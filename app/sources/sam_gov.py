import logging
from datetime import date, datetime, timedelta, timezone
from typing import Any

import httpx
from pydantic import ValidationError

from app.models.opportunity import Opportunity

LOGGER = logging.getLogger(__name__)
SAM_OPPORTUNITIES_URL = "https://api.sam.gov/opportunities/v2/search"


class SAMGovError(RuntimeError):
    """A safe, user-facing SAM.gov integration error."""


def _text(value: Any) -> str | None:
    if value is None:
        return None
    result = str(value).strip()
    return result or None


def _datetime(value: Any) -> datetime | None:
    text = _text(value)
    if not text:
        return None
    # SAM dates are ISO-8601; accepting Z explicitly keeps Python 3.11 portable.
    return datetime.fromisoformat(text.replace("Z", "+00:00"))


def map_sam_opportunity(record: dict[str, Any]) -> Opportunity:
    """Map documented Get Opportunities v2 fields into the internal model."""
    notice_id = _text(record.get("noticeId"))
    title = _text(record.get("title"))
    if not notice_id or not title:
        raise ValueError("record is missing required noticeId or title")

    hierarchy = [part.strip() for part in (_text(record.get("fullParentPathName")) or "").split(".") if part.strip()]
    naics_value = record.get("naicsCode")
    if isinstance(naics_value, list):
        naics_codes = [str(item).strip() for item in naics_value if str(item).strip()]
    elif normalized_naics := _text(naics_value):
        # A record normally has one documented naicsCode, while the internal model
        # intentionally supports more than one source-independent code.
        naics_codes = [normalized_naics]
    else:
        naics_codes = []

    resources = record.get("resourceLinks") or []
    if isinstance(resources, str):
        resources = [resources]
    if not isinstance(resources, list):
        resources = []

    return Opportunity(
        notice_id=notice_id,
        solicitation_number=_text(record.get("solicitationNumber")),
        title=title,
        department=hierarchy[0] if hierarchy else None,
        agency=hierarchy[1] if len(hierarchy) > 1 else None,
        office=hierarchy[-1] if len(hierarchy) > 2 else None,
        naics_codes=naics_codes,
        set_aside_code=_text(record.get("typeOfSetAside")),
        set_aside_description=_text(record.get("typeOfSetAsideDescription")),
        posted_date=date.fromisoformat(str(record["postedDate"])[:10]) if record.get("postedDate") else None,
        proposal_due_date=_datetime(record.get("responseDeadLine")),
        notice_type=_text(record.get("type")),
        description=_text(record.get("description")),
        ui_link=_text(record.get("uiLink")),
        resource_links=[str(item).strip() for item in resources if str(item).strip()],
        raw_data=record,
    )


class SAMGovOpportunitySource:
    """Async adapter for the official SAM.gov Get Opportunities Public API."""

    def __init__(
        self,
        api_key: str,
        *,
        posted_from: date | None = None,
        posted_to: date | None = None,
        page_size: int = 100,
        timeout_seconds: float = 30.0,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        if not api_key.strip():
            raise ValueError("SAM_API_KEY is missing; add it to .env")
        if not 1 <= page_size <= 1000:
            raise ValueError("page_size must be between 1 and 1000")
        today = datetime.now(timezone.utc).date()
        self.api_key = api_key
        self.posted_from = posted_from or today - timedelta(days=1)
        self.posted_to = posted_to or today
        if self.posted_from > self.posted_to:
            raise ValueError("posted_from cannot be after posted_to")
        self.page_size = page_size
        self.timeout = httpx.Timeout(timeout_seconds)
        self.client = client
        self.retrieved_count = 0
        self.skipped_count = 0

    async def list_opportunities(self) -> list[Opportunity]:
        owns_client = self.client is None
        client = self.client or httpx.AsyncClient(timeout=self.timeout)
        normalized: list[Opportunity] = []
        offset = 0
        try:
            while True:
                params = {
                    "api_key": self.api_key,
                    "postedFrom": self.posted_from.strftime("%m/%d/%Y"),
                    "postedTo": self.posted_to.strftime("%m/%d/%Y"),
                    "limit": self.page_size,
                    "offset": offset,
                }
                try:
                    response = await client.get(SAM_OPPORTUNITIES_URL, params=params, timeout=self.timeout)
                except httpx.TimeoutException as exc:
                    raise SAMGovError("SAM.gov request timed out") from exc
                except httpx.RequestError as exc:
                    raise SAMGovError(f"Could not reach SAM.gov: {exc.__class__.__name__}") from exc

                if response.status_code == 429:
                    retry_after = response.headers.get("Retry-After")
                    suffix = f" Retry after {retry_after} seconds." if retry_after else " Try again later."
                    raise SAMGovError("SAM.gov rate limit reached." + suffix)
                if response.status_code in (401, 403):
                    raise SAMGovError("SAM.gov rejected the API key or request authorization")
                try:
                    response.raise_for_status()
                except httpx.HTTPStatusError as exc:
                    raise SAMGovError(f"SAM.gov returned HTTP {response.status_code}") from exc
                try:
                    payload = response.json()
                except ValueError as exc:
                    raise SAMGovError("SAM.gov returned malformed JSON") from exc
                if not isinstance(payload, dict):
                    raise SAMGovError("SAM.gov returned an unexpected response shape")
                records = payload.get("opportunitiesData", [])
                if not isinstance(records, list):
                    raise SAMGovError("SAM.gov response has invalid opportunitiesData")

                self.retrieved_count += len(records)
                for record in records:
                    try:
                        if not isinstance(record, dict):
                            raise ValueError("record is not an object")
                        normalized.append(map_sam_opportunity(record))
                    except (ValueError, TypeError, ValidationError) as exc:
                        self.skipped_count += 1
                        LOGGER.warning("Skipping malformed SAM.gov opportunity at offset %d: %s", offset, exc)

                total = payload.get("totalRecords")
                try:
                    total_records = int(total) if total is not None else None
                except (TypeError, ValueError) as exc:
                    raise SAMGovError("SAM.gov response has invalid totalRecords") from exc
                offset += len(records)
                if not records or (total_records is not None and offset >= total_records) or len(records) < self.page_size:
                    break
            return normalized
        finally:
            if owns_client:
                await client.aclose()
