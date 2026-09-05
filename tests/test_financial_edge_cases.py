from datetime import date
from decimal import Decimal

import pytest

from src.agent import FinancialTools, Investigator
from src.finance import breakdown_by_dimension, compare_periods, rank_material_variances
from src.ingestion.models import AccountSummary, Transaction

PRIOR = date(2026, 1, 1)
CURRENT = date(2026, 2, 1)


def test_zero_baseline_can_be_material_without_inventing_percentage():
    summaries = [
        AccountSummary(period=PRIOR, account="New Revenue", amount="0"),
        AccountSummary(period=CURRENT, account="New Revenue", amount="50000"),
    ]
    variance = compare_periods(summaries, PRIOR, CURRENT)[0]
    ranked = rank_material_variances(
        [variance], absolute_threshold=Decimal("10000"), percentage_threshold=Decimal("20")
    )
    assert variance.variance_pct is None
    assert ranked[0].is_material is True


def test_disappearing_account_is_negative_one_hundred_percent():
    summaries = [
        AccountSummary(period=PRIOR, account="Legacy Revenue", amount="40000"),
        AccountSummary(period=CURRENT, account="Legacy Revenue", amount="0"),
    ]
    variance = compare_periods(summaries, PRIOR, CURRENT)[0]
    assert variance.variance == Decimal("-40000")
    assert variance.variance_pct == Decimal("-100")


def test_negative_balance_change_uses_absolute_prior_denominator():
    summaries = [
        AccountSummary(period=PRIOR, account="Refunds", amount="-20000"),
        AccountSummary(period=CURRENT, account="Refunds", amount="-35000"),
    ]
    variance = compare_periods(summaries, PRIOR, CURRENT)[0]
    assert variance.variance == Decimal("-15000")
    assert variance.variance_pct == Decimal("-75.00")


def test_offsetting_drivers_reconcile_and_use_absolute_coverage():
    transactions = [
        Transaction(
            transaction_id="a-prior",
            period=PRIOR,
            account="Revenue",
            amount="100",
            customer="A",
        ),
        Transaction(
            transaction_id="a-current",
            period=CURRENT,
            account="Revenue",
            amount="200",
            customer="A",
        ),
        Transaction(
            transaction_id="b-prior",
            period=PRIOR,
            account="Revenue",
            amount="100",
            customer="B",
        ),
        Transaction(
            transaction_id="b-current",
            period=CURRENT,
            account="Revenue",
            amount="80",
            customer="B",
        ),
    ]
    drivers = breakdown_by_dimension(transactions, "Revenue", PRIOR, CURRENT, "customer")
    assert sum((driver.variance for driver in drivers), Decimal("0")) == Decimal("80")
    assert drivers[0].contribution_pct == Decimal("125.00")

    summaries = [
        AccountSummary(period=PRIOR, account="Revenue", amount="200"),
        AccountSummary(period=CURRENT, account="Revenue", amount="280"),
    ]
    result = Investigator(
        FinancialTools(summaries, transactions),
        dimensions=("customer",),
        target_coverage=Decimal("0.80"),
        max_drivers=1,
    ).investigate(PRIOR, CURRENT, Decimal("1"), Decimal("1"))
    assert result.accounts[0].stop_decision.coverage == Decimal("0.8333333333333333333333333333")


def test_mixed_currency_account_is_rejected():
    summaries = [
        AccountSummary(period=PRIOR, account="Revenue", amount="100", currency="USD"),
        AccountSummary(period=CURRENT, account="Revenue", amount="120", currency="EUR"),
    ]
    with pytest.raises(ValueError, match="mixed currencies"):
        compare_periods(summaries, PRIOR, CURRENT)
