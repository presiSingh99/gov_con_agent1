from datetime import datetime, timedelta, timezone

import pytest

from app.config import CompanyProfile
from app.models.opportunity import Opportunity
from app.qualification.engine import QualificationEngine

NOW = datetime(2026, 1, 1, 12, tzinfo=timezone.utc)


def profile(**changes) -> CompanyProfile:
    values = {
        "company_name": "Test Co",
        "minimum_days_until_due": 14,
        "maximum_days_until_due": 365,
        "target_naics": ["541512", "541519"],
        "eligible_set_asides": [{"code": "SBA", "description": "Total Small Business Set-Aside"}],
        "allow_unrestricted": False,
        "target_departments": ["Department of Health"],
        "target_agencies": [],
    }
    values.update(changes)
    return CompanyProfile.model_validate(values)


def opportunity(**changes) -> Opportunity:
    values = {
        "notice_id": "N1",
        "title": "Test Opportunity",
        "proposal_due_date": NOW + timedelta(days=30),
        "naics_codes": ["541512"],
        "set_aside_code": "SBA",
        "department": "Department of Health",
    }
    values.update(changes)
    return Opportunity.model_validate(values)


def rule(result, name):
    return next(item for item in result.rules if item.rule == name)


@pytest.mark.parametrize(("days", "passed"), [(14, True), (365, True), (13, False), (366, False)])
def test_proposal_date_boundaries(days, passed):
    result = QualificationEngine(profile()).evaluate(opportunity(proposal_due_date=NOW + timedelta(days=days)), now=NOW)
    assert rule(result, "proposal_date").passed is passed
    assert result.days_until_due == days


def test_missing_due_date_fails():
    result = QualificationEngine(profile()).evaluate(opportunity(proposal_due_date=None), now=NOW)
    assert not rule(result, "proposal_date").passed
    assert "missing" in rule(result, "proposal_date").reason.lower()


@pytest.mark.parametrize(
    ("codes", "passed"),
    [([" 541512 "], True), (["999999"], False), (["999999", "541519"], True), ([], False)],
)
def test_naics(codes, passed):
    result = QualificationEngine(profile()).evaluate(opportunity(naics_codes=codes), now=NOW)
    assert rule(result, "naics").passed is passed


def test_matching_and_nonmatching_set_aside():
    engine = QualificationEngine(profile())
    assert rule(engine.evaluate(opportunity(set_aside_code="sba"), now=NOW), "set_aside").passed
    assert not rule(engine.evaluate(opportunity(set_aside_code="8A"), now=NOW), "set_aside").passed


@pytest.mark.parametrize(("allow", "passed"), [(False, False), (True, True)])
def test_missing_set_aside_is_configurable(allow, passed):
    result = QualificationEngine(profile(allow_unrestricted=allow)).evaluate(
        opportunity(set_aside_code=None, set_aside_description=None), now=NOW
    )
    assert rule(result, "set_aside").passed is passed


def test_organization_department_matching_normalizes_text():
    engine = QualificationEngine(profile(target_departments=[" department   OF HEALTH "]))
    assert rule(engine.evaluate(opportunity(department="Department of Health"), now=NOW), "organization").passed
    assert not rule(engine.evaluate(opportunity(department="Department of Energy"), now=NOW), "organization").passed


def test_organization_agency_matching_when_configured():
    engine = QualificationEngine(profile(target_departments=[], target_agencies=["Health Agency"]))
    result = engine.evaluate(opportunity(department=None, agency=" health   agency "), now=NOW)
    assert rule(result, "organization").passed


@pytest.mark.parametrize(
    ("departments", "agencies", "opportunity_changes"),
    [([], ["Health Agency"], {"agency": "Health Agency", "department": None}), (["Department of Health"], [], {"agency": None})],
)
def test_empty_organization_dimension_does_not_reject(departments, agencies, opportunity_changes):
    engine = QualificationEngine(profile(target_departments=departments, target_agencies=agencies))
    assert rule(engine.evaluate(opportunity(**opportunity_changes), now=NOW), "organization").passed


def test_all_required_rules_must_pass():
    result = QualificationEngine(profile()).evaluate(opportunity(naics_codes=[]), now=NOW)
    assert not result.qualified
