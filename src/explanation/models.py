"""Contracts for evidence-bound financial explanations."""

from pydantic import Field

from src.ingestion.models import LedgerModel


class ExplanationDraft(LedgerModel):
    headline: str = Field(min_length=1)
    summary: str = Field(min_length=1)
    claim_ids: list[str] = Field(min_length=1)


class GroundedExplanation(ExplanationDraft):
    account: str
    provider: str
    grounded: bool = True
