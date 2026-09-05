"""Deterministic tools available to the investigator.

These functions return financial facts; an LLM may describe their output but must
never replace their calculations.
"""

from datetime import date
from decimal import Decimal

from src.finance import (
    AccountVariance,
    DriverContribution,
    MaterialVariance,
    breakdown_by_dimension,
    compare_periods,
    get_top_drivers,
    rank_material_variances,
)
from src.finance.decomposition import Dimension
from src.ingestion.models import AccountSummary, Transaction


class FinancialTools:
    def __init__(self, summaries: list[AccountSummary], transactions: list[Transaction]):
        self.summaries = summaries
        self.transactions = transactions

    def compare_periods(self, prior_period: date, current_period: date) -> list[AccountVariance]:
        return compare_periods(self.summaries, prior_period, current_period)

    def rank_material_variances(
        self,
        prior_period: date,
        current_period: date,
        absolute_threshold: Decimal,
        percentage_threshold: Decimal,
    ) -> list[MaterialVariance]:
        return rank_material_variances(
            self.compare_periods(prior_period, current_period),
            absolute_threshold,
            percentage_threshold,
        )

    def breakdown_by_dimension(
        self,
        account: str,
        prior_period: date,
        current_period: date,
        dimension: Dimension,
    ) -> list[DriverContribution]:
        return breakdown_by_dimension(
            self.transactions, account, prior_period, current_period, dimension
        )

    def get_top_drivers(
        self,
        account: str,
        prior_period: date,
        current_period: date,
        dimension: Dimension,
        limit: int = 5,
    ) -> list[DriverContribution]:
        return get_top_drivers(
            self.breakdown_by_dimension(account, prior_period, current_period, dimension),
            limit,
        )

    def get_transactions(
        self,
        transaction_ids: list[str] | tuple[str, ...] | None = None,
        *,
        account: str | None = None,
        period: date | None = None,
    ) -> list[Transaction]:
        ids = set(transaction_ids) if transaction_ids is not None else None
        return [
            tx
            for tx in self.transactions
            if (ids is None or tx.transaction_id in ids)
            and (account is None or tx.account == account)
            and (period is None or tx.period == period)
        ]

    def compare_counterparty_history(
        self, dimension: Dimension, counterparty: str, account: str | None = None
    ) -> dict[date, Decimal]:
        totals: dict[date, Decimal] = {}
        for tx in self.transactions:
            if getattr(tx, dimension) != counterparty or (account and tx.account != account):
                continue
            totals[tx.period] = totals.get(tx.period, Decimal("0")) + tx.amount
        return dict(sorted(totals.items()))

    @staticmethod
    def calculate_driver_contribution(
        driver_variance: Decimal, total_variance: Decimal
    ) -> Decimal | None:
        return None if total_variance == 0 else driver_variance / total_variance * Decimal("100")
