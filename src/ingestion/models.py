"""Validated JSON-first data contracts for Ledger Lens."""

from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class LedgerModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class AccountSummary(LedgerModel):
    period: date
    account: str = Field(min_length=1)
    amount: Decimal
    currency: str = Field(default="USD", min_length=3, max_length=3)


class Transaction(LedgerModel):
    transaction_id: str = Field(min_length=1)
    period: date
    account: str = Field(min_length=1)
    amount: Decimal
    currency: str = Field(default="USD", min_length=3, max_length=3)
    customer: str | None = None
    vendor: str | None = None
    segment: str | None = None
    category: str | None = None
    department: str | None = None
    product: str | None = None
    geography: str | None = None
    description: str | None = None


class BusinessContext(LedgerModel):
    context_id: str
    subject: str
    description: str
    effective_period: date | None = None
    source: str | None = None
    tags: list[str] = Field(default_factory=list)


class EvidenceClaim(LedgerModel):
    claim_id: str
    statement: str
    calculation: str
    driver_dimension: str
    driver_value: str
    transaction_ids: list[str] = Field(min_length=1)


class ReviewerFeedback(LedgerModel):
    reviewer: str
    status: Literal["approved", "rejected", "needs_revision"]
    comment: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class RunAccountSummary(LedgerModel):
    account: str
    variance: Decimal
    variance_pct: Decimal | None
    coverage: Decimal = Field(ge=0, le=1)
    evidence_sufficient: bool


class InvestigationRun(LedgerModel):
    run_id: str
    prior_period: date
    current_period: date
    claims: list[EvidenceClaim] = Field(default_factory=list)
    accounts: list[RunAccountSummary] = Field(default_factory=list)
    feedback: list[ReviewerFeedback] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @model_validator(mode="after")
    def periods_are_ordered(self) -> "InvestigationRun":
        if self.current_period <= self.prior_period:
            raise ValueError("current_period must be after prior_period")
        return self
