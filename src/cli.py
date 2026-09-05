"""Command-line entry point for deterministic Ledger Lens investigations."""

import argparse
import json
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

from src.agent import FinancialTools, Investigator
from src.evidence import build_claim_lineage
from src.explanation import (
    EvidenceBoundExplainer,
    OpenAICompatibleProvider,
    TemplateExplanationProvider,
)
from src.ingestion.loaders import load_account_summaries, load_transactions
from src.memory import JsonMemoryStore
from src.observability import InMemoryTraceObserver, PrismTraceObserver

ROOT = Path(__file__).parents[1]


def parser() -> argparse.ArgumentParser:
    command = argparse.ArgumentParser(
        prog="ledger-lens", description="Investigate financial variances with transaction evidence."
    )
    command.add_argument(
        "--summaries", type=Path, default=ROOT / "data/sample/monthly_summary.json"
    )
    command.add_argument(
        "--transactions", type=Path, default=ROOT / "data/sample/transactions.json"
    )
    command.add_argument("--memory", type=Path, default=ROOT / "data/memory")
    command.add_argument("--prior", type=date.fromisoformat, required=True, metavar="YYYY-MM-DD")
    command.add_argument("--current", type=date.fromisoformat, required=True, metavar="YYYY-MM-DD")
    command.add_argument("--absolute-threshold", type=Decimal, default=Decimal("50000"))
    command.add_argument("--percentage-threshold", type=Decimal, default=Decimal("10"))
    command.add_argument("--coverage", type=Decimal, default=Decimal("0.80"))
    command.add_argument("--max-drivers", type=int, default=5)
    command.add_argument(
        "--output", type=Path, help="Write the complete investigation artifact as JSON."
    )
    command.add_argument(
        "--prism", action="store_true", help="Submit the trajectory using PRISMTRACE_* settings."
    )
    command.add_argument(
        "--llm",
        action="store_true",
        help="Use the configured OpenAI-compatible provider instead of the offline template.",
    )
    return command


def build_artifact(result, transactions, events, provider=None) -> dict[str, Any]:
    explanation_provider = provider or TemplateExplanationProvider()
    accounts = []
    for account in result.accounts:
        claims = build_claim_lineage(account, transactions)
        explanation = (
            EvidenceBoundExplainer(explanation_provider).explain(account, claims)
            if claims
            else None
        )
        accounts.append(
            {
                "account": account.variance.account,
                "prior_amount": str(account.variance.prior_amount),
                "current_amount": str(account.variance.current_amount),
                "variance": str(account.variance.variance),
                "variance_pct": (
                    str(account.variance.variance_pct)
                    if account.variance.variance_pct is not None
                    else None
                ),
                "investigated_dimension": account.dimension,
                "coverage": str(account.stop_decision.coverage),
                "evidence_sufficient": account.stop_decision.evidence_sufficient,
                "stop_reason": account.stop_decision.reason,
                "drivers": [
                    {
                        "driver": driver.driver,
                        "variance": str(driver.variance),
                        "contribution_pct": (
                            str(driver.contribution_pct)
                            if driver.contribution_pct is not None
                            else None
                        ),
                        "transaction_ids": list(driver.transaction_ids),
                    }
                    for driver in account.drivers
                ],
                "claims": [claim.model_dump(mode="json") for claim in claims],
                "explanation": explanation.model_dump(mode="json") if explanation else None,
                "business_context": [
                    context.model_dump(mode="json") for context in account.business_context
                ],
            }
        )
    return {
        "run_id": result.run_id,
        "prior_period": result.prior_period.isoformat(),
        "current_period": result.current_period.isoformat(),
        "accounts": accounts,
        "trace": [event.as_prism_step() for event in events],
    }


def print_report(artifact: dict[str, Any]) -> None:
    print(f"Ledger Lens investigation: {artifact['prior_period']} -> {artifact['current_period']}")
    if not artifact["accounts"]:
        print("No material variances found.")
        return
    for account in artifact["accounts"]:
        percent = account["variance_pct"] or "n/a"
        status = "evidence sufficient" if account["evidence_sufficient"] else "needs review"
        print(f"\n{account['account']}")
        print(
            f"  prior={account['prior_amount']} current={account['current_amount']} "
            f"variance={Decimal(account['variance']):+} ({percent}%)"
        )
        print(
            f"  dimension={account['investigated_dimension']} "
            f"coverage={Decimal(account['coverage']) * 100:.1f}% status={status}"
        )
        for driver in account["drivers"]:
            print(
                f"  - {driver['driver']}: {Decimal(driver['variance']):+} "
                f"({len(driver['transaction_ids'])} transactions)"
            )
        if account["explanation"]:
            print(f"  explanation: {account['explanation']['summary']}")


def run(args: argparse.Namespace) -> dict[str, Any]:
    summaries = load_account_summaries(args.summaries)
    transactions = load_transactions(args.transactions)
    memory = JsonMemoryStore(args.memory)
    local_trace = InMemoryTraceObserver()
    observer = PrismTraceObserver.from_env() if args.prism else local_trace
    investigator = Investigator(
        FinancialTools(summaries, transactions),
        target_coverage=args.coverage,
        max_drivers=args.max_drivers,
        memory=memory,
        observer=observer,
    )
    result = investigator.investigate(
        args.prior,
        args.current,
        args.absolute_threshold,
        args.percentage_threshold,
    )
    events = getattr(observer, "events", local_trace.events)
    provider = None
    if args.llm:
        provider = OpenAICompatibleProvider.from_env()
        if provider is None:
            raise RuntimeError(
                "--llm requires LEDGER_LENS_LLM_BASE_URL, LEDGER_LENS_LLM_API_KEY, "
                "and LEDGER_LENS_LLM_MODEL"
            )
    artifact = build_artifact(result, transactions, events, provider)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(artifact, indent=2) + "\n", encoding="utf-8")
    return artifact


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    if args.current <= args.prior:
        parser().error("--current must be after --prior")
    artifact = run(args)
    print_report(artifact)
    if args.output:
        print(f"\nJSON artifact: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
