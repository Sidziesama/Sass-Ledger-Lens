import json
from datetime import date
from decimal import Decimal

import pytest

from src.agent import FinancialTools, Investigator
from src.evidence import build_claim_lineage
from src.explanation import (
    EvidenceBoundExplainer,
    LLMResponseError,
    OpenAICompatibleProvider,
    TemplateExplanationProvider,
    UngroundedExplanationError,
)
from src.ingestion.models import AccountSummary, Transaction
from src.observability import InMemoryTraceObserver

PRIOR = date(2026, 1, 1)
CURRENT = date(2026, 2, 1)


class StreamContext:
    def __init__(self, response):
        self.response = response

    def __enter__(self):
        return self.response

    def __exit__(self, *args):
        return False


def evidence():
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
    result = Investigator(
        FinancialTools(summaries, transactions), dimensions=("customer",)
    ).investigate(PRIOR, CURRENT, Decimal("1"), Decimal("1"))
    account = result.accounts[0]
    return account, build_claim_lineage(account, transactions)


def test_template_explanation_is_grounded_and_traced():
    account, claims = evidence()
    observer = InMemoryTraceObserver()
    result = EvidenceBoundExplainer(TemplateExplanationProvider(), observer).explain(
        account, claims
    )
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


def test_openai_compatible_provider_accepts_fenced_json(monkeypatch):
    class Response:
        status_code = 200
        headers = {}

        def raise_for_status(self):
            pass

        def json(self):
            return {
                "choices": [
                    {
                        "message": {
                            "content": '```json\n{"headline":"h","summary":"s","claim_ids":["c"]}\n```'
                        }
                    }
                ]
            }

    captured = {}

    def fake_stream(method, url, **kwargs):
        captured.update(kwargs["json"])
        return StreamContext(Response())

    monkeypatch.setattr("src.explanation.providers.httpx.stream", fake_stream)
    provider = OpenAICompatibleProvider(
        base_url="http://127.0.0.1:41337/v1", api_key="local", model="local"
    )
    result = provider.generate(system="system", prompt="prompt")
    assert result.startswith('{"headline"')
    assert "response_format" not in captured
    assert captured["stream"] is True
    assert captured["messages"][0]["content"].startswith("/no_think\n")


def test_openai_compatible_provider_compacts_evidence_for_gide(monkeypatch):
    class Response:
        status_code = 200
        headers = {}

        def raise_for_status(self):
            pass

        def json(self):
            return {
                "choices": [
                    {"message": {"content": "Revenue increased by 50."}, "finish_reason": "stop"}
                ]
            }

    captured = {}

    def fake_stream(method, url, **kwargs):
        captured.update(kwargs["json"])
        return StreamContext(Response())

    prompt = json.dumps(
        {
            "account": "Revenue",
            "variance": {
                "prior_amount": "100",
                "current_amount": "150",
                "amount": "+50",
                "percentage_display": "50%",
            },
            "coverage_percentage": "100",
            "evidence_sufficient": True,
            "claims": [
                {
                    "claim_id": "claim-1",
                    "driver": "A",
                    "variance": "+50",
                    "transaction_count": 2,
                }
            ],
        }
    )
    monkeypatch.setattr("src.explanation.providers.httpx.stream", fake_stream)
    provider = OpenAICompatibleProvider(
        base_url="http://127.0.0.1:41337/v1", api_key="local", model="local"
    )
    provider.generate(system="system", prompt=prompt)
    sent = captured["messages"][1]["content"]
    assert "Verified drivers: A +50 (2 transactions)" in sent
    assert "claim_id" not in sent


