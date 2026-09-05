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
from src.quality import QualityFlag, run_quality_gate

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
    reliability_notes: tuple[str, ...] = ()
    quality_flags: tuple[QualityFlag, ...] = ()


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
            quality = run_quality_gate(
                self.tools.summaries, self.tools.transactions, prior_period, current_period
            )
            self.observer.record(
                TraceEvent(
                    step_type="tool_call",
                    label="Run data-quality gate",
                    tool_name="run_quality_gate",
                    output_summary=f"{len(quality.flags)} findings; {sum(f.severity == 'blocker' for f in quality.flags)} blockers",
                )
            )
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
                self._investigate_account(item.result, prior_period, current_period, quality.flags)
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
        self,
        variance: AccountVariance,
        prior_period: date,
        current_period: date,
        quality_flags: list[QualityFlag],
    ) -> AccountInvestigation:
        account_flags = tuple(
            flag for flag in quality_flags if flag.account in {None, variance.account}
        )
        blockers = tuple(flag for flag in account_flags if flag.severity == "blocker")
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
                self._reliability_notes(variance, (), "none", prior_period, current_period),
                account_flags,
            )
        dimension, drivers, decision = best
        if blockers:
            decision = StopDecision(False, decision.coverage, False, "data_quality_blocker")
        return AccountInvestigation(
            variance,
            prior_period,
            current_period,
            dimension,
            tuple(drivers),
            decision,
            self._context_for(variance.account, current_period),
            self._reliability_notes(
                variance, tuple(drivers), dimension, prior_period, current_period
            ),
            account_flags,
        )

    def _reliability_notes(
        self,
        variance: AccountVariance,
        drivers: tuple[DriverContribution, ...],
        dimension: str,
        prior_period: date,
        current_period: date,
    ) -> tuple[str, ...]:
        notes: list[str] = []
        if variance.prior_amount == 0:
            notes.append("percentage change is not meaningful because the prior base is zero")

        total_abs = sum((abs(item.variance) for item in drivers), Decimal("0"))
        if drivers and total_abs:
            lead_share = abs(drivers[0].variance) / total_abs
            if lead_share >= Decimal("0.60"):
                notes.append(
                    f"the movement is concentrated in {drivers[0].driver}; it is not broad-based"
                )
            elif len(drivers) >= 3 and lead_share <= Decimal("0.40"):
                notes.append("the movement is distributed across counterparties; stop drilling")

        for driver in drivers:
            if driver.prior_amount == 0 and driver.current_amount != 0:
                notes.append(f"{driver.driver} had no activity in {prior_period}")
            elif driver.current_amount == 0 and driver.prior_amount != 0:
                notes.append(f"{driver.driver} had no activity in {current_period}")

        scoped = [
            tx
            for tx in self.tools.transactions
            if tx.account == variance.account and tx.period in {prior_period, current_period}
        ]
        by_party: dict[str, list] = {}
        for tx in scoped:
            party = getattr(tx, dimension, None) if dimension != "none" else None
            if party:
                by_party.setdefault(party.casefold().strip(), []).append(tx)
        for _party, rows in by_party.items():
            for left in rows:
                for right in rows:
                    if left.transaction_id < right.transaction_id and left.amount == -right.amount:
                        notes.append(
                            f"{right.transaction_id} is the reversal of {left.transaction_id}"
                        )
                        break

        for tx in scoped:
            text = f"{tx.category or ''} {tx.description or ''}".casefold()
            if any(marker in text for marker in ("one-time", "one time", "non-recurring")):
                notes.append(f"{tx.transaction_id} is non-recurring, do not extrapolate")

        # A same-vendor move between accounts is a reclassification only when
        # the movements offset, making the conclusion net-income neutral.
        vendor_changes: dict[str, dict[str, Decimal]] = {}
        for tx in self.tools.transactions:
            if not tx.vendor or tx.period not in {prior_period, current_period}:
                continue
            sign = Decimal("1") if tx.period == current_period else Decimal("-1")
            vendor_changes.setdefault(tx.vendor.casefold().strip(), {}).setdefault(
                tx.account, Decimal("0")
            )
            vendor_changes[tx.vendor.casefold().strip()][tx.account] += sign * tx.amount
        for vendor, changes in vendor_changes.items():
            positives = [(a, value) for a, value in changes.items() if value > 0]
            negatives = [(a, value) for a, value in changes.items() if value < 0]
            if (
                variance.account in changes
                and positives
                and negatives
                and sum(changes.values()) == 0
            ):
                notes.append(
                    f"reclassification detected: {vendor} moved between accounts; net-income neutral"
                )

        if drivers and variance.account.casefold() == "revenue":
            remainder = variance.variance - drivers[0].variance
            if variance.variance > 0 and remainder < 0:
                notes.append(
                    f"excluding {drivers[0].driver}, revenue declined by ${abs(remainder):,.2f}"
                )

        if self.memory is not None:
            notes.extend(
                self.memory.assess_business_context(
                    subject=variance.account,
                    as_of=current_period,
                    observed_variance_pct=variance.variance_pct,
                )
            )
        notes.append(f"The available data does not establish why {variance.account} changed")
        return tuple(dict.fromkeys(notes))

    def _context_for(self, account: str, current_period: date) -> tuple[BusinessContext, ...]:
        if self.memory is None:
            return ()
        started = perf_counter()
        context = tuple(
            item
            for item in self.memory.get_business_context(subject=account, as_of=current_period)
            if item.status in {"proposed", "confirmed"}
        )
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
