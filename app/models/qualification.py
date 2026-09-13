from pydantic import BaseModel, Field


class RuleResult(BaseModel):
    rule: str
    passed: bool
    reason: str


class QualificationResult(BaseModel):
    opportunity_id: str
    qualified: bool
    days_until_due: int | None = None
    rules: list[RuleResult] = Field(default_factory=list)
