import asyncio
from datetime import date

import httpx
import pytest

from app.sources.sam_gov import SAMGovError, SAMGovOpportunitySource, map_sam_opportunity


def sam_record(notice_id="N1"):
    return {
        "noticeId": notice_id,
        "title": "Cloud services",
        "solicitationNumber": "SOL-1",
        "fullParentPathName": "DEPARTMENT OF TEST.TEST AGENCY.TEST OFFICE",
        "postedDate": "2026-01-01",
        "responseDeadLine": "2026-02-01T17:00:00-05:00",
        "naicsCode": "541512",
        "typeOfSetAside": "SBA",
        "typeOfSetAsideDescription": "Total Small Business Set-Aside",
        "type": "Solicitation",
        "uiLink": "https://sam.gov/opp/N1/view",
        "resourceLinks": ["https://example.invalid/resource"],
    }


def source(handler, page_size=100):
    transport = httpx.MockTransport(handler)
    client = httpx.AsyncClient(transport=transport)
    return SAMGovOpportunitySource(
        "not-a-real-key", posted_from=date(2026, 1, 1), posted_to=date(2026, 1, 2), page_size=page_size, client=client
    ), client


def test_successful_response_maps_documented_fields():
    def handler(request):
        assert request.url.params["postedFrom"] == "01/01/2026"
        assert request.url.params["postedTo"] == "01/02/2026"
        return httpx.Response(200, json={"totalRecords": 1, "opportunitiesData": [sam_record()]})

    adapter, client = source(handler)
    try:
        items = asyncio.run(adapter.list_opportunities())
    finally:
        asyncio.run(client.aclose())
    assert len(items) == 1
    assert items[0].notice_id == "N1"
    assert items[0].department == "DEPARTMENT OF TEST"
    assert items[0].agency == "TEST AGENCY"
    assert items[0].office == "TEST OFFICE"


def test_pagination():
    offsets = []

    def handler(request):
        offset = int(request.url.params["offset"])
        offsets.append(offset)
        records = [sam_record(f"N{offset + 1}")] if offset < 2 else []
        return httpx.Response(200, json={"totalRecords": 2, "opportunitiesData": records})

    adapter, client = source(handler, page_size=1)
    try:
        items = asyncio.run(adapter.list_opportunities())
    finally:
        asyncio.run(client.aclose())
    assert [item.notice_id for item in items] == ["N1", "N2"]
    assert offsets == [0, 1]


def test_empty_response():
    adapter, client = source(lambda request: httpx.Response(200, json={"totalRecords": 0, "opportunitiesData": []}))
    try:
        assert asyncio.run(adapter.list_opportunities()) == []
    finally:
        asyncio.run(client.aclose())


def test_malformed_record_is_skipped():
    adapter, client = source(
        lambda request: httpx.Response(200, json={"totalRecords": 2, "opportunitiesData": [{"title": "No ID"}, sam_record()]})
    )
    try:
        items = asyncio.run(adapter.list_opportunities())
    finally:
        asyncio.run(client.aclose())
    assert len(items) == 1
    assert adapter.skipped_count == 1


@pytest.mark.parametrize("status", [500, 503])
def test_http_error(status):
    adapter, client = source(lambda request: httpx.Response(status))
    try:
        with pytest.raises(SAMGovError, match=f"HTTP {status}"):
            asyncio.run(adapter.list_opportunities())
    finally:
        asyncio.run(client.aclose())


def test_timeout():
    def handler(request):
        raise httpx.ReadTimeout("timed out", request=request)

    adapter, client = source(handler)
    try:
        with pytest.raises(SAMGovError, match="timed out"):
            asyncio.run(adapter.list_opportunities())
    finally:
        asyncio.run(client.aclose())


def test_rate_limit_response():
    adapter, client = source(lambda request: httpx.Response(429, headers={"Retry-After": "60"}))
    try:
        with pytest.raises(SAMGovError, match="rate limit") as error:
            asyncio.run(adapter.list_opportunities())
    finally:
        asyncio.run(client.aclose())
    assert "60" in str(error.value)


def test_mapper_requires_notice_id_and_title():
    with pytest.raises(ValueError, match="noticeId or title"):
        map_sam_opportunity({"noticeId": "N1"})
