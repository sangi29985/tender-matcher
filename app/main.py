import asyncio
import logging
import uuid
from contextlib import asynccontextmanager
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import httpx
from fastapi import (
    Depends,
    FastAPI,
    File,
    Form,
    HTTPException,
    Query,
    Request,
    Response,
    UploadFile,
)
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import delete, func, select, text
from sqlalchemy.orm import Session

from app.auth import (
    CurrentUser,
    consume_password_reset,
    create_password_reset,
    current_user,
    end_session,
    hash_password,
    start_session,
    verify_password,
)
from app.config import get_settings
from app.database import (
    CompanyRecord,
    FeedbackRecord,
    JobRunRecord,
    MatchRecord,
    ProfileRecord,
    SessionRecord,
    TenderRecord,
    UserRecord,
    get_db,
    init_db,
)
from app.documents import UnsupportedDocument, extract_text
from app.emailer import build_reset_email, email_configured, send_email
from app.pipeline import (
    PipelineError,
    current_digest,
    load_profile,
    run_company_digest,
    sync_tenders,
)
from app.profile_builder import draft_profile
from app.rubric import RUBRIC_VERSION
from app.schemas import (
    AccountOut,
    AccountSettings,
    CompanyProfile,
    DigestItem,
    DigestRun,
    FeedbackInput,
    LoginInput,
    PasswordResetInput,
    PasswordResetRequest,
    ProfileDraft,
    ProfileFields,
    SignupInput,
)
from app.security import SecurityMiddleware, login_throttle

logger = logging.getLogger(__name__)
templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))
MAX_UPLOAD_BYTES = 15_000_000
# Compared against when an email is unknown, so failed logins take the same time either way.
_DUMMY_HASH = hash_password("not-a-real-password")


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    yield


app = FastAPI(title="Tender Matcher", version="0.2.0", lifespan=lifespan)
app.add_middleware(SecurityMiddleware, hsts=get_settings().cookie_secure)


def _pipeline_error(exc: PipelineError) -> HTTPException:
    message = str(exc)
    status = 409 if "profile" in message else 503
    return HTTPException(status_code=status, detail=message)


@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    return templates.TemplateResponse(request=request, name="index.html")


@app.get("/health")
def health():
    """Liveness: the process is up."""
    return {"status": "ok"}


def _last_run(db: Session) -> JobRunRecord | None:
    return db.scalar(select(JobRunRecord).order_by(JobRunRecord.started_at.desc()).limit(1))


def _aware(value: datetime | None) -> datetime | None:
    return value.replace(tzinfo=UTC) if value and value.tzinfo is None else value


@app.get("/health/ready")
def ready(response: Response, db: Session = Depends(get_db)):
    """Readiness for uptime monitoring: database reachable and the daily data fresh."""
    try:
        db.execute(text("SELECT 1"))
    except Exception:
        logger.exception("Database check failed")
        response.status_code = 503
        return {"status": "error", "database": "unreachable"}
    run = _last_run(db)
    finished = _aware(run.finished_at) if run else None
    stale_after = timedelta(hours=get_settings().stale_after_hours)
    fresh = bool(finished and datetime.now(UTC) - finished < stale_after)
    healthy = fresh and run.status == "ok"
    if not healthy:
        response.status_code = 503
    return {
        "status": "ok" if healthy else "degraded",
        "database": "ok",
        "last_daily_run": finished.isoformat() if finished else None,
        "last_daily_status": run.status if run else None,
    }


# --- Accounts -------------------------------------------------------------------------------


def _account(auth: CurrentUser, db: Session | None = None) -> AccountOut:
    run = _last_run(db) if db is not None else None
    return AccountOut(
        email=auth.user.email,
        company_name=auth.company.name,
        email_digest=auth.company.email_digest,
        email_configured=email_configured(get_settings()),
        last_update=_aware(run.finished_at) if run and run.status == "ok" else None,
    )


@app.post("/api/auth/signup", response_model=AccountOut, status_code=201)
def signup(payload: SignupInput, response: Response, db: Session = Depends(get_db)):
    if not get_settings().allow_signup:
        raise HTTPException(status_code=403, detail="Sign-up is closed")
    email = payload.email.strip().lower()
    if db.scalar(select(func.count()).select_from(UserRecord).where(UserRecord.email == email)):
        raise HTTPException(status_code=409, detail="An account with this email already exists")
    company = CompanyRecord(id=str(uuid.uuid4()), name=payload.company_name.strip())
    user = UserRecord(
        id=str(uuid.uuid4()),
        email=email,
        password_hash=hash_password(payload.password),
        company_id=company.id,
    )
    db.add_all([company, user])
    db.commit()
    start_session(db, response, user.id)
    return _account(CurrentUser(user=user, company=company))


