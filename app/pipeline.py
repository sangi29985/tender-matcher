"""The daily pipeline: sync notices, then filter, rank, read, judge, check and score them."""

import asyncio
import logging
from datetime import UTC, date, datetime

import httpx
from anthropic import AsyncAnthropic
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.checker import check_quotes
from app.config import Settings
from app.database import MatchRecord, ProfileRecord, TenderRecord
from app.judge import PROMPT_VERSION, judge_tender
from app.matcher import hard_filter, rank_tenders
from app.rubric import RUBRIC_VERSION, score_criteria
from app.samgov import fetch_attachments, fetch_description, fetch_notices
from app.schemas import (
    CompanyProfile,
    DigestItem,
    DigestRun,
    FitLabel,
    Judgment,
    SkippedTender,
    Tender,
)

logger = logging.getLogger(__name__)
FIT_ORDER = {"strong": 0, "possible": 1, "no": 2}


class PipelineError(RuntimeError):
    """A problem the caller should show to the user (missing key, missing profile)."""


def tender_from_record(record: TenderRecord) -> Tender:
    # The downloaded notice text lives in its own column; `data` holds the API fields.
    data = {**record.data, "description": record.description or ""}
    if data["description"].startswith(("http://", "https://")) and not data.get("description_url"):
        # Rows synced before descriptions were downloaded stored the link as the text.
        data["description_url"], data["description"] = data["description"], ""
    return Tender.model_validate(data)


def judge_text(tender: Tender, attachments_text: str | None) -> str:
    """Everything the judge reads and every quote is checked against."""
    if attachments_text:
        return f"{tender.description}\n\n{attachments_text}".strip()
    return tender.description


def digest_order(item: DigestItem) -> tuple[int, date]:
    return FIT_ORDER[item.fit], item.tender.response_deadline or date.max


def item_from_match(match: MatchRecord, tender: Tender) -> DigestItem:
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


async def sync_tenders(db: Session, settings: Settings, start: date, end: date) -> dict:
    if not settings.sam_gov_api_key:
        raise PipelineError("SAM_GOV_API_KEY is not configured")
    tenders = await fetch_notices(settings.sam_gov_api_key, start, end)
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
            # Amended notice: store the new fields, read it again, and judge it again.
            record.data = serialized
            record.description = tender.description
            record.attachments_text = None
            db.execute(delete(MatchRecord).where(MatchRecord.notice_id == tender.notice_id))
            changed += 1
    db.commit()
    return {"fetched": len(tenders), "new": new, "changed": changed}


def load_profile(db: Session, company_id: str) -> CompanyProfile | None:
    record = db.get(ProfileRecord, company_id)
    return CompanyProfile.model_validate(record.profile) if record else None


async def _read_notice(
    http: httpx.AsyncClient,
    record: TenderRecord,
    tender: Tender,
    settings: Settings,
) -> tuple[Tender, str | None]:
    """Download the notice text and attachments the first time a notice is judged."""
    if not tender.description and tender.description_url:
        if not settings.sam_gov_api_key:
            raise PipelineError("Description not downloaded: SAM_GOV_API_KEY is not configured")
        try:
            text = await fetch_description(
                settings.sam_gov_api_key, tender.description_url, client=http
            )
        except httpx.HTTPError as exc:
            raise PipelineError("Could not download the notice description from SAM.gov") from exc
        record.description = text
        tender = tender.model_copy(update={"description": text})

    if record.attachments_text is None:
        if tender.resource_links and settings.sam_gov_api_key and settings.max_attachments:
            record.attachments_text = await fetch_attachments(
                settings.sam_gov_api_key,
                tender.resource_links,
                max_files=settings.max_attachments,
                max_bytes=settings.max_attachment_bytes,
                char_limit=settings.attachment_char_limit,
                client=http,
            )
        elif not tender.resource_links:
            record.attachments_text = ""
    return tender, record.attachments_text


