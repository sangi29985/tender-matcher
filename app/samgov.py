import asyncio
import logging
import re
from datetime import date, datetime
from html import unescape
from html.parser import HTMLParser
from typing import Any

import httpx
from pydantic import ValidationError

from app.schemas import Tender

logger = logging.getLogger(__name__)

SAM_SEARCH_URL = "https://api.sam.gov/opportunities/v2/search"

_BLOCK_TAGS = {
    "p", "div", "br", "li", "ul", "ol", "tr", "table", "h1", "h2", "h3", "h4", "h5", "h6",
    "section", "article", "header", "footer", "blockquote", "pre",
}


RETRY_STATUSES = {429, 500, 502, 503, 504}


async def get_with_retry(
    http: httpx.AsyncClient, url, *, params=None, attempts: int = 4, base_delay: float = 2.0
) -> httpx.Response:
    """GET with backoff on rate limits, server errors and timeouts (SAM.gov has all three)."""
    for attempt in range(1, attempts + 1):
        try:
            response = await http.get(url, params=params)
        except (httpx.TimeoutException, httpx.TransportError):
            if attempt == attempts:
                raise
            await asyncio.sleep(base_delay * 2 ** (attempt - 1))
            continue
        if response.status_code not in RETRY_STATUSES or attempt == attempts:
            response.raise_for_status()
            return response
        retry_after = response.headers.get("retry-after", "")
        delay = float(retry_after) if retry_after.isdigit() else base_delay * 2 ** (attempt - 1)
        logger.warning("SAM.gov returned %s; retrying in %.0fs", response.status_code, delay)
        await asyncio.sleep(min(delay, 60))
    raise AssertionError("unreachable")


def parse_sam_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).date()
    except ValueError:
        try:
            return datetime.strptime(value, "%m/%d/%Y").date()
        except ValueError:
            raise ValueError(f"Unrecognized SAM.gov date format: {value!r}") from None


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._skip = 0

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag in {"script", "style"}:
            self._skip += 1
        elif tag in _BLOCK_TAGS:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style"} and self._skip:
            self._skip -= 1
        elif tag in _BLOCK_TAGS:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self._skip:
            self.parts.append(data)


def html_to_text(value: str) -> str:
    """Turn a SAM.gov description (often HTML) into plain text the judge can quote."""
    parser = _TextExtractor()
    parser.feed(value)
    parser.close()
    text = unescape("".join(parser.parts)).replace("\xa0", " ")
    lines = (re.sub(r"[ \t\r\f\v]+", " ", line).strip() for line in text.split("\n"))
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


def map_notice(data: dict[str, Any]) -> Tender:
    place = data.get("placeOfPerformance") or {}
    state = place.get("state") or {}
    # The search API returns `description` as a link to the noticedesc endpoint, not the text.
    raw_description = (data.get("description") or "").strip()
    is_link = raw_description.startswith(("http://", "https://"))
    return Tender(
        notice_id=str(data["noticeId"]),
        title=data.get("title") or "Untitled opportunity",
        agency=" / ".join(
            item for item in (data.get("department"), data.get("subTier")) if item
        ),
        description="" if is_link else html_to_text(raw_description),
        description_url=raw_description if is_link else None,
        resource_links=[link for link in data.get("resourceLinks") or [] if isinstance(link, str)],
        response_deadline=parse_sam_date(data.get("responseDeadLine")),
        questions_due=parse_sam_date(data.get("questionsDueDate")),
        notice_type=data.get("type") or "",
        set_aside=data.get("typeOfSetAside") or None,
        naics_code=data.get("naicsCode") or None,
        location=state.get("name") or state.get("code") or None,
        link=data.get("uiLink") or None,
    )


