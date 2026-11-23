import base64
import hashlib
import hmac
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from fastapi import Depends, HTTPException, Request, Response
from sqlalchemy import delete
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import (
    CompanyRecord,
    PasswordResetRecord,
    SessionRecord,
    UserRecord,
    get_db,
)

SESSION_COOKIE = "tm_session"
_SCRYPT = {"n": 2**14, "r": 8, "p": 1}


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, dklen=32, **_SCRYPT)
    encode = base64.b64encode
    return f"scrypt${encode(salt).decode()}${encode(digest).decode()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        scheme, salt, digest = stored.split("$")
    except ValueError:
        return False
    if scheme != "scrypt":
        return False
    candidate = hashlib.scrypt(
        password.encode(), salt=base64.b64decode(salt), dklen=32, **_SCRYPT
    )
    return hmac.compare_digest(candidate, base64.b64decode(digest))


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def start_session(db: Session, response: Response, user_id: str) -> None:
    settings = get_settings()
    token = secrets.token_urlsafe(32)
    expires = datetime.now(UTC) + timedelta(days=settings.session_days)
    db.add(SessionRecord(token_hash=_token_hash(token), user_id=user_id, expires_at=expires))
    db.commit()
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=settings.session_days * 86400,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
    )


def end_session(db: Session, request: Request, response: Response) -> None:
    token = request.cookies.get(SESSION_COOKIE)
    if token:
        db.execute(delete(SessionRecord).where(SessionRecord.token_hash == _token_hash(token)))
        db.commit()
    response.delete_cookie(SESSION_COOKIE)


def end_all_sessions(db: Session, user_id: str) -> None:
    db.execute(delete(SessionRecord).where(SessionRecord.user_id == user_id))


RESET_MINUTES = 60


def create_password_reset(db: Session, user_id: str) -> str:
    """Return a one-time reset token valid for an hour; only its hash is stored."""
    db.execute(delete(PasswordResetRecord).where(PasswordResetRecord.user_id == user_id))
    token = secrets.token_urlsafe(32)
    db.add(
        PasswordResetRecord(
            token_hash=_token_hash(token),
            user_id=user_id,
            expires_at=datetime.now(UTC) + timedelta(minutes=RESET_MINUTES),
        )
    )
    db.commit()
    return token


def consume_password_reset(db: Session, token: str, new_password: str) -> UserRecord | None:
    record = db.get(PasswordResetRecord, _token_hash(token))
    if record is None:
        return None
    expires = record.expires_at
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=UTC)
    user = db.get(UserRecord, record.user_id)
    db.delete(record)
    if expires <= datetime.now(UTC) or user is None:
        db.commit()
        return None
    user.password_hash = hash_password(new_password)
    end_all_sessions(db, user.id)  # sign out everywhere after a reset
    db.commit()
    return user


@dataclass
class CurrentUser:
    user: UserRecord
    company: CompanyRecord

    @property
    def company_id(self) -> str:
        return self.company.id


def current_user(request: Request, db: Session = Depends(get_db)) -> CurrentUser:
    token = request.cookies.get(SESSION_COOKIE)
    record = db.get(SessionRecord, _token_hash(token)) if token else None
    if record is not None:
        expires = record.expires_at
        if expires.tzinfo is None:  # SQLite returns naive datetimes
            expires = expires.replace(tzinfo=UTC)
        if expires > datetime.now(UTC):
            user = db.get(UserRecord, record.user_id)
            company = db.get(CompanyRecord, user.company_id) if user else None
            if user and company:
                return CurrentUser(user=user, company=company)
        db.delete(record)
        db.commit()
    raise HTTPException(status_code=401, detail="Please sign in")
