from datetime import date
from decimal import Decimal
from pathlib import Path

from src.finance import breakdown_by_dimension, compare_periods, rank_material_variances
from src.ingestion.loaders import load_account_summaries, load_transactions

ROOT = Path(__file__).parents[1]
PRIOR = date(2026, 1, 1)
CURRENT = date(2026, 2, 1)


def test_period_comparison_is_exact():
    results = compare_periods(load_account_summaries(ROOT / "data/sample/monthly_summary.json"), PRIOR, CURRENT)
    revenue = next(row for row in results if row.account == "Revenue")
    assert revenue.variance == Decimal("180000")
    assert revenue.variance_pct == Decimal("18.00")


def test_materiality_ranking():
    results = compare_periods(load_account_summaries(ROOT / "data/sample/monthly_summary.json"), PRIOR, CURRENT)
    ranked = rank_material_variances(results, Decimal("50000"), Decimal("10"))
    assert ranked[0].result.account == "Revenue"
    assert ranked[0].is_material is True
    assert ranked[1].is_material is False


def test_customer_decomposition_reconciles_and_retains_lineage():
    rows = breakdown_by_dimension(load_transactions(ROOT / "data/sample/transactions.json"), "Revenue", PRIOR, CURRENT, "customer")
    assert sum((row.variance for row in rows), Decimal("0")) == Decimal("180000")
    assert rows[0].driver == "Other"
    assert rows[0].variance == Decimal("65000")
    acme = next(row for row in rows if row.driver == "Acme")
    assert acme.contribution_pct == Decimal("28.88888888888888888888888889")
    assert acme.transaction_ids == ("feb-acme", "jan-acme")


def test_segment_decomposition():
    rows = breakdown_by_dimension(load_transactions(ROOT / "data/sample/transactions.json"), "Revenue", PRIOR, CURRENT, "segment")
    enterprise = next(row for row in rows if row.driver == "Enterprise")
    assert enterprise.variance == Decimal("93000")
