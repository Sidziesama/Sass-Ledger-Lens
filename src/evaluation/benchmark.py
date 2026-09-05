"""Run deterministic accuracy and evidence checks against known outcomes."""

import argparse
import json
from decimal import Decimal
from pathlib import Path

from pydantic import TypeAdapter

from src.agent import FinancialTools, Investigator
from src.evidence import build_claim_lineage
from src.ingestion.loaders import load_account_summaries, load_transactions

from .models import BenchmarkCase, BenchmarkScore, CaseScore

ROOT = Path(__file__).parents[2]
BENCHMARK = ROOT / "data" / "benchmark"


def load_cases(path: str | Path) -> list[BenchmarkCase]:
    with Path(path).open(encoding="utf-8") as handle:
        return TypeAdapter(list[BenchmarkCase]).validate_python(json.load(handle))


def _rate(results: list[bool]) -> Decimal:
    return sum(results, 0) / Decimal(len(results)) if results else Decimal("0")


def evaluate_case(case: BenchmarkCase, tools: FinancialTools) -> CaseScore:
    result = Investigator(tools).investigate(
        case.prior_period,
        case.current_period,
        case.absolute_threshold,
        case.percentage_threshold,
    )
    actual = {account.variance.account: account for account in result.accounts}
    variance_checks = []
    driver_checks = []
    reconciliation_checks = []
    evidence_checks = []

    for expected in case.expected_accounts:
        account = actual.get(expected.account)
        variance_checks.append(account is not None and account.variance.variance == expected.variance)
        driver_checks.append(
            account is not None
            and account.dimension == expected.top_driver_dimension
            and bool(account.drivers)
            and account.drivers[0].driver == expected.top_driver
        )
        if account is None:
            reconciliation_checks.append(False)
            evidence_checks.append(False)
            continue
        all_drivers = tools.breakdown_by_dimension(
            account.variance.account,
            case.prior_period,
            case.current_period,
            account.dimension,
        )
        reconciliation_checks.append(
            sum((driver.variance for driver in all_drivers), Decimal("0"))
            == account.variance.variance
        )
        claims = build_claim_lineage(account, tools.transactions)
        evidence_checks.append(
            account.stop_decision.evidence_sufficient
            and bool(claims)
            and all(claim.transactions for claim in claims)
        )

    score = CaseScore(
        case_id=case.case_id,
        variance_accuracy=_rate(variance_checks),
        driver_accuracy=_rate(driver_checks),
        reconciliation_rate=_rate(reconciliation_checks),
        evidence_completeness=_rate(evidence_checks),
        passed=False,
    )
    return score.model_copy(
        update={
            "passed": all(
                metric == Decimal("1")
                for metric in (
                    score.variance_accuracy,
                    score.driver_accuracy,
                    score.reconciliation_rate,
                    score.evidence_completeness,
                )
            )
        }
    )


def run_benchmark(
    summaries_path: str | Path = BENCHMARK / "monthly_summary.json",
    transactions_path: str | Path = BENCHMARK / "transactions.json",
    cases_path: str | Path = BENCHMARK / "cases.json",
) -> BenchmarkScore:
    tools = FinancialTools(
        load_account_summaries(summaries_path), load_transactions(transactions_path)
    )
    scores = [evaluate_case(case, tools) for case in load_cases(cases_path)]
    result = BenchmarkScore(
        cases=scores,
        variance_accuracy=sum((score.variance_accuracy for score in scores), Decimal("0")) / len(scores),
        driver_accuracy=sum((score.driver_accuracy for score in scores), Decimal("0")) / len(scores),
        reconciliation_rate=sum((score.reconciliation_rate for score in scores), Decimal("0")) / len(scores),
        evidence_completeness=sum((score.evidence_completeness for score in scores), Decimal("0")) / len(scores),
        passed=all(score.passed for score in scores),
    )
    return result


def main(argv: list[str] | None = None) -> int:
    command = argparse.ArgumentParser(description="Run the Ledger Lens deterministic benchmark.")
    command.add_argument("--output", type=Path)
    args = command.parse_args(argv)
    score = run_benchmark()
    serialized = score.model_dump_json(indent=2)
    print(serialized)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(serialized + "\n", encoding="utf-8")
    return 0 if score.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
