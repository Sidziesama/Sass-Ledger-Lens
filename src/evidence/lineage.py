"""Build and verify claim-to-transaction evidence lineage."""

from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING

from pydantic import Field, model_validator

from src.ingestion.models import LedgerModel, Transaction
from src.observability import NullTraceObserver, TraceEvent, TraceObserver

if TYPE_CHECKING:
    from src.agent import AccountInvestigation


class CalculationEvidence(LedgerModel):
    prior_amount: Decimal
    current_amount: Decimal
    variance: Decimal
    contribution_pct: Decimal | None

    @model_validator(mode="after")
    def variance_reconciles(self) -> "CalculationEvidence":
        if self.current_amount - self.prior_amount != self.variance:
            raise ValueError("variance does not reconcile to current minus prior")
        return self


class TransactionEvidence(LedgerModel):
    transaction_id: str
    period: date
    amount: Decimal


class ClaimLineage(LedgerModel):
    claim_id: str
    account: str
    dimension: str
    driver: str
    calculation: CalculationEvidence
    transactions: list[TransactionEvidence] = Field(min_length=1)


class EvidenceError(ValueError):
    pass


def build_claim_lineage(
    investigation: "AccountInvestigation",
    transactions: list[Transaction],
    observer: TraceObserver | None = None,
) -> list[ClaimLineage]:
    """Create evidence records only when IDs, dimensions, and totals reconcile."""
    trace = observer or NullTraceObserver()
    index = {tx.transaction_id: tx for tx in transactions}
    if len(index) != len(transactions):
        raise EvidenceError("transaction IDs must be unique")

    claims: list[ClaimLineage] = []
    for position, driver in enumerate(investigation.drivers, start=1):
        try:
            source = [index[transaction_id] for transaction_id in driver.transaction_ids]
        except KeyError as exc:
            raise EvidenceError(f"missing transaction: {exc.args[0]}") from exc

        matching = [
            tx
            for tx in source
            if tx.account == investigation.variance.account
            and (getattr(tx, driver.dimension) or "Unspecified") == driver.driver
        ]
        if len(matching) != len(source):
            raise EvidenceError(f"transaction lineage does not match driver {driver.driver}")

        prior_total = sum(
            (tx.amount for tx in matching if tx.period == investigation.prior_period),
            Decimal("0"),
        )
        current_total = sum(
            (tx.amount for tx in matching if tx.period == investigation.current_period),
            Decimal("0"),
        )
        if prior_total != driver.prior_amount or current_total != driver.current_amount:
            raise EvidenceError(f"transaction amounts do not reconcile for driver {driver.driver}")

        claims.append(
            ClaimLineage(
                claim_id=f"{investigation.variance.account}:{driver.dimension}:{position}",
                account=investigation.variance.account,
                dimension=driver.dimension,
                driver=driver.driver,
                calculation=CalculationEvidence(
                    prior_amount=prior_total,
                    current_amount=current_total,
                    variance=driver.variance,
                    contribution_pct=driver.contribution_pct,
                ),
                transactions=[
                    TransactionEvidence(
                        transaction_id=tx.transaction_id,
                        period=tx.period,
                        amount=tx.amount,
                    )
                    for tx in matching
                ],
            )
        )
        trace.record(
            TraceEvent(
                step_type="tool_call",
                label=f"Verify evidence for {driver.driver}",
                tool_name="build_claim_lineage",
                input_summary=f"{len(driver.transaction_ids)} transaction IDs",
                output_summary=f"claim reconciled; variance={driver.variance}",
            )
        )
    return claims
