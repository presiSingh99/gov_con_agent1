import re
from datetime import datetime, timezone

from app.config import CompanyProfile
from app.models.opportunity import Opportunity
from app.models.qualification import QualificationResult, RuleResult


def _normalize(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip().casefold()


class QualificationEngine:
    def __init__(self, profile: CompanyProfile) -> None:
        self.profile = profile

    def evaluate(self, opportunity: Opportunity, *, now: datetime | None = None) -> QualificationResult:
        now_utc = now or datetime.now(timezone.utc)
        if now_utc.tzinfo is None:
            now_utc = now_utc.replace(tzinfo=timezone.utc)
        else:
            now_utc = now_utc.astimezone(timezone.utc)

        date_rule, days = self._proposal_date(opportunity, now_utc)
        rules = [date_rule, self._naics(opportunity), self._set_aside(opportunity), self._organization(opportunity)]
        return QualificationResult(
            opportunity_id=opportunity.notice_id,
            qualified=all(rule.passed for rule in rules),
            days_until_due=days,
            rules=rules,
        )

    def evaluate_all(self, opportunities: list[Opportunity], *, now: datetime | None = None) -> list[QualificationResult]:
        return [self.evaluate(opportunity, now=now) for opportunity in opportunities]

    def _proposal_date(self, opportunity: Opportunity, now: datetime) -> tuple[RuleResult, int | None]:
        due = opportunity.proposal_due_date
        if due is None:
            return RuleResult(rule="proposal_date", passed=False, reason="Proposal deadline is missing."), None
        due_utc = due.replace(tzinfo=timezone.utc) if due.tzinfo is None else due.astimezone(timezone.utc)
        # Calendar-date arithmetic gives intuitive, stable inclusive boundaries.
        days = (due_utc.date() - now.date()).days
        minimum = self.profile.minimum_days_until_due
        maximum = self.profile.maximum_days_until_due
        passed = minimum <= days <= maximum
        if passed:
            reason = f"Proposal deadline is {days} days away, within the inclusive {minimum}-{maximum} day window."
        else:
            reason = f"Proposal deadline is {days} days away, outside the inclusive {minimum}-{maximum} day window."
        return RuleResult(rule="proposal_date", passed=passed, reason=reason), days

    def _naics(self, opportunity: Opportunity) -> RuleResult:
        codes = {_normalize(code) for code in opportunity.naics_codes if code.strip()}
        if not codes:
            return RuleResult(rule="naics", passed=False, reason="Opportunity NAICS code is missing.")
        targets = {_normalize(code) for code in self.profile.target_naics if code.strip()}
        matches = sorted(codes & targets)
        if matches:
            return RuleResult(rule="naics", passed=True, reason=f"Opportunity NAICS {matches[0]} matches a target NAICS.")
        return RuleResult(rule="naics", passed=False, reason="Opportunity NAICS does not match any configured target NAICS.")

    def _set_aside(self, opportunity: Opportunity) -> RuleResult:
        code = _normalize(opportunity.set_aside_code) if opportunity.set_aside_code else None
        description = _normalize(opportunity.set_aside_description) if opportunity.set_aside_description else None
        if not code and not description:
            if self.profile.allow_unrestricted:
                return RuleResult(rule="set_aside", passed=True, reason="No set-aside is specified; unrestricted opportunities are allowed by configuration.")
            return RuleResult(rule="set_aside", passed=False, reason="Opportunity set-aside is missing and unrestricted opportunities are not allowed.")
        for eligible in self.profile.eligible_set_asides:
            if code and code == _normalize(eligible.code):
                return RuleResult(rule="set_aside", passed=True, reason=f"Set-aside code {opportunity.set_aside_code} matches configured eligibility.")
            if not code and description and eligible.description and description == _normalize(eligible.description):
                return RuleResult(rule="set_aside", passed=True, reason="Set-aside description matches configured eligibility (no code was supplied).")
        return RuleResult(rule="set_aside", passed=False, reason="Opportunity set-aside does not match configured company eligibility.")

    def _organization(self, opportunity: Opportunity) -> RuleResult:
        target_departments = {_normalize(item) for item in self.profile.target_departments}
        target_agencies = {_normalize(item) for item in self.profile.target_agencies}
        checks: list[tuple[str, bool]] = []
        if target_departments:
            checks.append(("department", bool(opportunity.department and _normalize(opportunity.department) in target_departments)))
        if target_agencies:
            checks.append(("agency", bool(opportunity.agency and _normalize(opportunity.agency) in target_agencies)))
        if not checks:
            return RuleResult(rule="organization", passed=True, reason="No department or agency targets are configured; organization filtering is disabled.")
        failed = [name for name, passed in checks if not passed]
        if failed:
            return RuleResult(rule="organization", passed=False, reason=f"Opportunity {', '.join(failed)} does not match the configured target.")
        matched = " and ".join(name for name, _ in checks)
        return RuleResult(rule="organization", passed=True, reason=f"Opportunity {matched} matches the configured target.")
