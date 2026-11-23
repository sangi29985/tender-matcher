from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import pytest

from app import jobs, pipeline
from app.database import TenderRecord
from tests.test_digest_api import GOOD_TEXT, judgment, tender_data


@pytest.mark.anyio
async def test_daily_run_judges_every_company_and_emails_once(
    make_client, session_factory, settings
):
    from tests.conftest import PROFILE, sign_up

    for name in ["alice", "bob"]:
        client = make_client()
        sign_up(client, f"{name} co", f"{name}@x.test")
        client.put("/api/profile", json=PROFILE)
    nobody = make_client()
    sign_up(nobody, "No profile yet", "new@x.test")

    with session_factory() as session:
        session.add(TenderRecord(notice_id="n1", data=tender_data("n1"), description=GOOD_TEXT,
                                 attachments_text=""))
        session.commit()

    sent = []

    async def fake_sync(*_args, **_kwargs):
        return {"fetched": 0, "new": 0, "changed": 0}

    async def fake_judge(*_args, **_kwargs):
        return judgment(), "test-model"

    mail_settings = settings.model_copy(update={"smtp_host": "smtp.test", "smtp_from": "a@b.c"})
    with (
        patch.object(jobs, "SessionLocal", session_factory),
        patch.object(jobs, "sync_tenders", new=fake_sync),
        patch.object(pipeline, "judge_tender", new=fake_judge),
        patch.object(jobs, "send_email", new=lambda message, _s: sent.append(message)),
    ):
        first = await jobs.daily_run(mail_settings)
        second = await jobs.daily_run(mail_settings)

    assert first["companies"] == 2 and first["failed"] == 0 and first["emailed"] == 2
    assert sorted(message["To"] for message in sent) == ["alice@x.test", "bob@x.test"]
    assert "Cloud migration support" in sent[0].get_body(("plain",)).get_content()
    assert second["emailed"] == 0  # already sent


@pytest.mark.anyio
async def test_one_company_failing_does_not_stop_others(make_client, session_factory, settings):
    from tests.conftest import PROFILE, sign_up

    for name in ["alice", "bob"]:
        client = make_client()
        sign_up(client, name, f"{name}@x.test")
        client.put("/api/profile", json=PROFILE)

    calls = []

    async def flaky_digest(db, company_id, _settings, **_kwargs):
        calls.append(company_id)
        if len(calls) == 1:
            raise RuntimeError("boom")
        return pipeline.DigestRun(items=[], judged=0, reused=0, skipped=[])

    async def failing_sync(*_args, **_kwargs):
        raise RuntimeError("SAM.gov down")

    with (
        patch.object(jobs, "SessionLocal", session_factory),
        patch.object(jobs, "sync_tenders", new=failing_sync),
        patch.object(jobs, "run_company_digest", new=flaky_digest),
    ):
        summary = await jobs.daily_run(settings)
    assert len(calls) == 2
    assert summary["failed"] == 1 and summary["companies"] == 1


def test_seconds_until_next_run():
    now = datetime(2026, 11, 22, 10, 30, tzinfo=UTC)
    assert jobs.seconds_until_next_run(11, now) == 1800
    assert jobs.seconds_until_next_run(9, now) == timedelta(hours=22, minutes=30).total_seconds()

