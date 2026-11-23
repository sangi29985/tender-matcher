from datetime import date, timedelta

from app.auth import hash_password, verify_password
from app.database import MatchRecord, TenderRecord
from tests.conftest import PROFILE, sign_up


def test_password_hashing_round_trip():
    stored = hash_password("correct-horse-battery")
    assert stored.startswith("scrypt$")
    assert verify_password("correct-horse-battery", stored)
    assert not verify_password("wrong-password", stored)
    assert not verify_password("anything", "not-a-hash")


def test_api_requires_sign_in(make_client):
    client = make_client()
    for method, url in [
        ("get", "/api/me"),
        ("get", "/api/profile"),
        ("get", "/api/digest"),
        ("post", "/api/digest/run"),
        ("post", "/api/sync"),
    ]:
        assert getattr(client, method)(url).status_code == 401, url


def test_signup_login_logout(make_client):
    client = make_client()
    account = sign_up(client, email="Owner@Acme.test")
    assert account["email"] == "owner@acme.test"
    assert client.get("/api/me").status_code == 200

    assert client.post("/api/auth/logout").status_code == 204
    assert client.get("/api/me").status_code == 401

    bad = client.post(
        "/api/auth/login", json={"email": "owner@acme.test", "password": "wrong-password"}
    )
    assert bad.status_code == 401
    good = client.post(
        "/api/auth/login", json={"email": "owner@acme.test", "password": "correct-horse-battery"}
    )
    assert good.status_code == 200
    assert client.get("/api/me").json()["company_name"] == "Acme IT"


def test_duplicate_email_and_short_password_rejected(make_client):
    client = make_client()
    sign_up(client)
    duplicate = client.post(
        "/api/auth/signup",
        json={"company_name": "X", "email": "owner@acme.test", "password": "long-enough-pw"},
    )
    assert duplicate.status_code == 409
    short = client.post(
        "/api/auth/signup",
        json={"company_name": "X", "email": "x@x.test", "password": "short"},
    )
    assert short.status_code == 422


def test_companies_cannot_see_each_other(make_client, session_factory):
    alice, bob = make_client(), make_client()
    sign_up(alice, "Alice Co", "alice@a.test")
    sign_up(bob, "Bob Co", "bob@b.test")
    alice.put("/api/profile", json=PROFILE)

    with session_factory() as session:
        company_id = alice.get("/api/profile").json()["company_id"]
        session.add(
            TenderRecord(
                notice_id="n1",
                data={
                    "notice_id": "n1",
                    "title": "Cloud",
                    "notice_type": "Solicitation",
                    "response_deadline": (date.today() + timedelta(days=30)).isoformat(),
                },
                description="Cloud migration.",
            )
        )
        session.add(
            MatchRecord(
                company_id=company_id, notice_id="n1", profile_version=1,
                criteria={
                    "requirements": [], "scope": {"value": "core", "quote": "Cloud migration."},
                    "size": {"value": "unknown", "quote": ""}, "teaming_needed": False,
                },
                fit="strong", reason_code="STRONG", fit_reasons=["x"], summary="s",
                rubric_version="v1-draft", prompt_version="judge-v3", model="m",
            )
        )
        session.commit()

    assert len(alice.get("/api/digest").json()) == 1
    assert bob.get("/api/profile").json() is None
    assert bob.get("/api/digest").json() == []


def test_email_setting_toggle(make_client):
    client = make_client()
    sign_up(client)
    response = client.put("/api/me/settings", json={"email_digest": False})
    assert response.json()["email_digest"] is False
