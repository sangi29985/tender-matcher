import pytest

from app.rubric import score_criteria
from app.schemas import Criteria, FitLabel


def criteria(
    *,
    requirements=None,
    scope="core",
    size="in_range",
    teaming=False,
):
    return Criteria.model_validate(
        {
            "requirements": requirements or [],
            "scope": {"value": scope, "quote": "Work includes cloud migration"},
            "size": {"value": size, "quote": "Estimated value: $400,000"},
            "teaming_needed": teaming,
        }
    )


def requirement(kind, status, weight="major"):
    return {
        "type": kind,
        "requirement": "Requirement",
        "weight": weight,
        "status": status,
        "quote": "Must have certification",
    }


@pytest.mark.parametrize(
    ("input_criteria", "label", "reason"),
    [
        (criteria(), FitLabel.STRONG, "STRONG"),
        (criteria(size="unknown"), FitLabel.STRONG, "STRONG"),
        (
            criteria(
                requirements=[requirement("eligibility", "not_met")], scope="none", size="far"
            ),
            FitLabel.NO,
            "NO_ELIGIBILITY",
        ),
        (
            criteria(requirements=[requirement("experience", "not_met")]),
            FitLabel.NO,
            "NO_EXPERIENCE",
        ),
        (criteria(scope="none"), FitLabel.NO, "NO_SCOPE"),
        (criteria(size="far"), FitLabel.NO, "NO_SIZE"),
        (
            criteria(requirements=[requirement("eligibility", "unknown", "minor")]),
            FitLabel.STRONG,
            "STRONG",
        ),
        (
            criteria(requirements=[requirement("eligibility", "unknown", "major")]),
            FitLabel.POSSIBLE,
            "POSS_UNKNOWN_REQ",
        ),
        (
            criteria(
                requirements=[
                    requirement("eligibility", "unknown", "minor"),
                    requirement("experience", "unknown", "minor"),
                ],
                scope="partial",
                size="near",
                teaming=True,
            ),
            FitLabel.POSSIBLE,
            "POSS_UNKNOWN_REQ",
        ),
        (criteria(scope="partial"), FitLabel.POSSIBLE, "POSS_PARTIAL_SCOPE"),
        (criteria(size="near"), FitLabel.POSSIBLE, "POSS_SIZE"),
        (criteria(teaming=True), FitLabel.POSSIBLE, "POSS_TEAMING"),
    ],
)
def test_score_criteria(input_criteria, label, reason):
    score = score_criteria(input_criteria)
    assert score.fit == label
    assert score.reason_code == reason
