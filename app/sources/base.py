from typing import Protocol

from app.models.opportunity import Opportunity


class OpportunitySource(Protocol):
    async def list_opportunities(self) -> list[Opportunity]: ...
