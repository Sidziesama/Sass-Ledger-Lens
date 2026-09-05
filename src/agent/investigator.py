"""Deterministic investigation planner for material account variances."""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from time import perf_counter
from uuid import uuid4

from src.finance import AccountVariance, DriverContribution
from src.finance.decomposition import Dimension
from src.ingestion.models import BusinessContext
from src.memory import JsonMemoryStore
from src.observability import NullTraceObserver, TraceEvent, TraceObserver

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
    run_id: str
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
        observer: TraceObserver | None = None,
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
        self.observer = observer or NullTraceObserver()

    def investigate(
        self,
        prior_period: date,
        current_period: date,
        absolute_threshold: Decimal,
        percentage_threshold: Decimal,
    ) -> InvestigationResult:
        run_id = str(uuid4())
        self.observer.start_run(run_id)
        started = perf_counter()
        try:
            material = self.tools.rank_material_variances(
                prior_period, current_period, absolute_threshold, percentage_threshold
            )
            self.observer.record(
                TraceEvent(
                    step_type="tool_call",
                    label="Rank material account variances",
                    tool_name="rank_material_variances",
                    input_summary=f"{prior_period} to {current_period}",
                    output_summary=f"{sum(item.is_material for item in material)} material of {len(material)} accounts",
                    duration_ms=int((perf_counter() - started) * 1000),
                )
            )
            accounts = [
                self._investigate_account(item.result, prior_period, current_period)
                for item in material
                if item.is_material
            ]
            from src.evidence.lineage import build_claim_lineage

            for account in accounts:
                build_claim_lineage(account, self.tools.transactions, self.observer)
            result = InvestigationResult(run_id, prior_period, current_period, tuple(accounts))
            self.observer.record(
                TraceEvent(
                    step_type="final_answer",
                    label="Investigation completed",
                    output_summary=f"{len(accounts)} accounts investigated; {sum(a.stop_decision.should_stop for a in accounts)} evidence-sufficient",
                    duration_ms=int((perf_counter() - started) * 1000),
                )
            )
            self.observer.finish_run("success")
            return result
        except Exception as exc:
            self.observer.record(
                TraceEvent(
                    step_type="error",
                    label="Investigation failed",
                    output_summary=f"{type(exc).__name__}: {exc}",
                    duration_ms=int((perf_counter() - started) * 1000),
                    status="error",
                )
            )
            self.observer.finish_run("error")
            raise

    def _investigate_account(
        self, variance: AccountVariance, prior_period: date, current_period: date
    ) -> AccountInvestigation:
        best: tuple[str, list[DriverContribution], StopDecision] | None = None
        for dimension in self.dimensions:
            started = perf_counter()
            all_drivers = self.tools.breakdown_by_dimension(
                variance.account, prior_period, current_period, dimension
            )
            self.observer.record(
                TraceEvent(
                    step_type="tool_call",
                    label=f"Decompose {variance.account} by {dimension}",
                    tool_name="breakdown_by_dimension",
                    input_summary=f"account={variance.account}; dimension={dimension}",
                    output_summary=f"{len(all_drivers)} drivers",
                    duration_ms=int((perf_counter() - started) * 1000),
                )
            )
            if not all_drivers:
                continue
            if all(driver.driver == "Unspecified" for driver in all_drivers):
                self.observer.record(
                    TraceEvent(
                        step_type="reasoning",
                        label="Skip uninformative dimension",
                        input_summary=f"dimension={dimension}",
                        output_summary="all transactions are Unspecified",
                    )
                )
                continue

            selected: list[DriverContribution] = []
            decision = evaluate_stopping_rule(selected, all_drivers, self.target_coverage)
            for driver in all_drivers[: self.max_drivers]:
                selected.append(driver)
                decision = evaluate_stopping_rule(selected, all_drivers, self.target_coverage)
                if decision.should_stop:
                    break

            self.observer.record(
                TraceEvent(
                    step_type="reasoning",
                    label="Evaluate stopping criterion",
                    input_summary=f"dimension={dimension}; target={self.target_coverage}",
                    output_summary=f"coverage={decision.coverage}; evidence={decision.evidence_sufficient}; decision={decision.reason}",
                )
            )

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
        started = perf_counter()
        context = tuple(self.memory.get_business_context(subject=account, as_of=current_period))
        self.observer.record(
            TraceEvent(
                step_type="tool_call",
                label=f"Retrieve context for {account}",
                tool_name="get_business_context",
                input_summary=f"subject={account}; as_of={current_period}",
                output_summary=f"{len(context)} context records",
                duration_ms=int((perf_counter() - started) * 1000),
            )
        )
        return context
