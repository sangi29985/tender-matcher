import re
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app import jobs, main
from app.database import CompanyRecord, JobRunRecord, UserRecord
from tests.conftest import PROFILE, sign_up


def test_state_changing_api_calls_need_the_app_header(make_client):
    make_client()  # sets up the database override
    bare = TestClient(main.app)
    response = bare.post("/api/auth/login", json={"email": "a@b.c", "password": "x"})
    assert response.status_code == 403
    assert bare.get("/health").status_code == 200  # reads are unaffected


def test_security_headers_are_set(make_client):
    response = make_client().get("/")
    assert response.headers["X-Frame-Options"] == "DENY"
    assert "frame-ancestors 'none'" in response.headers["Content-Security-Policy"]
    assert make_client().get("/api/me").headers["Cache-Control"] == "no-store"


def test_repeated_failed_logins_are_locked_out(make_client, settings):
    client = make_client()
    sign_up(client)
    bad = {"email": "owner@acme.test", "password": "wrong-password"}
    for _ in range(settings.login_max_failures):
        assert client.post("/api/auth/login", json=bad).status_code == 401
    locked = client.post(
        "/api/auth/login", json={"email": "owner@acme.test", "password": "correct-horse-battery"}
    )
    assert locked.status_code == 429


def test_password_reset_by_email(make_client, settings):
    client = make_client()
    sign_up(client)
    sent = []
    mail = settings.model_copy(update={"smtp_host": "smtp.test", "smtp_from": "app@x.test"})
    with (
        patch.object(main, "get_settings", return_value=mail),
        patch.object(main, "send_email", new=lambda message, _s: sent.append(message)),
    ):
        unknown = client.post("/api/auth/reset-request", json={"email": "nobody@x.test"})
        known = client.post("/api/auth/reset-request", json={"email": "owner@acme.test"})
    assert unknown.status_code == known.status_code == 202
    assert unknown.json() == known.json()  # does not reveal who has an account
    assert len(sent) == 1
    token = re.search(r"#reset=([\w-]+)", sent[0].get_content()).group(1)

    changed = client.post("/api/auth/reset", json={"token": token, "password": "a-new-password-1"})
    assert changed.status_code == 200
    assert client.get("/api/me").status_code == 401  # signed out everywhere
    reused = client.post("/api/auth/reset", json={"token": token, "password": "another-pass-2"})
    assert reused.status_code == 400
    login = client.post(
        "/api/auth/login", json={"email": "owner@acme.test", "password": "a-new-password-1"}
    )
    assert login.status_code == 200


def test_reset_request_without_email_setup_says_so(make_client):
    client = make_client()
    assert client.post("/api/auth/reset-request", json={"email": "a@b.c"}).status_code == 503


def test_delete_account_removes_company_data(make_client, session_factory):
    client = make_client()
    sign_up(client)
    client.put("/api/profile", json=PROFILE)
    assert client.delete("/api/me").status_code == 204
    assert client.get("/api/me").status_code == 401
    with session_factory() as session:
        assert session.query(CompanyRecord).count() == 0
        assert session.query(UserRecord).count() == 0


def test_readiness_reports_stale_and_fresh_data(make_client, session_factory):
    client = make_client()
    stale = client.get("/health/ready")
    assert stale.status_code == 503 and stale.json()["status"] == "degraded"
    with session_factory() as session:
        session.add(JobRunRecord(status="ok", finished_at=datetime.now(UTC), summary={}))
        session.commit()
    fresh = client.get("/health/ready")
    assert fresh.status_code == 200, fresh.json()
    sign_up(client)
    assert client.get("/api/me").json()["last_update"] is not None


@pytest.mark.anyio
async def test_daily_run_is_recorded_and_failures_alert_the_admin(session_factory, settings):
    alerts = []

    async def failing_sync(*_args, **_kwargs):
        raise RuntimeError("SAM.gov down")

    alerting = settings.model_copy(
        update={"smtp_host": "smtp.test", "smtp_from": "a@x.test", "admin_email": "ops@x.test"}
    )
    with (
        patch.object(jobs, "SessionLocal", session_factory),
        patch.object(jobs, "sync_tenders", new=failing_sync),
        patch.object(jobs, "send_email", new=lambda message, _s: alerts.append(message)),
    ):
        await jobs.daily_run(alerting)
        assert not jobs.needs_catch_up()
        assert jobs.needs_catch_up(datetime.now(UTC) + timedelta(hours=25))

    with session_factory() as session:
        run = session.query(JobRunRecord).one()
        assert run.status == "partial" and run.finished_at is not None
    assert alerts[0]["To"] == "ops@x.test"
    assert "SAM.gov down" in alerts[0].get_content()
