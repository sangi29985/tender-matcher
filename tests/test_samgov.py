from datetime import date

import httpx
import pytest

from app.samgov import (
    fetch_attachments,
    fetch_description,
    fetch_notices,
    html_to_text,
    map_notice,
    parse_sam_date,
)


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


def test_map_notice_keeps_resource_links():
    tender = map_notice({"noticeId": "a", "resourceLinks": ["https://sam.gov/f/1", None]})
    assert tender.resource_links == ["https://sam.gov/f/1"]


@pytest.mark.anyio
async def test_attachments_are_labelled_capped_and_key_only_sent_to_sam():
    seen = {}

    def handler(request):
        seen[request.url.host] = request.url.params.get("api_key")
        if request.url.host == "huge.sam.gov":
            return httpx.Response(200, content=b"x" * 2000, headers={"content-type": "text/plain"})
        return httpx.Response(
            200,
            content=b"Offerors must hold a facility clearance. " * 10,
            headers={
                "content-type": "text/plain",
                "content-disposition": 'attachment; filename="SOW.txt"',
            },
        )

    links = [
        "https://sam.gov/api/files/1/download?api_key=null",
        "https://other.example.com/file.txt",
        "https://huge.sam.gov/file.txt",
        "https://sam.gov/never-read",
    ]
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        text = await fetch_attachments(
            "secret", links, max_files=3, max_bytes=1000, char_limit=1000, client=client
        )
    assert seen["sam.gov"] == "secret"
    assert seen["other.example.com"] is None  # key never leaves SAM.gov
    assert text.startswith("=== Attachment: SOW.txt ===\nOfferors must hold")
    assert "[1 more attachments were not read]" in text
    assert "huge" not in text  # over the size limit, skipped


@pytest.mark.anyio
async def test_attachment_text_is_cut_with_a_marker():
    def handler(request):
        return httpx.Response(200, content=b"word " * 5000, headers={"content-type": "text/plain"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        text = await fetch_attachments(
            "k", ["https://sam.gov/a"], max_files=5, max_bytes=10**6, char_limit=1000,
            client=client,
        )
    assert text.endswith("[Attachment text cut off here: too long to read]")


@pytest.mark.anyio
async def test_get_with_retry_backs_off_on_rate_limits():
    from app.samgov import get_with_retry

    statuses = [429, 503, 200]

    def handler(request):
        return httpx.Response(statuses.pop(0), headers={"retry-after": "0"}, json={})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        response = await get_with_retry(client, "https://api.sam.gov/x", base_delay=0)
    assert response.status_code == 200 and statuses == []


@pytest.mark.anyio
async def test_get_with_retry_gives_up_and_raises():
    from app.samgov import get_with_retry

    def handler(request):
        return httpx.Response(503)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(httpx.HTTPStatusError):
            await get_with_retry(client, "https://api.sam.gov/x", attempts=2, base_delay=0)
