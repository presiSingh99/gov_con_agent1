from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, Field


class Opportunity(BaseModel):
    """Source-independent representation of a contracting opportunity."""

    source: str = "sam.gov"
    notice_id: str
    solicitation_number: str | None = None
    title: str
    department: str | None = None
    agency: str | None = None
    office: str | None = None
    naics_codes: list[str] = Field(default_factory=list)
    set_aside_code: str | None = None
    set_aside_description: str | None = None
    posted_date: date | None = None
    proposal_due_date: datetime | None = None
    notice_type: str | None = None
    description: str | None = None
    ui_link: str | None = None
    resource_links: list[str] = Field(default_factory=list)
    raw_data: dict[str, Any] | None = None
