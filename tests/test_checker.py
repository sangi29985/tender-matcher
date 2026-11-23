from app.checker import check_quotes
from app.schemas import Criteria


def test_accepts_exact_quotes_from_tender():
    criteria = Criteria.model_validate(
        {
            "requirements": [
                {
                    "type": "eligibility",
                    "requirement": "Small business",
                    "weight": "major",
                    "status": "met",
                    "quote": "This is a small business set-aside.",
                }
            ],
            "scope": {"value": "core", "quote": "The contractor will migrate cloud workloads."},
            "size": {"value": "in_range", "quote": "The estimated value is $400,000."},
            "teaming_needed": False,
        }
    )
    text = (
        "This is a small business set-aside. "
        "The contractor will migrate cloud workloads. "
        "The estimated value is $400,000."
    )
    assert check_quotes(criteria, text) == []


def test_rejects_missing_or_nonverbatim_quotes():
    criteria = Criteria.model_validate(
        {
            "requirements": [
                {
                    "type": "eligibility",
                    "requirement": "Small business",
                    "weight": "major",
                    "status": "met",
                    "quote": "Small-business set-aside",
                }
            ],
            "scope": {"value": "core", "quote": "migrate workloads"},
            "size": {"value": "in_range", "quote": ""},
            "teaming_needed": False,
        }
    )
    errors = check_quotes(criteria, "This is a small business set-aside. Migrate cloud workloads.")
    assert len(errors) == 3
    assert "not found verbatim" in errors[0]
    assert "not found verbatim" in errors[1]
    assert "needs a quote" in errors[2]


def test_quotes_tolerate_formatting_differences():
    criteria = Criteria.model_validate(
        {
            "requirements": [],
            "scope": {"value": "core", "quote": "The contractor's team will migrate  workloads"},
            "size": {"value": "unknown", "quote": ""},
            "teaming_needed": False,
        }
    )
    text = "The Contractor’s team\nwill migrate workloads &amp; data."
    assert check_quotes(criteria, text) == []
