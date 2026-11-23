from datetime import date, timedelta
from unittest.mock import patch

import pytest

from app import pipeline
from app.database import TenderRecord
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


def judgment(scope_quote=GOOD_TEXT, requirements=()):
    return Judgment.model_validate(
        {
            "criteria": {
                "requirements": list(requirements),
                "scope": {"value": "core", "quote": scope_quote},
                "size": {"value": "unknown", "quote": ""},
                "teaming_needed": False,
            },
            "fit_reasons": ["Cloud migration is a core service."],
            "summary": "Cloud migration services are requested.",
        }
    )


@pytest.fixture
def env(session_factory):
    calls: list[tuple[str, str]] = []
    answers: dict[str, Judgment] = {}

    async def fake_judge(tender, *_args, **_kwargs):
        calls.append((tender.notice_id, tender.description))
        return answers.get(tender.notice_id, judgment()), "test-model"

    def add(notice_id, description, attachments_text="", **overrides):
        with session_factory() as session:
            session.add(
                TenderRecord(
                    notice_id=notice_id,
                    data=tender_data(notice_id, **overrides),
                    description=description,
                    attachments_text=attachments_text,
                )
            )
            session.commit()

    with patch.object(pipeline, "judge_tender", new=fake_judge):
        yield add, calls, answers


def test_digest_run_scores_persists_and_accepts_feedback(client, env):
    add, _, _ = env
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


def test_second_run_reuses_existing_judgments(client, env):
    add, calls, _ = env
    add("notice-1", GOOD_TEXT)

    client.post("/api/digest/run")
    run = client.post("/api/digest/run").json()
    assert len(calls) == 1
    assert run["reused"] == 1 and run["judged"] == 0
    assert len(run["items"]) == 1

    client.post("/api/digest/run", params={"rejudge": True})
    assert len(calls) == 2


def test_ungrounded_judgment_is_skipped_without_losing_others(client, env):
    add, _, answers = env
    add("good", GOOD_TEXT)
    add("bad", "Cloud migration for a small agency.", title="Cloud migration pilot")
    answers["bad"] = judgment(scope_quote="A quote that is not in the notice")

    response = client.post("/api/digest/run")
    assert response.status_code == 200, response.text
    run = response.json()
    assert [item["tender"]["notice_id"] for item in run["items"]] == ["good"]
    assert [item["notice_id"] for item in run["skipped"]] == ["bad"]
    assert len(client.get("/api/digest").json()) == 1


def test_description_and_attachments_are_read_before_judging(client, env):
    add, calls, answers = env
    url = "https://api.sam.gov/prod/opportunities/v1/noticedesc?noticeid=n1"
    add("n1", "", attachments_text=None, description_url=url, resource_links=["https://sam.gov/f/1"])
    attachment = "=== Attachment: sow.pdf ===\nOfferors must hold ISO 27001 certification."
    answers["n1"] = judgment(
        requirements=[
            {
                "type": "eligibility",
                "requirement": "ISO 27001",
                "weight": "major",
                "status": "met",
                "quote": "Offerors must hold ISO 27001 certification.",
            }
        ]
    )

    async def fake_description(api_key, fetched_url, **_kwargs):
        assert (api_key, fetched_url) == ("sam-key", url)
        return GOOD_TEXT

    async def fake_attachments(api_key, links, **_kwargs):
        assert links == ["https://sam.gov/f/1"]
        return attachment

    with (
        patch.object(pipeline, "fetch_description", new=fake_description),
        patch.object(pipeline, "fetch_attachments", new=fake_attachments),
    ):
        run = client.post("/api/digest/run").json()
    # The judge read both, and the quote from the attachment passed the check.
    assert calls == [("n1", f"{GOOD_TEXT}\n\n{attachment}")]
    assert run["items"][0]["fit"] == "strong", run


def test_digest_requires_a_profile(make_client):
    from tests.conftest import sign_up

    client = make_client()
    sign_up(client)
    response = client.post("/api/digest/run")
    assert response.status_code == 409
