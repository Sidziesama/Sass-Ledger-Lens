from datetime import date
from decimal import Decimal

from src.agent import FinancialTools, Investigator
from src.evidence import build_claim_lineage
from src.explanation import EvidenceBoundExplainer, TemplateExplanationProvider
from src.ingestion.models import AccountSummary, Transaction
from src.quality import run_quality_gate

PRIOR = date(2026, 1, 1)
CURRENT = date(2026, 2, 1)


def test_quality_gate_reports_amount_bearing_gap_and_blocks_attribution():
    summaries = [
        AccountSummary(period=PRIOR, account="Revenue", amount="100"),
        AccountSummary(period=CURRENT, account="Revenue", amount="200"),
    ]
    transactions = [
        Transaction(
            transaction_id="p", period=PRIOR, account="Revenue", amount="100", customer="A"
        ),
        Transaction(
            transaction_id="c", period=CURRENT, account="Revenue", amount="150", customer="A"
        ),
    ]
    account = (
        Investigator(FinancialTools(summaries, transactions), dimensions=("customer",))
        .investigate(PRIOR, CURRENT, Decimal("1"), Decimal("1"))
        .accounts[0]
    )
    assert account.stop_decision.reason == "data_quality_blocker"
    assert any(
        "cannot reliably attribute Revenue: gap of $50.00" in flag.message
        for flag in account.quality_flags
    )


def test_quality_gate_detects_near_duplicates_cutoff_variants_and_period_gap():
    march = date(2026, 3, 1)
    summaries = [
        AccountSummary(period=PRIOR, account="Revenue", amount="20"),
        AccountSummary(period=march, account="Revenue", amount="20"),
    ]
    transactions = [
        Transaction(
            transaction_id="a",
            period=PRIOR,
            transaction_date=date(2026, 1, 30),
            account="Revenue",
            amount="10",
            customer="Acme",
        ),
        Transaction(
            transaction_id="b",
            period=PRIOR,
            transaction_date=date(2026, 2, 1),
            account="Revenue",
            amount="10",
            customer="acme",
        ),
        Transaction(
            transaction_id="c",
            period=march,
            transaction_date=march,
            account="Revenue",
            amount="20",
            customer="ACME",
        ),
    ]
    codes = {flag.code for flag in run_quality_gate(summaries, transactions, PRIOR, march).flags}
    assert {"near_duplicate", "cutoff", "naming_variant", "period_gap"} <= codes


def test_memo_states_zero_base_inactivity_concentration_and_causal_limit():
    summaries = [
        AccountSummary(period=PRIOR, account="Revenue", amount="0"),
        AccountSummary(period=CURRENT, account="Revenue", amount="100"),
    ]
    transactions = [
        Transaction(
            transaction_id="new", period=CURRENT, account="Revenue", amount="100", customer="Acme"
        )
    ]
    account = (
        Investigator(FinancialTools(summaries, transactions), dimensions=("customer",))
        .investigate(PRIOR, CURRENT, Decimal("1"), Decimal("1"))
        .accounts[0]
    )
    claims = build_claim_lineage(account, transactions)
    memo = EvidenceBoundExplainer(TemplateExplanationProvider()).explain(account, claims).summary
    assert "percentage change is not meaningful" in memo
    assert f"had no activity in {PRIOR}" in memo
    assert "not broad-based" in memo
    assert "The available data does not establish why Revenue changed" in memo


def test_reclassification_is_detected_from_offsetting_vendor_movements():
    summaries = [
        AccountSummary(period=PRIOR, account="Travel", amount="100"),
        AccountSummary(period=CURRENT, account="Travel", amount="0"),
        AccountSummary(period=PRIOR, account="Consulting", amount="0"),
        AccountSummary(period=CURRENT, account="Consulting", amount="100"),
    ]
    transactions = [
        Transaction(
            transaction_id="old", period=PRIOR, account="Travel", amount="100", vendor="Acme"
        ),
        Transaction(
            transaction_id="new", period=CURRENT, account="Consulting", amount="100", vendor="ACME"
        ),
    ]
    result = Investigator(
        FinancialTools(summaries, transactions), dimensions=("vendor",)
    ).investigate(PRIOR, CURRENT, Decimal("1"), Decimal("1"))
    assert all(
        any("reclassification detected" in note for note in account.reliability_notes)
        for account in result.accounts
    )


def test_reversal_one_time_distributed_and_outlier_masking_are_explicit():
    summaries = [
        AccountSummary(period=PRIOR, account="Revenue", amount="0"),
        AccountSummary(period=CURRENT, account="Revenue", amount="40"),
    ]
    transactions = [
        Transaction(
            transaction_id="a-prior", period=PRIOR, account="Revenue", amount="-10", customer="A"
        ),
        Transaction(
            transaction_id="a-current",
            period=CURRENT,
            account="Revenue",
            amount="10",
            customer="A",
            description="one-time settlement",
        ),
        Transaction(
            transaction_id="b", period=CURRENT, account="Revenue", amount="10", customer="B"
        ),
        Transaction(
            transaction_id="c", period=CURRENT, account="Revenue", amount="10", customer="C"
        ),
        Transaction(
            transaction_id="d", period=CURRENT, account="Revenue", amount="10", customer="D"
        ),
    ]
    account = (
        Investigator(
            FinancialTools(summaries, transactions),
            dimensions=("customer",),
            target_coverage=Decimal("1"),
        )
        .investigate(PRIOR, CURRENT, Decimal("1"), Decimal("1"))
        .accounts[0]
    )
    memo = " ".join(account.reliability_notes)
    assert "is the reversal of" in memo
    assert "non-recurring, do not extrapolate" in memo
    assert "distributed across counterparties; stop drilling" in memo


def test_positive_revenue_can_disclose_decline_without_the_outlier():
    summaries = [
        AccountSummary(period=PRIOR, account="Revenue", amount="100"),
        AccountSummary(period=CURRENT, account="Revenue", amount="110"),
    ]
    transactions = [
        Transaction(
            transaction_id="a0", period=PRIOR, account="Revenue", amount="50", customer="A"
        ),
        Transaction(
            transaction_id="a1", period=CURRENT, account="Revenue", amount="80", customer="A"
        ),
        Transaction(
            transaction_id="b0", period=PRIOR, account="Revenue", amount="50", customer="B"
        ),
        Transaction(
            transaction_id="b1", period=CURRENT, account="Revenue", amount="30", customer="B"
        ),
    ]
    account = (
        Investigator(FinancialTools(summaries, transactions), dimensions=("customer",))
        .investigate(PRIOR, CURRENT, Decimal("1"), Decimal("1"))
        .accounts[0]
    )
    assert any(
        "excluding A, revenue declined by $20.00" in note for note in account.reliability_notes
    )
