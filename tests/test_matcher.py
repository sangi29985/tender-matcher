from datetime import date

from app.matcher import hard_filter, rank_tenders
from app.schemas import CompanyProfile, Tender


def profile():
    return CompanyProfile.model_validate(
        {
            "services": ["cloud migration", "IT helpdesk"],
            "set_aside_eligibility": ["SBA"],
            "locations_served": ["VA"],
            "contract_size_usd": {"min": 10000, "max": 1000000},
        }
    )


def tender(notice_id, **overrides):
    data = {
        "notice_id": notice_id,
        "title": f"Notice {notice_id}",
        "notice_type": "Solicitation",
        "response_deadline": date(2027, 1, 10),
        "description": "",
    }
    data.update(overrides)
    return Tender.model_validate(data)


def test_hard_filter_excludes_ineligible_or_urgent_notices():
    candidates = [
        tender("good", set_aside="SBA", location="Virginia"),
        tender("wrong-set-aside", set_aside="WOSB"),
        tender("wrong-location", location="California"),
        tender("closing-soon", response_deadline=date(2026, 11, 20)),
        tender("award", notice_type="Award Notice"),
    ]
    result = hard_filter(candidates, profile(), today=date(2026, 11, 16))
    assert [item.notice_id for item in result] == ["good"]


def test_hard_filter_excludes_set_aside_when_profile_has_no_eligibility():
    company = profile().model_copy(update={"set_aside_eligibility": []})
    result = hard_filter(
        [tender("set-aside", set_aside="SBA"), tender("open", set_aside=None)],
        company,
        today=date(2026, 11, 16),
    )
    assert [item.notice_id for item in result] == ["open"]


def test_rank_prioritizes_capability_overlap():
    notices = [
        tender("generic", description="Road maintenance and landscaping"),
        tender("match", description="Cloud migration and IT helpdesk support"),
    ]
    assert rank_tenders(notices, profile(), 1)[0].notice_id == "match"
