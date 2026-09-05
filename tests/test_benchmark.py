from decimal import Decimal

from src.evaluation import run_benchmark


def test_benchmark_proves_financial_and_evidence_quality():
    score = run_benchmark()
    assert score.passed is True
    assert score.account_set_accuracy == Decimal("1")
    assert score.variance_accuracy == Decimal("1")
    assert score.driver_accuracy == Decimal("1")
    assert score.reconciliation_rate == Decimal("1")
    assert score.evidence_completeness == Decimal("1")
    assert len(score.cases) == 2
