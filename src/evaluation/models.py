"""Schemas for repeatable Ledger Lens benchmark cases and scores."""

from datetime import date
from decimal import Decimal

from pydantic import Field

from src.ingestion.models import LedgerModel


class ExpectedAccountResult(LedgerModel):
    account: str
    variance: Decimal
    top_driver_dimension: str
    top_driver: str


class BenchmarkCase(LedgerModel):
    case_id: str
    prior_period: date
    current_period: date
    absolute_threshold: Decimal
    percentage_threshold: Decimal
    expected_accounts: list[ExpectedAccountResult] = Field(min_length=1)


class CaseScore(LedgerModel):
    case_id: str
    account_set_accuracy: Decimal
    variance_accuracy: Decimal
    driver_accuracy: Decimal
    reconciliation_rate: Decimal
    evidence_completeness: Decimal
    passed: bool


class BenchmarkScore(LedgerModel):
    cases: list[CaseScore]
    account_set_accuracy: Decimal
    variance_accuracy: Decimal
    driver_accuracy: Decimal
    reconciliation_rate: Decimal
    evidence_completeness: Decimal
    passed: bool
