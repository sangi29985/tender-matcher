from app.schemas import Criteria, FitLabel, Score, SizeValue

RUBRIC_VERSION = "v1-draft"


def score_criteria(criteria: Criteria) -> Score:
    requirements = criteria.requirements

    if any(item.status == "not_met" and item.type == "eligibility" for item in requirements):
        return Score(fit=FitLabel.NO, reason_code="NO_ELIGIBILITY")
    if any(item.status == "not_met" and item.type == "experience" for item in requirements):
        return Score(fit=FitLabel.NO, reason_code="NO_EXPERIENCE")
    if criteria.scope.value == "none":
        return Score(fit=FitLabel.NO, reason_code="NO_SCOPE")
    if criteria.size.value == SizeValue.FAR:
        return Score(fit=FitLabel.NO, reason_code="NO_SIZE")

    unknown_requirements = [item for item in requirements if item.status == "unknown"]
    strong_requirements = len(unknown_requirements) <= 1 and all(
        item.weight == "minor" for item in unknown_requirements
    )
    strong_size = criteria.size.value in {SizeValue.IN_RANGE, SizeValue.UNKNOWN}
    if (
        criteria.scope.value == "core"
        and strong_requirements
        and strong_size
        and not criteria.teaming_needed
    ):
        return Score(fit=FitLabel.STRONG, reason_code="STRONG")

    if unknown_requirements:
        reason_code = "POSS_UNKNOWN_REQ"
    elif criteria.scope.value == "partial":
        reason_code = "POSS_PARTIAL_SCOPE"
    elif criteria.size.value == SizeValue.NEAR:
        reason_code = "POSS_SIZE"
    elif criteria.teaming_needed:
        reason_code = "POSS_TEAMING"
    else:
        reason_code = "POSS_SIZE"
    return Score(fit=FitLabel.POSSIBLE, reason_code=reason_code)