def test_openai_compatible_provider_collects_streamed_gide_content(monkeypatch):
    class Response:
        status_code = 200
        headers = {"content-type": "text/event-stream"}
        text = "\n".join(
            [
                'data: {"choices":[{"delta":{"reasoning_content":"thinking"},"finish_reason":null}]}',
                'data: {"choices":[{"delta":{"content":"Revenue increased by 50."},"finish_reason":null}]}',
                'data: {"choices":[{"delta":{},"finish_reason":"stop"}]}',
                "data: [DONE]",
            ]
        )

        def raise_for_status(self):
            pass

    prompt = json.dumps({"account": "Revenue", "claims": [{"claim_id": "claim-1"}]})
    monkeypatch.setattr(
        "src.explanation.providers.httpx.stream",
        lambda *args, **kwargs: StreamContext(Response()),
    )
    provider = OpenAICompatibleProvider(
        base_url="http://127.0.0.1:41337/v1", api_key="local", model="local"
    )
    result = json.loads(provider.generate(system="system", prompt=prompt))
    assert result["summary"] == "Revenue increased by 50."
    assert result["claim_ids"] == ["claim-1"]


def test_openai_compatible_provider_extracts_json_from_reasoning(monkeypatch):
    class Response:
        status_code = 200
        headers = {}

        def raise_for_status(self):
            pass

        def json(self):
            return {
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {
                            "content": "",
                            "reasoning_content": (
                                'I will return the object. {"headline":"h","summary":"s",'
                                '"claim_ids":["c"]}'
                            ),
                        },
                    }
                ]
            }

    monkeypatch.setattr(
        "src.explanation.providers.httpx.stream",
        lambda *args, **kwargs: StreamContext(Response()),
    )
    provider = OpenAICompatibleProvider(
        base_url="http://127.0.0.1:41337/v1", api_key="local", model="local"
    )
    assert provider.generate(system="system", prompt="prompt").startswith('{"headline"')


def test_openai_compatible_provider_wraps_raw_prose_with_verified_claims(monkeypatch):
    class Response:
        status_code = 200
        headers = {}

        def raise_for_status(self):
            pass

        def json(self):
            return {
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {"content": "Revenue increased by 50."},
                    }
                ]
            }

    prompt = json.dumps({"account": "Revenue", "claims": [{"claim_id": "claim-1"}]})
    monkeypatch.setattr(
        "src.explanation.providers.httpx.stream",
        lambda *args, **kwargs: StreamContext(Response()),
    )
    provider = OpenAICompatibleProvider(
        base_url="http://127.0.0.1:41337/v1", api_key="local", model="local"
    )
    result = json.loads(provider.generate(system="system", prompt=prompt))
    assert result == {
        "headline": "Revenue variance",
        "summary": "Revenue increased by 50.",
        "claim_ids": ["claim-1"],
    }


def test_openai_compatible_provider_reports_safe_empty_response_details(monkeypatch):
    class Response:
        status_code = 200
        headers = {}

        def raise_for_status(self):
            pass

        def json(self):
            return {
                "choices": [
                    {
                        "finish_reason": "length",
                        "message": {"content": "", "reasoning_content": "thinking"},
                    }
                ]
            }

    monkeypatch.setattr(
        "src.explanation.providers.httpx.stream",
        lambda *args, **kwargs: StreamContext(Response()),
    )
    provider = OpenAICompatibleProvider(
        base_url="http://127.0.0.1:41337/v1", api_key="secret", model="local"
    )
    with pytest.raises(LLMResponseError, match="finish_reason=length") as error:
        provider.generate(system="system", prompt="prompt")
    assert "secret" not in str(error.value)


def test_openai_compatible_provider_retries_local_busy_response(monkeypatch):
    class Response:
        headers = {"Retry-After": "0"}

        def __init__(self, status_code):
            self.status_code = status_code

        def raise_for_status(self):
            assert self.status_code == 200

        def json(self):
            return {
                "choices": [
                    {"message": {"content": '{"headline":"h","summary":"s","claim_ids":["c"]}'}}
                ]
            }

    responses = iter([Response(429), Response(200)])
    monkeypatch.setattr(
        "src.explanation.providers.httpx.stream",
        lambda *args, **kwargs: StreamContext(next(responses)),
    )
    monkeypatch.setattr("src.explanation.providers.time.sleep", lambda delay: None)
    provider = OpenAICompatibleProvider(
        base_url="http://127.0.0.1:41337/v1",
        api_key="local",
        model="local",
        max_busy_retries=1,
    )
    assert provider.generate(system="system", prompt="prompt").startswith('{"headline"')
