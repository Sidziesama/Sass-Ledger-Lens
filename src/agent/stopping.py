"""Explicit, testable stopping rules for financial investigations."""

from dataclasses import dataclass
from decimal import Decimal

from src.finance import DriverContribution


@dataclass(frozen=True)
class StopDecision:
    should_stop: bool
    coverage: Decimal
    evidence_sufficient: bool
    reason: str


def explanatory_coverage(
    selected: list[DriverContribution], all_drivers: list[DriverContribution]
) -> Decimal:
    denominator = sum((abs(row.variance) for row in all_drivers), Decimal("0"))
    if denominator == 0:
        return Decimal("1")
    numerator = sum((abs(row.variance) for row in selected), Decimal("0"))
    return min(numerator / denominator, Decimal("1"))


def evaluate_stopping_rule(
    selected: list[DriverContribution],
    all_drivers: list[DriverContribution],
    target_coverage: Decimal,
) -> StopDecision:
    coverage = explanatory_coverage(selected, all_drivers)
    evidence_sufficient = bool(selected) and all(row.transaction_ids for row in selected)
    should_stop = coverage >= target_coverage and evidence_sufficient
    if should_stop:
        reason = "coverage_target_met_with_transaction_evidence"
    elif not evidence_sufficient:
        reason = "transaction_evidence_insufficient"
    else:
        reason = "coverage_below_target"
    return StopDecision(should_stop, coverage, evidence_sufficient, reason)
