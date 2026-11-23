from datetime import date, timedelta
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import main
from app.database import Base, TenderRecord, get_db
from app.schemas import Judgment

DEADLINE = date.today() + timedelta(days=30)
GOOD_TEXT = "The contractor will provide cloud migration services."


def tender_data(notice_id, title="Cloud migration support", **overrides):
    data = {
        "notice_id": notice_id,
        "title": title,
        "agency": "Sample Agency",
        "response_deadline": DEADLINE.isoformat(),
        "notice_type": "Solicitation",
        "link": f"https://sam.gov/opp/{notice_id}",
    }
    data.update(overrides)
    return data


def judgment(scope_quote=GOOD_TEXT):
    return Judgment.model_validate(
        {
            "criteria": {
                "requirements": [],
                "scope": {"value": "core", "quote": scope_quote},
                "size": {"value": "unknown", "quote": ""},
                "teaming_needed": False,
            },
            "fit_reasons": ["Cloud migration is a core service."],
            "summary": "Cloud migration services are requested.",
        }
    )


@pytest.fixture
def app_env():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

    def override_db():
        session = session_factory()
        try:
            yield session
        finally:
            session.close()

    main.app.dependency_overrides[get_db] = override_db
    settings = main.get_settings().model_copy(
        update={"top_k": 5, "anthropic_api_key": "test-key", "sam_gov_api_key": "sam-key"}
    )
    calls: list[str] = []
    answers: dict[str, Judgment] = {}

    async def fake_judge(tender, *_args, **_kwargs):
        calls.append(tender.notice_id)
        return answers.get(tender.notice_id, judgment()), "test-model"

    def add(notice_id, description, **overrides):
        with session_factory() as session:
            session.add(
                TenderRecord(
                    notice_id=notice_id,
                    data=tender_data(notice_id, **overrides),
                    description=description,
                )
            )
            session.commit()

    with (
        patch.object(main, "init_db"),
        patch.object(main, "judge_tender", new=fake_judge),
        patch.object(main, "get_settings", return_value=settings),
        TestClient(main.app) as client,
    ):
        response = client.put(
            "/api/profile",
            json={"services": ["cloud migration"], "contract_size_usd": {"min": 1000, "max": 1e5}},
        )
        assert response.status_code == 200
        yield client, add, calls, answers

    main.app.dependency_overrides.pop(get_db, None)
    engine.dispose()


def test_digest_run_scores_persists_and_accepts_feedback(app_env):
    client, add, calls, _ = app_env
    add("notice-1", GOOD_TEXT)

    response = client.post("/api/digest/run")
    assert response.status_code == 200, response.text
    run = response.json()
    assert run["judged"] == 1 and run["skipped"] == []
    assert run["items"][0]["fit"] == "strong"
    assert run["items"][0]["reason_code"] == "STRONG"
    assert run["items"][0]["tender"]["response_deadline"] == DEADLINE.isoformat()

    assert client.get("/api/digest").json()[0]["fit"] == "strong"
    assert client.post("/api/feedback/notice-1", json={"decision": "pursue"}).status_code == 200


def test_second_run_reuses_existing_judgments(app_env):
    client, add, calls, _ = app_env
    add("notice-1", GOOD_TEXT)

    client.post("/api/digest/run")
    run = client.post("/api/digest/run").json()
    assert calls == ["notice-1"]
    assert run["reused"] == 1 and run["judged"] == 0
    assert len(run["items"]) == 1

    client.post("/api/digest/run", params={"rejudge": True})
    assert calls == ["notice-1", "notice-1"]


def test_ungrounded_judgment_is_skipped_without_losing_others(app_env):
    client, add, _, answers = app_env
    add("good", GOOD_TEXT)
    add("bad", "Cloud migration for a small agency.", title="Cloud migration pilot")
    answers["bad"] = judgment(scope_quote="A quote that is not in the notice")

    response = client.post("/api/digest/run")
    assert response.status_code == 200, response.text
    run = response.json()
    assert [item["tender"]["notice_id"] for item in run["items"]] == ["good"]
    assert [item["notice_id"] for item in run["skipped"]] == ["bad"]
    assert len(client.get("/api/digest").json()) == 1


def test_description_is_downloaded_before_judging(app_env):
    client, add, calls, _ = app_env
    url = "https://api.sam.gov/prod/opportunities/v1/noticedesc?noticeid=n1"
    add("n1", "", description_url=url)

    async def fake_fetch(api_key, fetched_url, **_kwargs):
        assert (api_key, fetched_url) == ("sam-key", url)
        return GOOD_TEXT

    with patch.object(main, "fetch_description", new=fake_fetch):
        run = client.post("/api/digest/run").json()
    assert calls == ["n1"]
    assert run["items"][0]["fit"] == "strong"
