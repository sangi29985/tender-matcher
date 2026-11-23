from datetime import date

from app.config import Settings
from app.emailer import build_digest_email
from app.schemas import DigestItem


def test_email_escapes_notice_text():
    item = DigestItem.model_validate(
        {
            "tender": {
                "notice_id": "n1",
                "title": "<script>alert(1)</script> Cloud",
                "response_deadline": date(2027, 1, 5),
                "link": "https://sam.gov/opp/n1",
            },
            "criteria": {
                "requirements": [],
                "scope": {"value": "core", "quote": "q"},
                "size": {"value": "unknown"},
                "teaming_needed": False,
            },
            "fit": "strong",
            "reason_code": "STRONG",
            "fit_reasons": ["x"],
            "summary": "Fits & more",
            "rubric_version": "v",
            "prompt_version": "p",
            "model": "m",
        }
    )
    settings = Settings(smtp_from="digest@app.test", app_base_url="https://app.test")
    message = build_digest_email(
        [item], company_name="Acme", recipient="o@a.test", settings=settings
    )
    html = message.get_body(("html",)).get_content()
    assert "<script>" not in html and "&lt;script&gt;" in html
    assert "Fits &amp; more" in html
    assert message["Subject"] == "1 new tender matches for Acme (1 strong)"
    assert "https://app.test" in message.get_body(("plain",)).get_content()