async def run_company_digest(
    db: Session, company_id: str, settings: Settings, *, rejudge: bool = False
) -> DigestRun:
    profile = load_profile(db, company_id)
    if profile is None:
        raise PipelineError("Save a company profile before running the digest")

    records = {record.notice_id: record for record in db.scalars(select(TenderRecord)).all()}
    tenders = [tender_from_record(record) for record in records.values()]
    candidates = rank_tenders(hard_filter(tenders, profile), profile, settings.top_k)

    existing = {
        match.notice_id: match
        for match in db.scalars(
            select(MatchRecord).where(
                MatchRecord.company_id == company_id,
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
            items.append(item_from_match(match, tender))
        else:
            to_judge.append(tender)

    if to_judge and not settings.anthropic_api_key:
        raise PipelineError("ANTHROPIC_API_KEY is not configured")

    ready: list[tuple[Tender, str]] = []  # (tender as shown, full text the judge reads)
    async with httpx.AsyncClient(timeout=60) as http:
        for tender in to_judge:
            try:
                tender, attachments = await _read_notice(
                    http, records[tender.notice_id], tender, settings
                )
            except PipelineError as exc:
                logger.warning("Could not read notice %s: %s", tender.notice_id, exc)
                skip(tender, str(exc))
                continue
            text = judge_text(tender, attachments)
            if not text.strip():
                skip(tender, "The notice has no description text to assess")
                continue
            ready.append((tender, text))
    db.commit()

    client = AsyncAnthropic(api_key=settings.anthropic_api_key) if ready else None
    limit = asyncio.Semaphore(settings.judge_concurrency)

    async def judge(tender: Tender, text: str) -> tuple[Judgment, str]:
        async with limit:
            reading = tender.model_copy(update={"description": text})
            return await judge_tender(reading, profile, settings, client=client)

    results = await asyncio.gather(*(judge(t, text) for t, text in ready), return_exceptions=True)
    judged = 0
    for (tender, text), result in zip(ready, results, strict=True):
        if isinstance(result, BaseException):
            logger.error("Judgment failed for %s", tender.notice_id, exc_info=result)
            skip(tender, "The model call failed; see server logs")
            continue
        judgment, model = result
        quote_errors = check_quotes(judgment.criteria, text)
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
                company_id=company_id,
                notice_id=tender.notice_id,
                profile_version=profile.profile_version,
                **values,
            )
            db.add(match)
        items.append(item_from_match(match, tender))
        judged += 1

    db.commit()
    return DigestRun(
        items=sorted(items, key=digest_order),
        judged=judged,
        reused=len(candidates) - len(to_judge),
        skipped=skipped,
    )


def current_digest(db: Session, company_id: str) -> list[DigestItem]:
    profile_record = db.get(ProfileRecord, company_id)
    if not profile_record:
        return []
    matches = db.scalars(
        select(MatchRecord).where(
            MatchRecord.company_id == company_id,
            MatchRecord.profile_version == profile_record.profile_version,
            MatchRecord.prompt_version == PROMPT_VERSION,
        )
    ).all()
    digest = []
    for match in matches:
        record = db.get(TenderRecord, match.notice_id)
        if record:
            digest.append(item_from_match(match, tender_from_record(record)))
    return sorted(digest, key=digest_order)


def unsent_matches(db: Session, company_id: str) -> list[tuple[MatchRecord, DigestItem]]:
    """Strong and possible matches for the current profile not yet sent by email."""
    profile_record = db.get(ProfileRecord, company_id)
    if not profile_record:
        return []
    today = date.today()
    matches = db.scalars(
        select(MatchRecord).where(
            MatchRecord.company_id == company_id,
            MatchRecord.profile_version == profile_record.profile_version,
            MatchRecord.prompt_version == PROMPT_VERSION,
            MatchRecord.fit.in_([FitLabel.STRONG.value, FitLabel.POSSIBLE.value]),
            MatchRecord.notified_at.is_(None),
        )
    ).all()
    pending = []
    for match in matches:
        record = db.get(TenderRecord, match.notice_id)
        if record is None:
            continue
        item = item_from_match(match, tender_from_record(record))
        deadline = item.tender.response_deadline
        if deadline is None or deadline >= today:
            pending.append((match, item))
    return sorted(pending, key=lambda pair: digest_order(pair[1]))


def mark_notified(db: Session, matches: list[MatchRecord]) -> None:
    now = datetime.now(UTC)
    for match in matches:
        match.notified_at = now
    db.commit()
