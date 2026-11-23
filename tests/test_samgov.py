from datetime import date

import httpx
import pytest

from app.samgov import fetch_description, fetch_notices, html_to_text, map_notice, parse_sam_date


def test_parse_sam_dates():
    assert parse_sam_date("2026-11-14T17:00:00-05:00") == date(2026, 11, 14)
    assert parse_sam_date("11/14/2026") == date(2026, 11, 14)
    assert parse_sam_date(None) is None


def test_map_notice():
    tender = map_notice(
        {
            "noticeId": "abc123",
            "title": "Cloud services",
            "department": "Agency",
            "type": "Solicitation",
            "responseDeadLine": "11/30/2026",
            "typeOfSetAside": "SBA",
            "naicsCode": "541512",
            "placeOfPerformance": {"state": {"name": "Virginia"}},
            "uiLink": "https://sam.gov/opp/abc123",
            "description": "Cloud migration services.",
        }
    )
    assert tender.notice_id == "abc123"
    assert tender.response_deadline == date(2026, 11, 30)
    assert tender.location == "Virginia"
    assert str(tender.link) == "https://sam.gov/opp/abc123"


@pytest.mark.anyio
async def test_fetch_paginates_all_notices():
    calls = []

    def handler(request):
        calls.append(request)
        offset = int(request.url.params["offset"])
        entries = (
            [{"noticeId": "one"}]
            if offset == 0
            else [{"noticeId": "two"}]
        )
        return httpx.Response(200, json={"opportunitiesData": entries, "totalRecords": 2})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        notices = await fetch_notices(
            "test-key", date(2026, 11, 1), date(2026, 11, 2), client=client
        )

    assert [notice.notice_id for notice in notices] == ["one", "two"]
    assert [int(request.url.params["offset"]) for request in calls] == [0, 1]


def test_map_notice_keeps_description_link_separate():
    tender = map_notice(
        {
            "noticeId": "abc123",
            "description": "https://api.sam.gov/prod/opportunities/v1/noticedesc?noticeid=abc123",
        }
    )
    assert tender.description == ""
    assert tender.description_url.endswith("noticeid=abc123")


def test_html_to_text_strips_markup():
    html = "<p>Cloud&nbsp;migration</p><ul><li>Item&nbsp;one</li></ul><script>x()</script>"
    assert html_to_text(html) == "Cloud migration\n\nItem one"


@pytest.mark.anyio
async def test_fetch_description_reads_json_body_with_key():
    def handler(request):
        assert request.url.params["api_key"] == "test-key"
        return httpx.Response(200, json={"description": "<p>Migrate &amp; host apps.</p>"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        text = await fetch_description(
            "test-key", "https://api.sam.gov/prod/opportunities/v1/noticedesc?noticeid=x",
            client=client,
        )
    assert text == "Migrate & host apps."


@pytest.mark.anyio
async def test_fetch_skips_malformed_notices():
    def handler(request):
        return httpx.Response(
            200,
            json={"opportunitiesData": [{"title": "no id"}, {"noticeId": "ok"}], "totalRecords": 2},
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        notices = await fetch_notices("k", date(2026, 11, 1), date(2026, 11, 2), client=client)
    assert [notice.notice_id for notice in notices] == ["ok"]
