"""Deterministic investigation planner for material account variances."""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from src.finance import AccountVariance, DriverContribution
from src.finance.decomposition import Dimension
from src.ingestion.models import BusinessContext
from src.memory import JsonMemoryStore

from .stopping import StopDecision, evaluate_stopping_rule
from .tools import FinancialTools


@dataclass(frozen=True)
class AccountInvestigation:
    variance: AccountVariance
    prior_period: date
    current_period: date
    dimension: str
    drivers: tuple[DriverContribution, ...]
    stop_decision: StopDecision
    business_context: tuple[BusinessContext, ...] = ()


@dataclass(frozen=True)
class InvestigationResult:
    prior_period: date
    current_period: date
    accounts: tuple[AccountInvestigation, ...]


class Investigator:
    """Investigates material accounts until coverage and evidence are sufficient."""

    def __init__(
        self,
        tools: FinancialTools,
        dimensions: tuple[Dimension, ...] = ("customer", "vendor", "segment", "category"),
        target_coverage: Decimal = Decimal("0.80"),
        max_drivers: int = 5,
        memory: JsonMemoryStore | None = None,
    ):
        if not Decimal("0") <= target_coverage <= Decimal("1"):
            raise ValueError("target_coverage must be between 0 and 1")
        if max_drivers < 1:
            raise ValueError("max_drivers must be at least 1")
        self.tools = tools
        self.dimensions = dimensions
        self.target_coverage = target_coverage
        self.max_drivers = max_drivers
        self.memory = memory

    def investigate(
        self,
        prior_period: date,
        current_period: date,
        absolute_threshold: Decimal,
        percentage_threshold: Decimal,
    ) -> InvestigationResult:
        material = self.tools.rank_material_variances(
            prior_period, current_period, absolute_threshold, percentage_threshold
        )
        accounts = [
            self._investigate_account(item.result, prior_period, current_period)
            for item in material
            if item.is_material
        ]
        return InvestigationResult(prior_period, current_period, tuple(accounts))

    def _investigate_account(
        self, variance: AccountVariance, prior_period: date, current_period: date
    ) -> AccountInvestigation:
        best: tuple[str, list[DriverContribution], StopDecision] | None = None
        for dimension in self.dimensions:
            all_drivers = self.tools.breakdown_by_dimension(
                variance.account, prior_period, current_period, dimension
            )
            if not all_drivers:
                continue

            selected: list[DriverContribution] = []
            decision = evaluate_stopping_rule(selected, all_drivers, self.target_coverage)
            for driver in all_drivers[: self.max_drivers]:
                selected.append(driver)
                decision = evaluate_stopping_rule(selected, all_drivers, self.target_coverage)
                if decision.should_stop:
                    break

            candidate = (dimension, selected, decision)
            if best is None or decision.coverage > best[2].coverage:
                best = candidate
            if decision.should_stop:
                break

        if best is None:
            decision = StopDecision(False, Decimal("0"), False, "no_transaction_drivers")
            return AccountInvestigation(
                variance,
                prior_period,
                current_period,
                "none",
                (),
                decision,
                self._context_for(variance.account, current_period),
            )
        dimension, drivers, decision = best
        return AccountInvestigation(
            variance,
            prior_period,
            current_period,
            dimension,
            tuple(drivers),
            decision,
            self._context_for(variance.account, current_period),
        )

    def _context_for(self, account: str, current_period: date) -> tuple[BusinessContext, ...]:
        if self.memory is None:
            return ()
        return tuple(self.memory.get_business_context(subject=account, as_of=current_period))
