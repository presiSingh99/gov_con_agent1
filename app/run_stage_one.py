import argparse
import asyncio
import json
import logging
import os
from datetime import date
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from app.config import load_company_profile
from app.models.opportunity import Opportunity
from app.models.qualification import QualificationResult
from app.qualification.engine import QualificationEngine
from app.sources.sam_gov import SAMGovError, SAMGovOpportunitySource

LOGGER = logging.getLogger(__name__)


def _parse_date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("date must use YYYY-MM-DD") from exc


def _record(opportunity: Opportunity, result: QualificationResult) -> dict[str, Any]:
    item: dict[str, Any] = {
        "opportunity": opportunity.model_dump(mode="json"),
        "qualification_result": result.model_dump(mode="json"),
    }
    if not result.qualified:
        item["rejection_reasons"] = [rule.reason for rule in result.rules if not rule.passed]
    return item


def save_results(
    opportunities: list[Opportunity],
    results: list[QualificationResult],
    output_dir: Path,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    output_dir.mkdir(parents=True, exist_ok=True)
    combined = [_record(opportunity, result) for opportunity, result in zip(opportunities, results, strict=True)]
    qualified = [item for item in combined if item["qualification_result"]["qualified"]]
    rejected = [item for item in combined if not item["qualification_result"]["qualified"]]
    for name, records in (("qualified_opportunities.json", qualified), ("rejected_opportunities.json", rejected)):
        (output_dir / name).write_text(json.dumps(records, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return qualified, rejected


def print_report(
    source: SAMGovOpportunitySource,
    opportunities: list[Opportunity],
    results: list[QualificationResult],
) -> None:
    qualified = [(item, result) for item, result in zip(opportunities, results, strict=True) if result.qualified]
    print("\nSAM.gov Stage 1 Qualification\n")
    print(f"Opportunities retrieved: {source.retrieved_count}")
    print(f"Successfully normalized: {len(opportunities)}")
    print(f"Malformed/skipped: {source.skipped_count}\n")
    print(f"Qualified: {len(qualified)}")
    print(f"Rejected: {len(results) - len(qualified)}\n")
    print("QUALIFIED OPPORTUNITIES")
    print("-" * 50)
    if not qualified:
        print("None")
        return
    for opportunity, result in qualified:
        print(f"\n{opportunity.title}\n")
        print(f"Notice ID: {opportunity.notice_id}")
        print(f"Agency: {opportunity.agency or 'Not provided'}")
        print(f"Department: {opportunity.department or 'Not provided'}")
        print(f"NAICS: {', '.join(opportunity.naics_codes) or 'Not provided'}")
        print(f"Set Aside: {opportunity.set_aside_description or opportunity.set_aside_code or 'Unrestricted/not provided'}")
        print(f"Proposal Due: {opportunity.proposal_due_date.isoformat() if opportunity.proposal_due_date else 'Not provided'}")
        print(f"Days Remaining: {result.days_until_due}")
        print("\n" + "-" * 50)


async def run_stage_one(
    *,
    profile_path: Path = Path("config/company_profile.yaml"),
    output_dir: Path = Path("output/stage1"),
    posted_from: date | None = None,
    posted_to: date | None = None,
) -> tuple[list[Opportunity], list[QualificationResult]]:
    load_dotenv()
    api_key = os.getenv("SAM_API_KEY", "")
    if not api_key.strip():
        raise ValueError("SAM_API_KEY is missing; copy .env.example to .env and add your key")
    profile = load_company_profile(profile_path)
    source = SAMGovOpportunitySource(api_key, posted_from=posted_from, posted_to=posted_to)
    LOGGER.info("Starting SAM.gov Stage 1 scan")
    LOGGER.info("Fetching opportunities from SAM.gov")
    opportunities = await source.list_opportunities()
    LOGGER.info("Retrieved %d opportunity records", source.retrieved_count)
    LOGGER.info("Successfully normalized %d records", len(opportunities))
    if source.skipped_count:
        LOGGER.warning("Skipped %d malformed records", source.skipped_count)
    LOGGER.info("Running business qualification")
    results = QualificationEngine(profile).evaluate_all(opportunities)
    qualified, rejected = save_results(opportunities, results, output_dir)
    LOGGER.info("Qualified %d opportunities", len(qualified))
    LOGGER.info("Rejected %d opportunities", len(rejected))
    LOGGER.info("Results saved to %s", output_dir)
    print_report(source, opportunities, results)
    return opportunities, results


def main() -> int:
    parser = argparse.ArgumentParser(description="Run deterministic Stage 1 SAM.gov qualification")
    parser.add_argument("--profile", type=Path, default=Path("config/company_profile.yaml"))
    parser.add_argument("--output-dir", type=Path, default=Path("output/stage1"))
    parser.add_argument("--posted-from", type=_parse_date, help="SAM.gov posted start date (YYYY-MM-DD)")
    parser.add_argument("--posted-to", type=_parse_date, help="SAM.gov posted end date (YYYY-MM-DD)")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    try:
        asyncio.run(
            run_stage_one(
                profile_path=args.profile,
                output_dir=args.output_dir,
                posted_from=args.posted_from,
                posted_to=args.posted_to,
            )
        )
    except (ValueError, SAMGovError) as exc:
        LOGGER.error("Stage 1 failed: %s", exc)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
