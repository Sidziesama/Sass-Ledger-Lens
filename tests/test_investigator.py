from datetime import date
from decimal import Decimal
from pathlib import Path

from src.agent import FinancialTools, Investigator
from src.ingestion.loaders import load_account_summaries, load_transactions

ROOT = Path(__file__).parents[1]
PRIOR = date(2026, 1, 1)
CURRENT = date(2026, 2, 1)


def tools():
    return FinancialTools(
        load_account_summaries(ROOT / "data/sample/monthly_summary.json"),
        load_transactions(ROOT / "data/sample/transactions.json"),
    )


def test_investigator_stops_on_coverage_with_evidence():
    result = Investigator(
        tools(), dimensions=("customer",), target_coverage=Decimal("0.80")
    ).investigate(PRIOR, CURRENT, Decimal("50000"), Decimal("10"))
    assert len(result.accounts) == 1
    investigation = result.accounts[0]
    assert investigation.variance.account == "Revenue"
    assert investigation.stop_decision.should_stop is True
    assert investigation.stop_decision.coverage >= Decimal("0.80")
    assert all(driver.transaction_ids for driver in investigation.drivers)


def test_transaction_lookup_is_exact_and_filtered():
    matches = tools().get_transactions(["jan-acme", "feb-acme"], period=CURRENT)
    assert [tx.transaction_id for tx in matches] == ["feb-acme"]


def test_counterparty_history_and_contribution_are_deterministic():
    financial_tools = tools()
    history = financial_tools.compare_counterparty_history("customer", "Acme", "Revenue")
    assert history == {PRIOR: Decimal("300000"), CURRENT: Decimal("352000")}
    assert financial_tools.calculate_driver_contribution(
        Decimal("52000"), Decimal("180000")
    ) == Decimal("28.88888888888888888888888889")


def test_account_without_transactions_does_not_claim_success():
    result = Investigator(tools()).investigate(PRIOR, CURRENT, Decimal("0"), Decimal("0"))
    hosting = next(row for row in result.accounts if row.variance.account == "Hosting Expense")
    assert hosting.stop_decision.should_stop is False
    assert hosting.stop_decision.reason == "no_transaction_drivers"
