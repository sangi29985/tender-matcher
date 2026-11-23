from datetime import date, datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, model_validator


class FitLabel(StrEnum):
    STRONG = "strong"
    POSSIBLE = "possible"
    NO = "no"


class RequirementType(StrEnum):
    ELIGIBILITY = "eligibility"
    EXPERIENCE = "experience"


class RequirementStatus(StrEnum):
    MET = "met"
    NOT_MET = "not_met"
    UNKNOWN = "unknown"


class RequirementWeight(StrEnum):
    MINOR = "minor"
    MAJOR = "major"


class ScopeValue(StrEnum):
    CORE = "core"
    PARTIAL = "partial"
    NONE = "none"


class SizeValue(StrEnum):
    IN_RANGE = "in_range"
    NEAR = "near"
    FAR = "far"
    UNKNOWN = "unknown"


class ContractSize(BaseModel):
    min: float = Field(ge=0)
    max: float = Field(gt=0)

    @model_validator(mode="after")
    def validate_range(self) -> "ContractSize":
        if self.min > self.max:
            raise ValueError("contract_size_usd.min must not exceed max")
        return self


class PastContract(BaseModel):
    client: str
    summary: str
    value_usd: float | None = Field(default=None, ge=0)


class ProfileFields(BaseModel):
    model_config = ConfigDict(extra="forbid")

    services: list[str] = Field(min_length=1)
    naics_codes: list[str] = Field(default_factory=list)
    set_aside_eligibility: list[str] = Field(default_factory=list)
    locations_served: list[str] = Field(default_factory=list)
    contract_size_usd: ContractSize
    certifications: list[str] = Field(default_factory=list)
    clearances: list[str] = Field(default_factory=list)
    past_contracts: list[PastContract] = Field(default_factory=list)
    exclusions: list[str] = Field(default_factory=list)


class CompanyProfile(ProfileFields):
    company_id: str = ""
    profile_version: int = Field(default=1, ge=1)


class ProfileDraft(BaseModel):
    """A profile proposed from company documents; the owner reviews it before saving."""

    model_config = ConfigDict(extra="forbid")

    profile: ProfileFields
    notes: list[str] = Field(
        default_factory=list,
        description="Anything guessed, ambiguous or missing that the owner should check.",
    )


class SignupInput(BaseModel):
    company_name: str = Field(min_length=1, max_length=200)
    email: str = Field(min_length=3, max_length=320, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    password: str = Field(min_length=10, max_length=200)


class LoginInput(BaseModel):
    email: str = Field(max_length=320)
    password: str = Field(max_length=200)


class AccountOut(BaseModel):
    email: str
    company_name: str
    email_digest: bool
    email_configured: bool
    last_update: datetime | None = None


class PasswordResetRequest(BaseModel):
    email: str = Field(max_length=320)


class PasswordResetInput(BaseModel):
    token: str = Field(min_length=10, max_length=200)
    password: str = Field(min_length=10, max_length=200)


class AccountSettings(BaseModel):
    email_digest: bool


class Requirement(BaseModel):
    type: RequirementType
    requirement: str
    weight: RequirementWeight
    status: RequirementStatus
    quote: str = ""


class ScopeCriterion(BaseModel):
    value: ScopeValue
    quote: str


class SizeCriterion(BaseModel):
    value: SizeValue
    quote: str = ""


class Criteria(BaseModel):
    requirements: list[Requirement] = Field(default_factory=list)
    scope: ScopeCriterion
    size: SizeCriterion
    teaming_needed: bool


class Judgment(BaseModel):
    criteria: Criteria
    fit_reasons: list[str] = Field(min_length=1)
    summary: str


class Tender(BaseModel):
    notice_id: str
    title: str
    agency: str = ""
    description: str = ""
    description_url: str | None = None
    resource_links: list[str] = Field(default_factory=list)
    response_deadline: date | None = None
    questions_due: date | None = None
    notice_type: str = ""
    set_aside: str | None = None
    naics_code: str | None = None
    location: str | None = None
    link: HttpUrl | None = None


class Score(BaseModel):
    fit: FitLabel
    reason_code: str


class DigestItem(BaseModel):
    tender: Tender
    criteria: Criteria
    fit: FitLabel
    reason_code: str
    fit_reasons: list[str]
    summary: str
    rubric_version: str
    prompt_version: str
    model: str


class SkippedTender(BaseModel):
    notice_id: str
    title: str
    reason: str


class DigestRun(BaseModel):
    items: list[DigestItem]
    judged: int
    reused: int
    skipped: list[SkippedTender]


class FeedbackInput(BaseModel):
    decision: str
    reason_code: str | None = None
    reason_text: str | None = None

    @model_validator(mode="after")
    def validate_feedback(self) -> "FeedbackInput":
        if self.decision not in {"pursue", "not_relevant"}:
            raise ValueError("decision must be 'pursue' or 'not_relevant'")
        if self.decision == "not_relevant" and self.reason_code not in {
            "NO_ELIGIBILITY",
            "NO_EXPERIENCE",
            "NO_SCOPE",
            "NO_SIZE",
            "other",
        }:
            raise ValueError("not_relevant feedback requires a valid reason_code")
        if self.decision == "not_relevant" and self.reason_code == "other":
            if not self.reason_text or not self.reason_text.strip():
                raise ValueError("other feedback requires reason_text")
        elif self.reason_text is not None:
            raise ValueError("reason_text is only valid with reason_code 'other'")
        if self.decision == "pursue" and self.reason_code is not None:
            raise ValueError("pursue feedback must not include a reason_code")
        return self
