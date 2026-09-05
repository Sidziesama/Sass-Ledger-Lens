from datetime import date
from decimal import Decimal

import pytest

from src.agent import FinancialTools, Investigator
from src.evidence import build_claim_lineage
from src.ingestion.models import AccountSummary, Transaction
from src.observability import (
    InMemoryTraceObserver,
    NullTraceObserver,
    PrismTraceObserver,
    TraceEvent,
)

PRIOR = date(2026, 1, 1)
CURRENT = date(2026, 2, 1)


def fixture_data():
    summaries = [
        AccountSummary(period=PRIOR, account="Revenue", amount="100"),
        AccountSummary(period=CURRENT, account="Revenue", amount="150"),
    ]
    transactions = [
        Transaction(
            transaction_id="p", period=PRIOR, account="Revenue", amount="100", customer="A"
        ),
        Transaction(
            transaction_id="c", period=CURRENT, account="Revenue", amount="150", customer="A"
        ),
    ]
    return summaries, transactions


def test_investigation_records_tools_decisions_and_outcome():
    summaries, transactions = fixture_data()
    observer = InMemoryTraceObserver()
    result = Investigator(
        FinancialTools(summaries, transactions), dimensions=("customer",), observer=observer
    ).investigate(PRIOR, CURRENT, Decimal("1"), Decimal("1"))
    build_claim_lineage(result.accounts[0], transactions, observer)
    assert observer.final_status == "success"
    assert {event.step_type for event in observer.events} >= {
        "tool_call",
        "reasoning",
        "final_answer",
    }
    assert any(event.tool_name == "breakdown_by_dimension" for event in observer.events)
    assert any(event.tool_name == "build_claim_lineage" for event in observer.events)


def test_failure_is_observed_and_reraised():
    summaries, transactions = fixture_data()
    summaries[1] = AccountSummary(period=CURRENT, account="Revenue", amount="150", currency="EUR")
    observer = InMemoryTraceObserver()
    with pytest.raises(ValueError, match="mixed currencies"):
        Investigator(FinancialTools(summaries, transactions), observer=observer).investigate(
            PRIOR, CURRENT, Decimal("1"), Decimal("1")
        )
    assert observer.final_status == "error"
    assert observer.events[-1].status == "error"


class FakePrismClient:
    def __init__(self):
        self.payload = None
        self.llm_payloads = []
        self.flushed = False

    def submit_trajectory(self, **payload):
        self.payload = payload
        return {"id": "trajectory-1"}

    def trace_llm(self, **payload):
        self.llm_payloads.append(payload)

    def flush(self):
        self.flushed = True


def test_prism_adapter_submits_sdk_trajectory():
    client = FakePrismClient()
    observer = PrismTraceObserver(client)
    summaries, transactions = fixture_data()
    Investigator(
        FinancialTools(summaries, transactions), dimensions=("customer",), observer=observer
    ).investigate(PRIOR, CURRENT, Decimal("1"), Decimal("1"))
    assert client.payload["agent_id"] == "ledger-lens"
    assert client.payload["final_status"] == "success"
    assert client.payload["steps"]
    assert any(step.get("tool_name") == "build_claim_lineage" for step in client.payload["steps"])


def test_prism_adapter_submits_an_existing_complete_trajectory():
    client = FakePrismClient()
    observer = PrismTraceObserver(client)
    events = [
        TraceEvent(step_type="tool_call", label="Investigate"),
        TraceEvent(step_type="llm_call", label="Explain"),
    ]
    result = observer.submit_existing("run-1", events)
    assert result == {"id": "trajectory-1"}
    assert client.payload["request_id"] == "run-1"
    assert [step["step_type"] for step in client.payload["steps"]] == [
        "tool_call",
        "llm_call",
    ]
    assert client.llm_payloads[0]["metadata"]["session_id"] == "run-1"
    assert client.llm_payloads[0]["agent_id"] == "ledger-lens"
    assert client.flushed is True


def test_missing_prism_configuration_is_offline_safe(monkeypatch):
    for name in ("PRISMTRACE_API_KEY", "PRISMTRACE_HOST", "PRISMTRACE_PROJECT_ID"):
        monkeypatch.delenv(name, raising=False)
    assert isinstance(PrismTraceObserver.from_env(), NullTraceObserver)
