"""Command-line entry point for deterministic Ledger Lens investigations."""

import argparse
import json
from datetime import date
from decimal import Decimal
from pathlib import Path

from src.explanation import (
    OpenAICompatibleProvider,
)
from src.ingestion.loaders import load_account_summaries, load_transactions
from src.memory import JsonMemoryStore
from src.observability import InMemoryTraceObserver, PrismTraceObserver
from src.settings import load_settings
from src.workflow import build_artifact, run_workflow  # noqa: F401

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


def print_report(artifact: dict) -> None:
    print(f"Ledger Lens investigation: {artifact['prior_period']} -> {artifact['current_period']}")
    for issue in artifact.get("data_quality_issues", []):
        print(f"Needs review: {issue}")
    if not artifact["accounts"]:
        print(
            "Investigation requires data review."
            if artifact.get("data_quality_issues")
            else "No material variances found."
        )
        return
    for account in artifact["accounts"]:
        percent = (
            f"{Decimal(account['variance_pct']):.2f}"
            if account["variance_pct"] is not None
            else "n/a"
        )
        status = account["status"]
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
        for issue in account.get("reliability_issues", []):
            print(f"  needs review: {issue}")
        if account.get("explanation_warning"):
            print(f"  explanation warning: {account['explanation_warning']}")
        if account["explanation"]:
            print(f"  explanation: {account['explanation']['summary']}")


def run(args: argparse.Namespace) -> dict:
    load_settings()
    summaries = load_account_summaries(args.summaries)
    transactions = load_transactions(args.transactions)
    memory = JsonMemoryStore(args.memory)
    observer = PrismTraceObserver.from_env(required=True) if args.prism else InMemoryTraceObserver()
    provider = None
    if args.llm:
        provider = OpenAICompatibleProvider.from_env()
        if provider is None:
            raise RuntimeError(
                "--llm requires LEDGER_LENS_LLM_BASE_URL, LEDGER_LENS_LLM_API_KEY, "
                "and LEDGER_LENS_LLM_MODEL"
            )
    execution = run_workflow(
        summaries,
        transactions,
        args.prior,
        args.current,
        args.absolute_threshold,
        args.percentage_threshold,
        provider=provider,
        observer=observer,
        memory=memory,
        target_coverage=args.coverage,
        max_drivers=args.max_drivers,
    )
    artifact = execution.artifact
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
    print(f"PRISM delivery: {artifact['telemetry']['status']}")
    if args.output:
        print(f"\nJSON artifact: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
