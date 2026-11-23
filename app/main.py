import asyncio
import logging
from contextlib import asynccontextmanager
from datetime import date, timedelta
from pathlib import Path

import httpx
from anthropic import AsyncAnthropic
from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.checker import check_quotes
from app.config import get_settings
from app.database import (
    FeedbackRecord,
    MatchRecord,
    ProfileRecord,
    TenderRecord,
    get_db,
    init_db,
)
from app.judge import PROMPT_VERSION, judge_tender
from app.matcher import hard_filter, rank_tenders
from app.rubric import RUBRIC_VERSION, score_criteria
from app.samgov import fetch_description, fetch_notices
from app.schemas import (
    CompanyProfile,
    DigestItem,
    DigestRun,
    FeedbackInput,
    Judgment,
    SkippedTender,
    Tender,
)

logger = logging.getLogger(__name__)
templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))
FIT_ORDER = {"strong": 0, "possible": 1, "no": 2}


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    yield


app = FastAPI(title="Tender Matcher", version="0.1.0", lifespan=lifespan)


def _tender_from_record(record: TenderRecord) -> Tender:
    # The fetched description text lives in its own column; `data` holds the API fields.
    data = {**record.data, "description": record.description or ""}
    if data["description"].startswith(("http://", "https://")) and not data.get("description_url"):
        # Rows synced before descriptions were fetched stored the link as the text.
        data["description_url"], data["description"] = data["description"], ""
    return Tender.model_validate(data)


def _digest_order(item: DigestItem) -> tuple[int, date]:
    return FIT_ORDER[item.fit], item.tender.response_deadline or date.max


@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    return templates.TemplateResponse(request=request, name="index.html")


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/api/profile", response_model=CompanyProfile | None)
def read_profile(db: Session = Depends(get_db)):
    record = db.get(ProfileRecord, "default")
    return CompanyProfile.model_validate(record.profile) if record else None


@app.put("/api/profile", response_model=CompanyProfile)
def save_profile(profile: CompanyProfile, db: Session = Depends(get_db)):
    current = db.get(ProfileRecord, "default")
    version = current.profile_version + 1 if current else 1
    profile = profile.model_copy(update={"company_id": "default", "profile_version": version})
    if current:
        current.profile_version = version
        current.profile = profile.model_dump(mode="json")
    else:
        db.add(
            ProfileRecord(
                company_id="default",
                profile_version=version,
                profile=profile.model_dump(mode="json"),
            )
        )
    db.commit()
    return profile


@app.post("/api/sync")
async def sync_notices(
    posted_from: date | None = Query(default=None),
    posted_to: date | None = Query(default=None),
    db: Session = Depends(get_db),
):
    settings = get_settings()
    if not settings.sam_gov_api_key:
        raise HTTPException(status_code=503, detail="SAM_GOV_API_KEY is not configured")
    end = posted_to or date.today()
    start = posted_from or end - timedelta(days=3)
    if start > end:
        raise HTTPException(status_code=422, detail="posted_from must not be after posted_to")
    try:
        tenders = await fetch_notices(settings.sam_gov_api_key, start, end)
    except (httpx.HTTPError, ValueError, KeyError) as exc:
        logger.exception("SAM.gov sync failed")
        raise HTTPException(status_code=502, detail="SAM.gov sync failed; see server logs") from exc

    new = changed = 0
    for tender in tenders:
        record = db.get(TenderRecord, tender.notice_id)
        serialized = tender.model_dump(mode="json", exclude={"description"})
        if record is None:
            db.add(
                TenderRecord(
                    notice_id=tender.notice_id, data=serialized, description=tender.description
                )
            )
            new += 1
        elif record.data != serialized:
            # Amended notice: store the new fields, refetch its text, and judge it again.
            record.data = serialized
            record.description = tender.description
            db.execute(delete(MatchRecord).where(MatchRecord.notice_id == tender.notice_id))
            changed += 1
    db.commit()
    return {
        "fetched": len(tenders),
        "new": new,
        "changed": changed,
        "posted_from": start,
        "posted_to": end,
    }


