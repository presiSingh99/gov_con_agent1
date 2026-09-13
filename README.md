# GovCon Capture — Stage 1

This repository is a lean, deterministic opportunity-qualification pipeline:

```text
SAM.gov Get Opportunities Public API -> normalize -> company rules -> JSON results
```

It retrieves recently published notices from the official Get Opportunities v2 endpoint, maps documented SAM.gov fields to a source-independent `Opportunity`, and checks proposal timing, NAICS, set-aside eligibility, and organization targets. It makes no LLM calls. Document retrieval, fit scoring, past-performance analysis, capture briefs, and every other Stage 2/3 feature are intentionally **not implemented**.

## Setup

Python 3.11 or newer is required.

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
cp .env.example .env
```

Get a public API key through SAM.gov and put only this value in `.env`:

```dotenv
SAM_API_KEY=your_actual_sam_gov_public_api_key
```

`.env` is ignored by Git. The application never prints or logs the key.

## Configure your company

Edit `config/company_profile.yaml` before the first real run. Its checked-in entries are examples, **not assumed company attributes**. Replace:

- `company_name` with the company's name;
- `minimum_days_until_due` and `maximum_days_until_due` with the inclusive date window;
- `target_naics` with the company's actual six-digit NAICS codes, quoted as strings;
- `eligible_set_asides` with exact SAM.gov `typeOfSetAside` codes for which the company is eligible (descriptions are useful labels and a fallback only if a notice supplies no code);
- `allow_unrestricted` with `true` if notices with neither a set-aside code nor description should pass, or `false` to reject them;
- `target_departments` with exact desired top-level organization names;
- `target_agencies` with exact desired second-level organization names.

Empty department or agency target lists disable only that dimension. If both lists are empty, organization filtering passes. If one is configured, it must match. If both are configured, **both** must match. Comparisons ignore case, surrounding whitespace, and repeated whitespace; they are otherwise exact.

All four rules are required. The proposal-day calculation compares UTC calendar dates and includes both configured boundaries. NAICS and stable set-aside codes are exact after whitespace/case normalization. A missing deadline or NAICS always fails. A missing set-aside follows `allow_unrestricted`.

## Run Stage 1

From the repository root:

```bash
python -m app.run_stage_one
```

By default, the source requests notices posted from yesterday through today. To select a different documented SAM.gov posted-date range:

```bash
python -m app.run_stage_one --posted-from 2026-09-01 --posted-to 2026-09-12
```

The terminal report summarizes retrieval and displays qualified notices only. Pretty-printed results are written to:

- `output/stage1/qualified_opportunities.json`
- `output/stage1/rejected_opportunities.json`

Each JSON item includes the normalized opportunity and its structured rule results. Rejected items also have an explicit `rejection_reasons` list.

## Tests

Tests use `httpx.MockTransport`; they never contact SAM.gov.

```bash
pytest
```

## SAM.gov assumptions and error behavior

The adapter uses the official `https://api.sam.gov/opportunities/v2/search` endpoint and documented query parameters `api_key`, `postedFrom`, `postedTo`, `limit`, and `offset`. It consumes `totalRecords` and `opportunitiesData`. Field mapping uses `noticeId`, `title`, `solicitationNumber`, `fullParentPathName`, `postedDate`, `responseDeadLine`, `naicsCode`, `typeOfSetAside`, `typeOfSetAsideDescription`, `type`, `description`, `uiLink`, and `resourceLinks`.

SAM.gov represents the organization hierarchy in `fullParentPathName` as period-separated levels. Stage 1 treats the first level as department, the second as agency, and the last level (when there are at least three) as office. The documented response has one `naicsCode`; the internal model uses a list so another source can provide multiple codes later. No unofficial set-aside mapping is embedded in Python.

Pagination continues until `totalRecords` is reached, a short page is returned, or a page is empty. A malformed individual opportunity is logged and skipped. Timeout, network, authorization, rate-limit, non-success HTTP, malformed JSON, and invalid response-shape errors stop the scan with a concise message. Partial pages are not written after such a failure, avoiding misleading incomplete output. See the [official GSA Get Opportunities Public API documentation](https://open.gsa.gov/api/get-opportunities-public-api/) for API access and field details.
