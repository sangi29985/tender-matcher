from datetime import date
from types import SimpleNamespace

import pytest

from app.config import Settings
from app.judge import judge_tender
from app.schemas import CompanyProfile, Judgment, Tender


@pytest.mark.anyio
async def test_judge_uses_structured_tool_and_returns_typed_output(monkeypatch):
    judgment_input = {
        "criteria": {
            "requirements": [],
            "scope": {"value": "core", "quote": "Build cloud software."},
            "size": {"value": "unknown", "quote": ""},
            "teaming_needed": False,
        },
        "fit_reasons": ["Cloud software is a core service."],
        "summary": "The notice requests cloud software.",
    }

    class FakeMessages:
        async def parse(self, **kwargs):
            assert kwargs["output_format"] is Judgment
            assert kwargs["model"] == "test-model"
            assert "tool_choice" not in kwargs
            prompt = kwargs["messages"][0]["content"]
            assert "<tender_description>\nBuild cloud software.\n" in prompt
            return SimpleNamespace(
                stop_reason="end_turn",
                model="test-model",
                parsed_output=Judgment.model_validate(judgment_input),
            )

    class FakeClient:
        def __init__(self, *, api_key):
            assert api_key == "test-key"
            self.beta = SimpleNamespace(messages=FakeMessages())

    monkeypatch.setattr("app.judge.AsyncAnthropic", FakeClient)
    tender = Tender(
        notice_id="n1",
        title="Cloud software",
        response_deadline=date(2027, 1, 1),
        description="Build cloud software.",
    )
    profile = CompanyProfile(
        services=["cloud software"],
        contract_size_usd={"min": 100, "max": 10000},
    )
    judgment, model = await judge_tender(
        tender,
        profile,
        Settings(anthropic_api_key="test-key", anthropic_model="test-model"),
    )

    assert judgment.summary == "The notice requests cloud software."
    assert model == "test-model"


@pytest.mark.anyio
async def test_judge_requires_api_key():
    with pytest.raises(RuntimeError, match="ANTHROPIC_API_KEY"):
        await judge_tender(
            Tender(notice_id="n1", title="Notice"),
            CompanyProfile(
                services=["cloud software"],
                contract_size_usd={"min": 100, "max": 10000},
            ),
            Settings(),
        )
