from dataclasses import replace
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from src.agent import FinancialTools, Investigator
from src.evidence import EvidenceError, build_claim_lineage
from src.ingestion.loaders import load_account_summaries, load_transactions

ROOT = Path(__file__).parents[1]
PRIOR = date(2026, 1, 1)
CURRENT = date(2026, 2, 1)


def investigation_and_transactions():
    transactions = load_transactions(ROOT / "data/sample/transactions.json")
    tools = FinancialTools(
        load_account_summaries(ROOT / "data/sample/monthly_summary.json"), transactions
    )
    result = Investigator(tools, dimensions=("customer",)).investigate(
        PRIOR, CURRENT, Decimal("50000"), Decimal("10")
    )
    return result.accounts[0], transactions


def test_claims_have_calculation_driver_and_transactions():
    investigation, transactions = investigation_and_transactions()
    claims = build_claim_lineage(investigation, transactions)
    assert claims
    assert all(claim.calculation.variance for claim in claims)
    assert all(claim.driver for claim in claims)
    assert all(claim.transactions for claim in claims)
    assert sum((claim.calculation.variance for claim in claims), Decimal("0")) == sum(
        (driver.variance for driver in investigation.drivers), Decimal("0")
    )


def test_missing_transaction_invalidates_claim():
    investigation, transactions = investigation_and_transactions()
    first_driver = replace(
        investigation.drivers[0], transaction_ids=("missing-transaction",)
    )
    tampered = replace(investigation, drivers=(first_driver,))
    with pytest.raises(EvidenceError, match="missing transaction"):
        build_claim_lineage(tampered, transactions)
