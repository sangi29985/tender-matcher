from types import SimpleNamespace
from unittest.mock import patch

import pytest

from app import main
from app.config import Settings
from app.profile_builder import draft_profile
from app.schemas import ProfileDraft
from tests.conftest import sign_up

DRAFT = ProfileDraft.model_validate(
    {
        "profile": {
            "services": ["cloud migration"],
            "naics_codes": ["541512"],
            "contract_size_usd": {"min": 10000, "max": 1000000},
        },
        "notes": ["Contract size was not stated; please set it."],
    }
)


@pytest.mark.anyio
async def test_draft_profile_uses_structured_output():
    class FakeMessages:
        async def parse(self, **kwargs):
            assert kwargs["output_format"] is ProfileDraft
            assert "<company_documents>\nWe migrate clouds." in kwargs["messages"][0]["content"]
            return SimpleNamespace(stop_reason="end_turn", parsed_output=DRAFT)

    client = SimpleNamespace(beta=SimpleNamespace(messages=FakeMessages()))
    draft = await draft_profile(
        "We migrate clouds.", Settings(anthropic_api_key="k"), client=client
    )
    assert draft.profile.services == ["cloud migration"]


@pytest.mark.anyio
async def test_draft_profile_rejects_empty_text():
    with pytest.raises(ValueError):
        await draft_profile("   ", Settings(anthropic_api_key="k"))


def test_draft_endpoint_reads_uploaded_file_and_saves_nothing(make_client):
    client = make_client()
    sign_up(client)
    seen = {}

    async def fake_draft(source, _settings):
        seen["source"] = source
        return DRAFT

    with patch.object(main, "draft_profile", new=fake_draft):
        response = client.post(
            "/api/profile/draft",
            data={"text": "Website: we do helpdesk."},
            files={"file": ("cap.txt", b"Capability: cloud migration", "text/plain")},
        )
    assert response.status_code == 200, response.text
    assert response.json()["notes"] == DRAFT.notes
    assert "we do helpdesk" in seen["source"] and "Capability: cloud migration" in seen["source"]
    assert client.get("/api/profile").json() is None  # the owner must confirm first
