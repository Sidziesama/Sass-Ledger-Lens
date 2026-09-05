import json
from datetime import date
from decimal import Decimal

import pytest

from src.agent import FinancialTools, Investigator
from src.evidence import build_claim_lineage
from src.explanation import (
    EvidenceBoundExplainer,
    OpenAICompatibleProvider,
    TemplateExplanationProvider,
    UngroundedExplanationError,
)
from src.ingestion.models import AccountSummary, Transaction
from src.observability import InMemoryTraceObserver

PRIOR = date(2026, 1, 1)
CURRENT = date(2026, 2, 1)


def evidence():
    summaries = [
        AccountSummary(period=PRIOR, account="Revenue", amount="100"),
        AccountSummary(period=CURRENT, account="Revenue", amount="150"),
    ]
    transactions = [
        Transaction(transaction_id="p", period=PRIOR, account="Revenue", amount="100", customer="A"),
        Transaction(transaction_id="c", period=CURRENT, account="Revenue", amount="150", customer="A"),
    ]
    result = Investigator(FinancialTools(summaries, transactions), dimensions=("customer",)).investigate(
        PRIOR, CURRENT, Decimal("1"), Decimal("1")
    )
    account = result.accounts[0]
    return account, build_claim_lineage(account, transactions)


def test_template_explanation_is_grounded_and_traced():
    account, claims = evidence()
    observer = InMemoryTraceObserver()
    result = EvidenceBoundExplainer(TemplateExplanationProvider(), observer).explain(account, claims)
    assert result.grounded is True
    assert result.claim_ids == [claims[0].claim_id]
    assert observer.final_status == "success"
    assert observer.events[0].step_type == "llm_call"


class StaticProvider:
    name = "test"

    def __init__(self, payload):
        self.payload = payload

    def generate(self, *, system, prompt):
        return json.dumps(self.payload)


def test_unknown_claim_is_rejected():
    account, claims = evidence()
    provider = StaticProvider(
        {"headline": "Revenue changed", "summary": "Supported summary", "claim_ids": ["invented"]}
    )
    with pytest.raises(UngroundedExplanationError, match="unknown claims"):
        EvidenceBoundExplainer(provider).explain(account, claims)


def test_invented_number_is_rejected_and_failure_is_traced():
    account, claims = evidence()
    observer = InMemoryTraceObserver()
    provider = StaticProvider(
        {
            "headline": "Revenue increased 999%",
            "summary": "Customer A caused the change.",
            "claim_ids": [claims[0].claim_id],
        }
    )
    with pytest.raises(UngroundedExplanationError, match="unsupported numbers"):
        EvidenceBoundExplainer(provider, observer).explain(account, claims)
    assert observer.final_status == "error"


def test_openai_compatible_provider_requires_complete_environment(monkeypatch):
    monkeypatch.setenv("LEDGER_LENS_LLM_BASE_URL", "http://localhost:1234/v1")
    monkeypatch.delenv("LEDGER_LENS_LLM_API_KEY", raising=False)
    monkeypatch.setenv("LEDGER_LENS_LLM_MODEL", "local")
    assert OpenAICompatibleProvider.from_env() is None