@app.post("/api/auth/login", response_model=AccountOut)
def login(
    payload: LoginInput, request: Request, response: Response, db: Session = Depends(get_db)
):
    settings = get_settings()
    email = payload.email.strip().lower()
    address = request.client.host if request.client else "unknown"
    keys = [f"email:{email}", f"ip:{address}"]
    window = settings.login_lockout_minutes * 60
    if login_throttle.blocked(keys[:1], settings.login_max_failures, window) or (
        login_throttle.blocked(keys[1:], settings.login_max_failures * 5, window)
    ):
        raise HTTPException(
            status_code=429,
            detail=f"Too many failed sign-ins. Try again in {settings.login_lockout_minutes} "
            "minutes or reset your password.",
        )
    user = db.scalar(select(UserRecord).where(UserRecord.email == email))
    valid = verify_password(payload.password, user.password_hash if user else _DUMMY_HASH)
    if not user or not valid:
        login_throttle.failed(keys)
        raise HTTPException(status_code=401, detail="Email or password is incorrect")
    login_throttle.succeeded(keys[:1])
    start_session(db, response, user.id)
    return _account(CurrentUser(user=user, company=db.get(CompanyRecord, user.company_id)), db)


@app.post("/api/auth/reset-request", status_code=202)
async def request_password_reset(payload: PasswordResetRequest, db: Session = Depends(get_db)):
    """Email a reset link. Always answers the same way, so it can't reveal who has an account."""
    settings = get_settings()
    if not email_configured(settings):
        raise HTTPException(
            status_code=503,
            detail="Password reset by email isn't set up on this server; contact the operator.",
        )
    user = db.scalar(select(UserRecord).where(UserRecord.email == payload.email.strip().lower()))
    if user:
        token = create_password_reset(db, user.id)
        try:
            await asyncio.to_thread(
                send_email, build_reset_email(user.email, token, settings), settings
            )
        except Exception:
            logger.exception("Could not send the password reset email")
    return {"detail": "If that email has an account, a reset link is on its way."}


@app.post("/api/auth/reset")
def reset_password(payload: PasswordResetInput, db: Session = Depends(get_db)):
    user = consume_password_reset(db, payload.token, payload.password)
    if user is None:
        raise HTTPException(status_code=400, detail="This reset link is invalid or has expired")
    login_throttle.succeeded([f"email:{user.email}"])
    return {"detail": "Password changed. Sign in with your new password."}


@app.post("/api/auth/logout", status_code=204)
def logout(request: Request, response: Response, db: Session = Depends(get_db)):
    end_session(db, request, response)


@app.get("/api/me", response_model=AccountOut)
def me(auth: CurrentUser = Depends(current_user), db: Session = Depends(get_db)):
    return _account(auth, db)


@app.delete("/api/me", status_code=204)
def delete_account(
    request: Request,
    response: Response,
    auth: CurrentUser = Depends(current_user),
    db: Session = Depends(get_db),
):
    """Delete the company, its users, profile, matches and feedback."""
    end_session(db, request, response)
    company_id = auth.company_id
    user_ids = select(UserRecord.id).where(UserRecord.company_id == company_id)
    db.execute(delete(SessionRecord).where(SessionRecord.user_id.in_(user_ids)))
    for model in (FeedbackRecord, MatchRecord, ProfileRecord, UserRecord):
        db.execute(delete(model).where(model.company_id == company_id))
    db.execute(delete(CompanyRecord).where(CompanyRecord.id == company_id))
    db.commit()


@app.put("/api/me/settings", response_model=AccountOut)
def update_settings(
    payload: AccountSettings,
    auth: CurrentUser = Depends(current_user),
    db: Session = Depends(get_db),
):
    company = db.get(CompanyRecord, auth.company_id)
    company.email_digest = payload.email_digest
    db.commit()
    return _account(CurrentUser(user=auth.user, company=company), db)


# --- Profile --------------------------------------------------------------------------------