@app.post("/api/digest/run", response_model=DigestRun)
async def run_digest(
    rejudge: bool = Query(default=False, description="Judge again even if a match exists"),
    db: Session = Depends(get_db),
):
    settings = get_settings()
    profile_record = db.get(ProfileRecord, "default")
    if not profile_record:
        raise HTTPException(
            status_code=409, detail="Save a company profile before running the digest"
        )
    profile = CompanyProfile.model_validate(profile_record.profile)
    records = {record.notice_id: record for record in db.scalars(select(TenderRecord)).all()}
    tenders = [_tender_from_record(record) for record in records.values()]
    candidates = rank_tenders(hard_filter(tenders, profile), profile, settings.top_k)

    existing = {
        match.notice_id: match
        for match in db.scalars(
            select(MatchRecord).where(
                MatchRecord.company_id == "default",
                MatchRecord.profile_version == profile.profile_version,
                MatchRecord.prompt_version == PROMPT_VERSION,
            )
        ).all()
    }
    items: list[DigestItem] = []
    skipped: list[SkippedTender] = []
    to_judge: list[Tender] = []

    def skip(tender: Tender, reason: str) -> None:
        skipped.append(SkippedTender(notice_id=tender.notice_id, title=tender.title, reason=reason))

    for tender in candidates:
        match = existing.get(tender.notice_id)
        if match and not rejudge:
            items.append(_item_from_match(match, tender))
        else:
            to_judge.append(tender)

    if to_judge and not settings.anthropic_api_key:
        raise HTTPException(status_code=503, detail="ANTHROPIC_API_KEY is not configured")

    # Fetch description text only for the tenders we are about to judge.
    ready: list[Tender] = []
    async with httpx.AsyncClient(timeout=30) as http:
        for tender in to_judge:
            if not tender.description and tender.description_url:
                if not settings.sam_gov_api_key:
                    skip(tender, "Description not downloaded: SAM_GOV_API_KEY is not configured")
                    continue
                try:
                    text = await fetch_description(
                        settings.sam_gov_api_key, tender.description_url, client=http
                    )
                except httpx.HTTPError:
                    logger.exception("Description fetch failed for %s", tender.notice_id)
                    skip(tender, "Could not download the notice description from SAM.gov")
                    continue
                records[tender.notice_id].description = text
                tender = tender.model_copy(update={"description": text})
            if not tender.description.strip():
                skip(tender, "The notice has no description text to assess")
                continue
            ready.append(tender)
    db.commit()

    client = AsyncAnthropic(api_key=settings.anthropic_api_key) if ready else None
    limit = asyncio.Semaphore(settings.judge_concurrency)

    async def judge(tender: Tender) -> tuple[Judgment, str]:
        async with limit:
            return await judge_tender(tender, profile, settings, client=client)

    results = await asyncio.gather(*(judge(t) for t in ready), return_exceptions=True)
    judged = 0
    for tender, result in zip(ready, results, strict=True):
        if isinstance(result, BaseException):
            logger.error("Judgment failed for %s", tender.notice_id, exc_info=result)
            skip(tender, "The model call failed; see server logs")
            continue
        judgment, model = result
        quote_errors = check_quotes(judgment.criteria, tender.description)
        if quote_errors:
            logger.warning("Ungrounded judgment for %s: %s", tender.notice_id, quote_errors)
            skip(tender, "The judgment quoted text that is not in the notice")
            continue
        score = score_criteria(judgment.criteria)
        values = {
            "criteria": judgment.criteria.model_dump(mode="json"),
            "fit": score.fit.value,
            "reason_code": score.reason_code,
            "fit_reasons": judgment.fit_reasons,
            "summary": judgment.summary,
            "rubric_version": RUBRIC_VERSION,
            "prompt_version": PROMPT_VERSION,
            "model": model,
        }
        match = existing.get(tender.notice_id)
        if match:
            for name, value in values.items():
                setattr(match, name, value)
        else:
            match = MatchRecord(
                company_id="default",
                notice_id=tender.notice_id,
                profile_version=profile.profile_version,
                **values,
            )
            db.add(match)
        items.append(_item_from_match(match, tender))
        judged += 1

    db.commit()
    return DigestRun(
        items=sorted(items, key=_digest_order),
        judged=judged,
        reused=len(candidates) - len(to_judge),
        skipped=skipped,
    )


def _item_from_match(match: MatchRecord, tender: Tender) -> DigestItem:
    return DigestItem(
        tender=tender,
        criteria=match.criteria,
        fit=match.fit,
        reason_code=match.reason_code,
        fit_reasons=match.fit_reasons,
        summary=match.summary,
        rubric_version=match.rubric_version,
        prompt_version=match.prompt_version,
        model=match.model,
    )


@app.get("/api/digest", response_model=list[DigestItem])
def get_digest(db: Session = Depends(get_db)):
    profile_record = db.get(ProfileRecord, "default")
    if not profile_record:
        return []
    matches = db.scalars(
        select(MatchRecord).where(
            MatchRecord.company_id == "default",
            MatchRecord.profile_version == profile_record.profile_version,
            MatchRecord.prompt_version == PROMPT_VERSION,
        )
    ).all()
    digest: list[DigestItem] = []
    for match in matches:
        tender_record = db.get(TenderRecord, match.notice_id)
        if tender_record:
            digest.append(_item_from_match(match, _tender_from_record(tender_record)))
    return sorted(digest, key=_digest_order)


@app.post("/api/feedback/{notice_id}")
def submit_feedback(
    notice_id: str, feedback: FeedbackInput, db: Session = Depends(get_db)
):
    if not db.get(TenderRecord, notice_id):
        raise HTTPException(status_code=404, detail="Tender not found")
    db.add(
        FeedbackRecord(
            company_id="default",
            notice_id=notice_id,
            decision=feedback.decision,
            reason_code=feedback.reason_code,
            reason_text=feedback.reason_text,
            rubric_version=RUBRIC_VERSION,
        )
    )
    db.commit()
    return {"saved": True}