async def fetch_notices(
    api_key: str,
    posted_from: date,
    posted_to: date,
    *,
    client: httpx.AsyncClient | None = None,
) -> list[Tender]:
    owns_client = client is None
    http = client or httpx.AsyncClient(timeout=30)
    notices: list[Tender] = []
    offset = 0
    try:
        while True:
            response = await get_with_retry(
                http,
                SAM_SEARCH_URL,
                params={
                    "api_key": api_key,
                    "postedFrom": posted_from.strftime("%m/%d/%Y"),
                    "postedTo": posted_to.strftime("%m/%d/%Y"),
                    "limit": 1000,
                    "offset": offset,
                },
            )
            payload = response.json()
            page = payload.get("opportunitiesData", [])
            for item in page:
                try:
                    notices.append(map_notice(item))
                except (KeyError, ValueError, ValidationError):
                    # One malformed notice must not abort the whole sync.
                    logger.warning("Skipping malformed SAM.gov notice %s", item.get("noticeId"))
            total = int(payload.get("totalRecords", offset + len(page)))
            offset += len(page)
            if not page or offset >= total:
                break
    finally:
        if owns_client:
            await http.aclose()
    return notices


def _with_api_key(link: str, api_key: str) -> httpx.URL:
    url = httpx.URL(link)
    host = url.host or ""
    # Never send the API key to a host other than SAM.gov.
    if host == "sam.gov" or host.endswith(".sam.gov"):
        return url.copy_set_param("api_key", api_key)
    return url


def _filename(response: httpx.Response, fallback: str) -> str:
    disposition = response.headers.get("content-disposition", "")
    match = re.search(r'filename\*?=(?:UTF-8\'\')?"?([^";]+)"?', disposition, re.IGNORECASE)
    return match.group(1).strip() if match else fallback


async def _download(
    http: httpx.AsyncClient, url: httpx.URL, max_bytes: int
) -> tuple[bytes, httpx.Response]:
    async with http.stream("GET", url, follow_redirects=True) as response:
        response.raise_for_status()
        chunks, size = [], 0
        async for chunk in response.aiter_bytes():
            size += len(chunk)
            if size > max_bytes:
                raise ValueError(f"Attachment is larger than {max_bytes} bytes")
            chunks.append(chunk)
        return b"".join(chunks), response


async def fetch_attachments(
    api_key: str,
    links: list[str],
    *,
    max_files: int,
    max_bytes: int,
    char_limit: int,
    client: httpx.AsyncClient | None = None,
) -> str:
    """Download a notice's attachments and return their combined text, labelled by file."""
    from app.documents import UnsupportedDocument, extract_text

    owns_client = client is None
    http = client or httpx.AsyncClient(timeout=60)
    sections: list[str] = []
    try:
        for index, link in enumerate(links[:max_files], start=1):
            try:
                content, response = await _download(http, _with_api_key(link, api_key), max_bytes)
                name = _filename(response, f"attachment-{index}")
                text = extract_text(
                    content,
                    content_type=response.headers.get("content-type", ""),
                    filename=name,
                )
            except (httpx.HTTPError, ValueError, UnsupportedDocument) as exc:
                logger.info("Skipping attachment %s: %s", index, exc)
                continue
            if text:
                sections.append(f"=== Attachment: {name} ===\n{text}")
        if len(links) > max_files:
            sections.append(f"[{len(links) - max_files} more attachments were not read]")
    finally:
        if owns_client:
            await http.aclose()

    combined = "\n\n".join(sections)
    if len(combined) > char_limit:
        combined = combined[:char_limit] + "\n[Attachment text cut off here: too long to read]"
    return combined


async def fetch_description(
    api_key: str, url: str, *, client: httpx.AsyncClient | None = None
) -> str:
    """Fetch a notice's full description text from the noticedesc link."""
    owns_client = client is None
    http = client or httpx.AsyncClient(timeout=30)
    try:
        response = await get_with_retry(http, url, params={"api_key": api_key})
        body = response.text
        if "json" in response.headers.get("content-type", ""):
            body = response.json().get("description") or ""
        return html_to_text(body)
    finally:
        if owns_client:
            await http.aclose()
