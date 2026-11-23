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
            response = await http.get(
                SAM_SEARCH_URL,
                params={
                    "api_key": api_key,
                    "postedFrom": posted_from.strftime("%m/%d/%Y"),
                    "postedTo": posted_to.strftime("%m/%d/%Y"),
                    "limit": 1000,
                    "offset": offset,
                },
            )
            response.raise_for_status()
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


async def fetch_description(
    api_key: str, url: str, *, client: httpx.AsyncClient | None = None
) -> str:
    """Fetch a notice's full description text from the noticedesc link."""
    owns_client = client is None
    http = client or httpx.AsyncClient(timeout=30)
    try:
        response = await http.get(url, params={"api_key": api_key})
        response.raise_for_status()
        body = response.text
        if "json" in response.headers.get("content-type", ""):
            body = response.json().get("description") or ""
        return html_to_text(body)
    finally:
        if owns_client:
            await http.aclose()
