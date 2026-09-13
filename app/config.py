from pathlib import Path

import yaml
from pydantic import BaseModel, Field, field_validator, model_validator


class EligibleSetAside(BaseModel):
    code: str
    description: str | None = None

    @field_validator("code")
    @classmethod
    def nonempty_code(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("set-aside code cannot be empty")
        return value


class CompanyProfile(BaseModel):
    company_name: str
    minimum_days_until_due: int = Field(ge=0)
    maximum_days_until_due: int = Field(ge=0)
    target_naics: list[str] = Field(default_factory=list)
    eligible_set_asides: list[EligibleSetAside] = Field(default_factory=list)
    allow_unrestricted: bool = False
    target_departments: list[str] = Field(default_factory=list)
    target_agencies: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def valid_window(self) -> "CompanyProfile":
        if self.minimum_days_until_due > self.maximum_days_until_due:
            raise ValueError("minimum_days_until_due cannot exceed maximum_days_until_due")
        return self


def load_company_profile(path: str | Path = "config/company_profile.yaml") -> CompanyProfile:
    profile_path = Path(path)
    try:
        data = yaml.safe_load(profile_path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ValueError(f"Company profile not found: {profile_path}") from exc
    if not isinstance(data, dict):
        raise ValueError(f"Company profile must be a YAML mapping: {profile_path}")
    return CompanyProfile.model_validate(data)