@app.get("/api/profile", response_model=CompanyProfile | None)
def read_profile(auth: CurrentUser = Depends(current_user), db: Session = Depends(get_db)):
    return load_profile(db, auth.company_id)


@app.put("/api/profile", response_model=CompanyProfile)
def save_profile(
    fields: ProfileFields,
    auth: CurrentUser = Depends(current_user),
    db: Session = Depends(get_db),
):
    current = db.get(ProfileRecord, auth.company_id)
    version = current.profile_version + 1 if current else 1
    profile = CompanyProfile(
        **fields.model_dump(), company_id=auth.company_id, profile_version=version
    )
    if current:
        current.profile_version = version
        current.profile = profile.model_dump(mode="json")
    else:
        db.add(
            ProfileRecord(
                company_id=auth.company_id,
                profile_version=version,
                profile=profile.model_dump(mode="json"),
            )
        )
    db.commit()
    return profile


@app.post("/api/profile/draft", response_model=ProfileDraft)
async def draft_profile_from_documents(
    text: str = Form(default=""),
    file: UploadFile | None = File(default=None),
    auth: CurrentUser = Depends(current_user),
):
    """Propose a profile from a capability statement. Nothing is saved until the owner saves."""
    if not get_settings().anthropic_api_key:
        raise HTTPException(status_code=503, detail="ANTHROPIC_API_KEY is not configured")
    source = text.strip()
    if file is not None and file.filename:
        content = await file.read(MAX_UPLOAD_BYTES + 1)
        if len(content) > MAX_UPLOAD_BYTES:
            raise HTTPException(status_code=413, detail="The file is larger than 15 MB")
        try:
            document = extract_text(
                content, content_type=file.content_type or "", filename=file.filename
            )
        except UnsupportedDocument as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        source = f"{source}\n\n=== {file.filename} ===\n{document}".strip()
    try:
        return await draft_profile(source, get_settings())
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Profile draft failed for company %s", auth.company_id)
        raise HTTPException(
            status_code=502, detail="Could not draft a profile; see server logs"
        ) from exc


# --- Tenders and digest ---------------------------------------------------------------------


@app.post("/api/sync")
async def sync_notices(
    posted_from: date | None = Query(default=None),
    posted_to: date | None = Query(default=None),
    _: CurrentUser = Depends(current_user),
    db: Session = Depends(get_db),
):
    end = posted_to or date.today()
    start = posted_from or end - timedelta(days=3)
    if start > end:
        raise HTTPException(status_code=422, detail="posted_from must not be after posted_to")
    if (end - start).days > 31:
        raise HTTPException(status_code=422, detail="Sync at most 31 days at a time")
    try:
        result = await sync_tenders(db, get_settings(), start, end)
    except PipelineError as exc:
        raise _pipeline_error(exc) from exc
    except (httpx.HTTPError, ValueError, KeyError) as exc:
        logger.exception("SAM.gov sync failed")
        raise HTTPException(status_code=502, detail="SAM.gov sync failed; see server logs") from exc
    return {**result, "posted_from": start, "posted_to": end}


@app.post("/api/digest/run", response_model=DigestRun)
async def run_digest(
    rejudge: bool = Query(default=False, description="Judge again even if a match exists"),
    auth: CurrentUser = Depends(current_user),
    db: Session = Depends(get_db),
):
    try:
        return await run_company_digest(db, auth.company_id, get_settings(), rejudge=rejudge)
    except PipelineError as exc:
        raise _pipeline_error(exc) from exc


@app.get("/api/digest", response_model=list[DigestItem])
def get_digest(auth: CurrentUser = Depends(current_user), db: Session = Depends(get_db)):
    return current_digest(db, auth.company_id)


@app.post("/api/feedback/{notice_id}")
def submit_feedback(
    notice_id: str,
    feedback: FeedbackInput,
    auth: CurrentUser = Depends(current_user),
    db: Session = Depends(get_db),
):
    if not db.get(TenderRecord, notice_id):
        raise HTTPException(status_code=404, detail="Tender not found")
    db.add(
        FeedbackRecord(
            company_id=auth.company_id,
            notice_id=notice_id,
            decision=feedback.decision,
            reason_code=feedback.reason_code,
            reason_text=feedback.reason_text,
            rubric_version=RUBRIC_VERSION,
        )
    )
    db.commit()
    return {"saved": True}
