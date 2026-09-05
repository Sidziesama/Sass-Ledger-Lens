from datetime import date
from decimal import Decimal

import pytest

from src.agent import FinancialTools, Investigator
from src.ingestion.models import (
    BusinessContext,
    InvestigationRun,
    ReviewerFeedback,
)
from src.memory import JsonMemoryStore


def test_context_is_upserted_and_retrieved_by_subject_and_date(tmp_path):
    memory = JsonMemoryStore(tmp_path)
    memory.save_business_context(
        BusinessContext(
            context_id="event-1",
            subject="Revenue",
            description="Enterprise renewals accelerated.",
            effective_period=date(2026, 2, 1),
            tags=["enterprise"],
        )
    )
    memory.save_business_context(
        BusinessContext(
            context_id="event-1",
            subject="Revenue",
            description="Finance confirmed enterprise renewals accelerated.",
            effective_period=date(2026, 2, 1),
            tags=["enterprise", "confirmed"],
        )
    )
    assert memory.get_business_context(subject="Revenue", as_of=date(2026, 1, 1)) == []
    matches = memory.get_business_context(subject="revenue", tags={"confirmed"}, as_of=date(2026, 2, 1))
    assert len(matches) == 1
    assert matches[0].description.startswith("Finance confirmed")


def test_runs_are_immutable_and_feedback_is_appended(tmp_path):
    memory = JsonMemoryStore(tmp_path)
    run = InvestigationRun(
        run_id="run-1", prior_period=date(2026, 1, 1), current_period=date(2026, 2, 1)
    )
    memory.save_investigation_run(run)
    with pytest.raises(ValueError, match="already exists"):
        memory.save_investigation_run(run)

    updated = memory.add_reviewer_feedback(
        "run-1",
        ReviewerFeedback(reviewer="finance", status="approved", comment="Verified"),
    )
    assert updated.feedback[0].status == "approved"
    assert memory.list_investigation_runs()[0].feedback[0].comment == "Verified"


def test_investigator_receives_relevant_prior_context(tmp_path):
    memory = JsonMemoryStore(tmp_path)
    memory.save_business_context(
        BusinessContext(
            context_id="event-1",
            subject="Revenue",
            description="Known renewal event",
            effective_period=date(2026, 2, 1),
        )
    )
    from src.ingestion.models import AccountSummary, Transaction

    summaries = [
        AccountSummary(period=date(2026, 1, 1), account="Revenue", amount="100"),
        AccountSummary(period=date(2026, 2, 1), account="Revenue", amount="150"),
    ]
    transactions = [
        Transaction(transaction_id="p", period=date(2026, 1, 1), account="Revenue", amount="100", customer="A"),
        Transaction(transaction_id="c", period=date(2026, 2, 1), account="Revenue", amount="150", customer="A"),
    ]
    result = Investigator(FinancialTools(summaries, transactions), dimensions=("customer",), memory=memory).investigate(
        date(2026, 1, 1), date(2026, 2, 1), Decimal("1"), Decimal("1")
    )
    assert result.accounts[0].business_context[0].description == "Known renewal event"


def test_feedback_for_unknown_run_fails(tmp_path):
    with pytest.raises(KeyError, match="unknown investigation run"):
        JsonMemoryStore(tmp_path).add_reviewer_feedback(
            "missing", ReviewerFeedback(reviewer="finance", status="rejected")
        )
