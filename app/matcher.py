import re
from datetime import date, timedelta

from app.schemas import CompanyProfile, Tender

ALLOWED_NOTICE_TYPES = {"solicitation", "combined synopsis/solicitation"}
STATE_ALIASES = {
    "alabama": "al", "alaska": "ak", "arizona": "az", "arkansas": "ar",
    "california": "ca", "colorado": "co", "connecticut": "ct", "delaware": "de",
    "florida": "fl", "georgia": "ga", "hawaii": "hi", "idaho": "id",
    "illinois": "il", "indiana": "in", "iowa": "ia", "kansas": "ks",
    "kentucky": "ky", "louisiana": "la", "maine": "me", "maryland": "md",
    "massachusetts": "ma", "michigan": "mi", "minnesota": "mn", "mississippi": "ms",
    "missouri": "mo", "montana": "mt", "nebraska": "ne", "nevada": "nv",
    "new hampshire": "nh", "new jersey": "nj", "new mexico": "nm", "new york": "ny",
    "north carolina": "nc", "north dakota": "nd", "ohio": "oh", "oklahoma": "ok",
    "oregon": "or", "pennsylvania": "pa", "rhode island": "ri", "south carolina": "sc",
    "south dakota": "sd", "tennessee": "tn", "texas": "tx", "utah": "ut",
    "vermont": "vt", "virginia": "va", "washington": "wa", "west virginia": "wv",
    "wisconsin": "wi", "wyoming": "wy", "district of columbia": "dc",
}


def _normalized_location(location: str) -> str:
    normalized = location.strip().casefold()
    return STATE_ALIASES.get(normalized, normalized)


def hard_filter(
    tenders: list[Tender], profile: CompanyProfile, today: date | None = None
) -> list[Tender]:
    today = today or date.today()
    deadline_cutoff = today + timedelta(days=5)
    set_asides = {item.strip().casefold() for item in profile.set_aside_eligibility}
    locations = {_normalized_location(item) for item in profile.locations_served}
    serves_remote = "remote" in locations
    candidates: list[Tender] = []

    for tender in tenders:
        if tender.notice_type.strip().casefold() not in ALLOWED_NOTICE_TYPES:
            continue
        if tender.response_deadline is not None and tender.response_deadline <= deadline_cutoff:
            continue
        if tender.set_aside and tender.set_aside.strip().casefold() not in set_asides:
            continue
        if tender.location and locations and not serves_remote:
            if _normalized_location(tender.location) not in locations:
                continue
        candidates.append(tender)
    return candidates


def rank_tenders(tenders: list[Tender], profile: CompanyProfile, limit: int) -> list[Tender]:
    terms = set(_tokens(" ".join(profile.services)))
    if not terms:
        return tenders[:limit]

    def relevance(tender: Tender) -> tuple[float, str]:
        description_terms = set(_tokens(f"{tender.title} {tender.description}"))
        score = len(terms & description_terms) / len(terms)
        return score, tender.notice_id

    return sorted(tenders, key=relevance, reverse=True)[:limit]


def _tokens(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", text.casefold())
