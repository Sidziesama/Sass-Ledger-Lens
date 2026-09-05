import json
from datetime import date
from decimal import Decimal

import httpx
import pytest

from src.explanation import TemplateExplanationProvider
from src.ingestion.models import AccountSummary, Transaction
from src.observability import PrismTraceObserver
from src.workflow import run_workflow

PRIOR, CURRENT = date(2026, 1, 1), date(2026, 2, 1)


def data(prior="100", current="150", currency="USD"):
    summaries = [
        AccountSummary(period=p, account="Revenue", amount=a)
        for p, a in [(PRIOR, "100"), (CURRENT, "150")]
    ]
    transactions = [
        Transaction(
            transaction_id=str(p),
            period=p,
            account="Revenue",
            amount=a,
            customer="Acme",
            currency=currency,
        )
        for p, a in [(PRIOR, prior), (CURRENT, current)]
    ]
    return summaries, transactions


def execute(*, provider=None, observer=None, **kwargs):
    summaries, transactions = data(**kwargs)
    return run_workflow(
        summaries,
        transactions,
        PRIOR,
        CURRENT,
        Decimal(1),
        Decimal(1),
        provider=provider,
        observer=observer,
    )


class Client:
    def __init__(self, receipt=True):
        self.calls = []
        self.receipt = receipt

    def submit_trajectory(self, **payload):
        self.calls.append(payload)
        return {"id": "synthetic-receipt"} if self.receipt else None


def test_one_remote_run_contains_explanation_and_validation_before_finish():
    client = Client()
    result = execute(observer=PrismTraceObserver(client))
    assert len(client.calls) == 1
    call = client.calls[0]
    assert call["conversation_id"] == result.artifact["run_id"] == result.result.run_id
    steps = call["steps"]
    assert any(step["step_type"] == "llm_call" for step in steps)
    assert any(step["step_type"] == "validation" for step in steps)
    assert steps[-1]["label"] == "Workflow completed"
    assert result.artifact["telemetry"]["status"] == "delivered"


@pytest.mark.parametrize(
    "prior,current,currency", [("10", "20", "USD"), ("10", "60", "USD"), ("100", "150", "EUR")]
)
def test_incomplete_or_wrong_currency_detail_blocks_explanation(prior, current, currency):
    output = execute(prior=prior, current=current, currency=currency).artifact
    assert output["status"] == "blocked"
    assert output["accounts"][0]["reliability_issues"]
    assert output["accounts"][0]["claims"] == []
    assert output["accounts"][0]["explanation"] is None
    assert not output["accounts"][0]["evidence_sufficient"]


def test_prism_delivery_failure_retains_financial_result_and_local_trace():
    result = execute(observer=PrismTraceObserver(Client(receipt=False)))
    assert result.artifact["status"] == "complete"
    assert result.artifact["telemetry"]["status"] == "failed"
    assert result.artifact["trace"]


class TimeoutProvider:
    name = "synthetic-timeout"

    def generate(self, **kwargs):
        raise httpx.ReadTimeout("synthetic")


def test_provider_failure_is_visible_and_falls_back_within_same_run():
    client = Client()
    result = execute(provider=TimeoutProvider(), observer=PrismTraceObserver(client))
    account = result.artifact["accounts"][0]
    assert account["explanation"]["provider"] == "deterministic-template"
    assert "ReadTimeout" in account["explanation_warning"]
    assert len(client.calls) == 1
    assert any(s["label"] == "Explanation rejected" for s in client.calls[0]["steps"])


class WrongProvider:
    name = "synthetic-wrong"

    def __init__(self, text):
        self.text = text

    def generate(self, *, system, prompt):
        packet = json.loads(prompt)
        return json.dumps(
            {
                "headline": packet["approved_headlines"][0],
                "summary": self.text,
                "claim_ids": [packet["claims"][0]["claim_id"]],
            }
        )


@pytest.mark.parametrize(
    "text", ["Revenue increased because of pricing power.", "Revenue increased by 100."]
)
def test_valid_number_or_citation_does_not_authorize_an_unrelated_claim(text):
    account = execute(provider=WrongProvider(text)).artifact["accounts"][0]
    assert "UngroundedExplanationError" in account["explanation_warning"]
    assert text not in account["explanation"]["summary"]


def test_low_coverage_cannot_be_labeled_complete():
    summaries, _ = data()
    transactions = [
        Transaction(
            transaction_id=f"{p}-{customer}",
            period=p,
            account="Revenue",
            amount=amount,
            customer=customer,
        )
        for p, amount in [(PRIOR, "50"), (CURRENT, "75")]
        for customer in ("A", "B")
    ]
    result = run_workflow(
        summaries, transactions, PRIOR, CURRENT, Decimal(1), Decimal(1), max_drivers=1
    )
    account = result.artifact["accounts"][0]
    assert account["status"] == "partial"
    assert not account["evidence_sufficient"]
    assert "incomplete" in account["explanation"]["summary"]


def test_incomplete_caveat_cannot_be_dropped_by_model():
    class DropsCaveat(TemplateExplanationProvider):
        def generate(self, *, system, prompt):
            packet = json.loads(prompt)
            packet["approved_statements"] = [
                s for s in packet["approved_statements"] if "incomplete" not in s["text"]
            ]
            return super().generate(system=system, prompt=json.dumps(packet))

    summaries, _ = data()
    transactions = [
        Transaction(transaction_id=f"{p}-{c}", period=p, account="Revenue", amount=a, customer=c)
        for p, a in [(PRIOR, "50"), (CURRENT, "75")]
        for c in ("A", "B")
    ]
    result = run_workflow(
        summaries,
        transactions,
        PRIOR,
        CURRENT,
        Decimal(1),
        Decimal(1),
        max_drivers=1,
        provider=DropsCaveat(),
    )
    assert result.artifact["accounts"][0]["explanation_warning"]


def test_explicit_prism_request_requires_credentials(monkeypatch):
    for name in ("PRISMTRACE_API_KEY", "PRISMTRACE_HOST", "PRISMTRACE_PROJECT_ID"):
        monkeypatch.delenv(name, raising=False)
    with pytest.raises(RuntimeError, match="PRISM requires"):
        PrismTraceObserver.from_env(required=True)


def test_live_summary_and_trajectory_share_identity():
    traces = []
    client = Client()
    result = execute(observer=PrismTraceObserver(client, trace_sender=traces.append))
    assert len(traces) == 1
    assert traces[0]["session_id"] == client.calls[0]["conversation_id"]
    assert traces[0]["metadata"]["kind"] == "workflow_summary"
    assert json.loads(traces[0]["output_message"])[-1]["label"] == "Workflow completed"
    assert result.artifact["telemetry"]["status"] == "delivered"


def test_live_trace_failure_keeps_local_result():
    def fail(payload):
        raise httpx.ConnectError("offline")

    result = execute(observer=PrismTraceObserver(Client(), trace_sender=fail))
    assert result.artifact["status"] == "complete"
    assert result.artifact["telemetry"]["status"] == "failed"
