"""Background jobs and admin commands.

    python -m app.jobs daily                 # run once: sync, build every digest, send emails
    python -m app.jobs schedule              # stay running and do the daily run every day
    python -m app.jobs set-password EMAIL    # set a user's password (prompts for it)
"""

import argparse
import asyncio
import getpass
import logging
import sys
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.auth import end_all_sessions, hash_password
from app.config import Settings, get_settings
from app.database import (
    CompanyRecord,
    JobRunRecord,
    PasswordResetRecord,
    ProfileRecord,
    SessionLocal,
    SessionRecord,
    UserRecord,
    init_db,
)
from app.emailer import build_alert_email, build_digest_email, email_configured, send_email
from app.pipeline import mark_notified, run_company_digest, sync_tenders, unsent_matches

logger = logging.getLogger("app.jobs")


async def send_company_digest(db: Session, company: CompanyRecord, settings: Settings) -> int:
    """Email the company's unsent strong/possible matches. Returns how many were sent."""
    if not company.email_digest or not email_configured(settings):
        return 0
    pending = unsent_matches(db, company.id)
    if not pending:
        return 0
    recipients = db.scalars(select(UserRecord.email).where(UserRecord.company_id == company.id))
    items = [item for _, item in pending]
    for recipient in recipients:
        message = build_digest_email(
            items, company_name=company.name, recipient=recipient, settings=settings
        )
        await asyncio.to_thread(send_email, message, settings)
    mark_notified(db, [match for match, _ in pending])
    return len(items)


async def _alert(settings: Settings, subject: str, body: str) -> None:
    if not (settings.admin_email and email_configured(settings)):
        logger.error("ALERT (no admin email configured): %s\n%s", subject, body)
        return
    try:
        await asyncio.to_thread(send_email, build_alert_email(subject, body, settings), settings)
    except Exception:
        logger.exception("Could not send the admin alert: %s", subject)


def _clean_expired(db: Session) -> None:
    now = datetime.now(UTC)
    db.execute(delete(SessionRecord).where(SessionRecord.expires_at < now))
    db.execute(delete(PasswordResetRecord).where(PasswordResetRecord.expires_at < now))
    db.commit()


async def daily_run(settings: Settings | None = None, *, today: date | None = None) -> dict:
    settings = settings or get_settings()
    today = today or date.today()
    summary: dict = {"synced": None, "companies": 0, "failed": 0, "emailed": 0, "errors": []}
    with SessionLocal() as db:
        run = JobRunRecord(status="running", summary={})
        db.add(run)
        db.commit()

        try:
            summary["synced"] = await sync_tenders(db, settings, today - timedelta(days=3), today)
        except Exception as exc:
            # Keep going: notices from earlier days can still be judged and emailed.
            logger.exception("SAM.gov sync failed")
            db.rollback()
            summary["errors"].append(f"SAM.gov sync failed: {exc}")

        company_ids = db.scalars(
            select(CompanyRecord.id).join(
                ProfileRecord, ProfileRecord.company_id == CompanyRecord.id
            )
        ).all()
        for company_id in company_ids:
            company = db.get(CompanyRecord, company_id)
            try:
                result = await run_company_digest(db, company_id, settings)
                summary["emailed"] += await send_company_digest(db, company, settings)
                summary["companies"] += 1
                logger.info(
                    "Digest for %s: %d items, %d judged, %d skipped",
                    company_id, len(result.items), result.judged, len(result.skipped),
                )
            except Exception as exc:
                # One company's failure must not stop the others.
                logger.exception("Daily run failed for company %s", company_id)
                db.rollback()
                summary["failed"] += 1
                summary["errors"].append(f"Company {company_id} ({company.name}): {exc}")

        try:
            _clean_expired(db)
        except Exception:
            logger.exception("Could not clean expired sessions")
            db.rollback()

        run = db.get(JobRunRecord, run.id)
        run.finished_at = datetime.now(UTC)
        run.status = "ok" if not summary["errors"] else "partial"
        run.summary = summary
        db.commit()

    if summary["errors"]:
        await _alert(
            settings,
            f"Daily run finished with {len(summary['errors'])} problem(s)",
            "\n".join(summary["errors"]) + "\n\nSee the worker logs for details.",
        )
    logger.info("Daily run finished: %s", summary)
    return summary


def seconds_until_next_run(hour_utc: int, now: datetime | None = None) -> float:
    now = now or datetime.now(UTC)
    target = now.replace(hour=hour_utc, minute=0, second=0, microsecond=0)
    if target <= now:
        target += timedelta(days=1)
    return (target - now).total_seconds()


def needs_catch_up(now: datetime | None = None) -> bool:
    """True when no daily run has finished in the last 24 hours (e.g. the worker was down)."""
    now = now or datetime.now(UTC)
    with SessionLocal() as db:
        last = db.scalar(
            select(JobRunRecord.finished_at)
            .where(JobRunRecord.finished_at.is_not(None))
            .order_by(JobRunRecord.finished_at.desc())
            .limit(1)
        )
    if last is None:
        return True
    if last.tzinfo is None:
        last = last.replace(tzinfo=UTC)
    return now - last > timedelta(hours=24)


async def schedule_forever(settings: Settings) -> None:
    if needs_catch_up():
        logger.info("No daily run in the last 24 hours; running now to catch up")
        try:
            await daily_run(settings)
        except Exception as exc:
            logger.exception("Catch-up run crashed")
            await _alert(settings, "Daily run crashed", f"{exc!r}\n\nSee the worker logs.")
    while True:
        wait = seconds_until_next_run(settings.daily_run_hour_utc)
        logger.info("Next daily run in %.1f hours", wait / 3600)
        await asyncio.sleep(wait)
        try:
            await daily_run(settings)
        except Exception as exc:
            logger.exception("Daily run crashed; will try again tomorrow")
            await _alert(settings, "Daily run crashed", f"{exc!r}\n\nSee the worker logs.")


def set_password(email: str) -> int:
    password = getpass.getpass("New password (at least 10 characters): ")
    if len(password) < 10:
        print("Password too short.", file=sys.stderr)
        return 1
    with SessionLocal() as db:
        user = db.scalar(select(UserRecord).where(UserRecord.email == email.strip().lower()))
        if user is None:
            print(f"No account for {email}.", file=sys.stderr)
            return 1
        user.password_hash = hash_password(password)
        end_all_sessions(db, user.id)
        db.commit()
    print("Password updated; the user is signed out everywhere.")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Tender Matcher background jobs")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("daily", help="Run the daily sync, digests and emails once")
    sub.add_parser("schedule", help="Run the daily job every day at DAILY_RUN_HOUR_UTC")
    reset = sub.add_parser("set-password", help="Set a user's password")
    reset.add_argument("email")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    init_db()
    settings = get_settings()
    if args.command == "daily":
        asyncio.run(daily_run(settings))
    elif args.command == "schedule":
        asyncio.run(schedule_forever(settings))
    else:
        sys.exit(set_password(args.email))


if __name__ == "__main__":
    main()
