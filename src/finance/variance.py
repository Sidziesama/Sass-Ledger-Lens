"""Deterministic account variance calculations."""

from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from src.ingestion.models import AccountSummary


@dataclass(frozen=True)
class AccountVariance:
    account: str
    prior_amount: Decimal
    current_amount: Decimal
    variance: Decimal
    variance_pct: Decimal | None


def compare_periods(
    summaries: list[AccountSummary], prior_period: date, current_period: date
) -> list[AccountVariance]:
    totals: dict[tuple[date, str], Decimal] = defaultdict(Decimal)
    currencies: dict[str, set[str]] = defaultdict(set)
    for row in summaries:
        if row.period in (prior_period, current_period):
            totals[(row.period, row.account)] += row.amount
            currencies[row.account].add(row.currency)

    mixed = [account for account, values in currencies.items() if len(values) > 1]
    if mixed:
        raise ValueError(f"Cannot compare mixed currencies for: {', '.join(sorted(mixed))}")

    accounts = sorted({account for _, account in totals})
    results = []
    for account in accounts:
        prior = totals[(prior_period, account)]
        current = totals[(current_period, account)]
        change = current - prior
        percent = None if prior == 0 else (change / abs(prior)) * Decimal("100")
        results.append(AccountVariance(account, prior, current, change, percent))
    return results
