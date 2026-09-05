"""Deterministic transaction-level driver decomposition."""

from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Literal

from src.ingestion.models import Transaction

Dimension = Literal[
    "customer", "vendor", "segment", "category", "department", "product", "geography"
]


@dataclass(frozen=True)
class DriverContribution:
    dimension: str
    driver: str
    prior_amount: Decimal
    current_amount: Decimal
    variance: Decimal
    contribution_pct: Decimal | None
    transaction_ids: tuple[str, ...]


def breakdown_by_dimension(
    transactions: list[Transaction],
    account: str,
    prior_period: date,
    current_period: date,
    dimension: Dimension,
) -> list[DriverContribution]:
    totals: dict[tuple[str, date], Decimal] = defaultdict(Decimal)
    evidence: dict[str, set[str]] = defaultdict(set)
    labels: dict[str, str] = {}
    for tx in transactions:
        if tx.account != account or tx.period not in (prior_period, current_period):
            continue
        raw_driver = getattr(tx, dimension) or "Unspecified"
        # Financially identical counterparties must not become separate drivers
        # solely because source-system capitalization differs.
        driver = raw_driver.casefold().strip() if raw_driver != "Unspecified" else raw_driver
        labels.setdefault(driver, raw_driver)
        totals[(driver, tx.period)] += tx.amount
        evidence[driver].add(tx.transaction_id)

    changes = {
        driver: totals[(driver, current_period)] - totals[(driver, prior_period)]
        for driver in evidence
    }
    total_variance = sum(changes.values(), Decimal("0"))
    rows = [
        DriverContribution(
            dimension=dimension,
            driver=labels[driver],
            prior_amount=totals[(driver, prior_period)],
            current_amount=totals[(driver, current_period)],
            variance=change,
            contribution_pct=None
            if total_variance == 0
            else change / total_variance * Decimal("100"),
            transaction_ids=tuple(sorted(evidence[driver])),
        )
        for driver, change in changes.items()
    ]
    return sorted(rows, key=lambda row: (-abs(row.variance), row.driver))


def get_top_drivers(drivers: list[DriverContribution], limit: int = 5) -> list[DriverContribution]:
    if limit < 0:
        raise ValueError("limit must be non-negative")
    return drivers[:limit]
