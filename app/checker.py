import re
from html import unescape

from app.schemas import Criteria

_CHARACTER_MAP = str.maketrans(
    {
        "‘": "'", "’": "'", "“": '"', "”": '"',
        "–": "-", "—": "-", " ": " ",
    }
)


def normalize(text: str) -> str:
    """Normalise formatting differences that don't change the words of a quote."""
    text = unescape(text).translate(_CHARACTER_MAP)
    return re.sub(r"\s+", " ", text).strip().casefold()


def check_quotes(criteria: Criteria, tender_text: str) -> list[str]:
    errors: list[str] = []
    source = normalize(tender_text)

    def found(quote: str) -> bool:
        return normalize(quote) in source

    for index, requirement in enumerate(criteria.requirements):
        if requirement.status != "unknown" and not requirement.quote:
            errors.append(f"requirements[{index}] needs a quote for a known status")
        if requirement.quote and not found(requirement.quote):
            errors.append(f"requirements[{index}] quote was not found verbatim")

    if not criteria.scope.quote:
        errors.append("scope needs a quote")
    elif not found(criteria.scope.quote):
        errors.append("scope quote was not found verbatim")

    if criteria.size.value != "unknown" and not criteria.size.quote:
        errors.append("size needs a quote for a known value")
    elif criteria.size.quote and not found(criteria.size.quote):
        errors.append("size quote was not found verbatim")

    return errors
