from datetime import date
from decimal import Decimal

from src.agent import FinancialTools
from src.evaluation import BenchmarkCase, ExpectedAccountResult, evaluate_case
from src.ingestion.models import AccountSummary, Transaction


def test_benchmark_fails_on_unexpected_material_account():
    prior = date(2026, 1, 1)
    current = date(2026, 2, 1)
    summaries = [
        AccountSummary(period=prior, account="Revenue", amount="100"),
        AccountSummary(period=current, account="Revenue", amount="150"),
        AccountSummary(period=prior, account="Expense", amount="10"),
        AccountSummary(period=current, account="Expense", amount="30"),
    ]
    transactions = [
        Transaction(
            transaction_id="r1",
            period=prior,
            account="Revenue",
            amount="100",
            customer="A",
        ),
        Transaction(
            transaction_id="r2",
            period=current,
            account="Revenue",
            amount="150",
            customer="A",
        ),
        Transaction(
            transaction_id="e1",
            period=prior,
            account="Expense",
            amount="10",
            vendor="V",
        ),
        Transaction(
            transaction_id="e2",
            period=current,
            account="Expense",
            amount="30",
            vendor="V",
        ),
    ]
    case = BenchmarkCase(
        case_id="strict-account-set",
        prior_period=prior,
        current_period=current,
        absolute_threshold=Decimal("1"),
        percentage_threshold=Decimal("1"),
        expected_accounts=[
            ExpectedAccountResult(
                account="Revenue",
                variance=Decimal("50"),
                top_driver_dimension="customer",
                top_driver="A",
            )
        ],
    )
    score = evaluate_case(case, FinancialTools(summaries, transactions))
    assert score.account_set_accuracy == Decimal("0")
    assert score.passed is False
