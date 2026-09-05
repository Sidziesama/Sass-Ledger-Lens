from datetime import date
from decimal import Decimal

from src.ingestion.models import (
    EvidenceClaim,
    InvestigationRun,
    ReviewerFeedback,
    RunAccountSummary,
)
from src.memory import compare_investigation_runs


def account(name: str, variance: str, supported: bool = True) -> RunAccountSummary:
    return RunAccountSummary(
        account=name,
        variance=Decimal(variance),
        variance_pct=Decimal("10"),
        coverage=Decimal("0.9"),
        evidence_sufficient=supported,
    )


def claim(identifier: str, driver: str) -> EvidenceClaim:
    return EvidenceClaim(
        claim_id=identifier,
        statement="supported",
        calculation="deterministic",
        driver_dimension="customer",
        driver_value=driver,
        transaction_ids=[f"tx-{identifier}"],
    )


def test_run_comparison_tracks_accounts_drivers_and_review():
    previous = InvestigationRun(
        run_id="previous",
        prior_period=date(2026, 1, 1),
        current_period=date(2026, 2, 1),
        accounts=[account("Revenue", "100")],
        claims=[claim("one", "Acme")],
    )
    current = InvestigationRun(
        run_id="current",
        prior_period=date(2026, 2, 1),
        current_period=date(2026, 3, 1),
        accounts=[account("Revenue", "60"), account("Hosting Expense", "20", False)],
        claims=[claim("two", "Globex")],
        feedback=[ReviewerFeedback(reviewer="Finance", status="needs_revision")],
    )

    comparison = compare_investigation_runs(previous, current)
    revenue = next(change for change in comparison.account_changes if change.account == "Revenue")
    hosting = next(
        change for change in comparison.account_changes if change.account == "Hosting Expense"
    )
    assert revenue.change_between_runs == Decimal("-40")
    assert hosting.prior_run_variance is None
    assert comparison.added_drivers == ["customer: Globex"]
    assert comparison.removed_drivers == ["customer: Acme"]
    assert comparison.current_review_statuses == ["needs_revision"]
