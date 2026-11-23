import pytest
from pydantic import ValidationError

from app.schemas import FeedbackInput


def test_other_feedback_requires_explanation():
    with pytest.raises(ValidationError):
        FeedbackInput(decision="not_relevant", reason_code="other")

    feedback = FeedbackInput(
        decision="not_relevant",
        reason_code="other",
        reason_text="The agency is outside our service area.",
    )
    assert feedback.reason_text == "The agency is outside our service area."


def test_feedback_rejects_reason_for_pursue():
    with pytest.raises(ValidationError):
        FeedbackInput(decision="pursue", reason_code="NO_SIZE")
