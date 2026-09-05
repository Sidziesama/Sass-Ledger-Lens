"""Pluggable LLM providers for explanation generation."""

import json
import os
from typing import Protocol

import httpx


class ExplanationProvider(Protocol):
    name: str

    def generate(self, *, system: str, prompt: str) -> str: ...


class OpenAICompatibleProvider:
    """Call a standard chat-completions endpoint, including GIDE's local API."""

    name = "openai-compatible"

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        model: str,
        timeout: float = 30,
    ):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.timeout = timeout

    @classmethod
    def from_env(cls) -> "OpenAICompatibleProvider | None":
        base_url = os.getenv("LEDGER_LENS_LLM_BASE_URL")
        api_key = os.getenv("LEDGER_LENS_LLM_API_KEY")
        model = os.getenv("LEDGER_LENS_LLM_MODEL")
        if not all((base_url, api_key, model)):
            return None
        return cls(base_url=base_url, api_key=api_key, model=model)

    def generate(self, *, system: str, prompt: str) -> str:
        response = httpx.post(
            f"{self.base_url}/chat/completions",
            headers={"Authorization": f"Bearer {self.api_key}"},
            json={
                "model": self.model,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": prompt},
                ],
                "temperature": 0,
                "response_format": {"type": "json_object"},
            },
            timeout=self.timeout,
        )
        response.raise_for_status()
        payload = response.json()
        return payload["choices"][0]["message"]["content"]


class TemplateExplanationProvider:
    """Offline fallback that uses only the supplied evidence packet."""

    name = "deterministic-template"

    def generate(self, *, system: str, prompt: str) -> str:
        packet = json.loads(prompt)
        account = packet["account"]
        direction = "increased" if packet["variance"]["amount"].startswith("+") else "decreased"
        claims = packet["claims"]
        lead = claims[0]
        summary = (
            f"{account} {direction} by {packet['variance']['absolute_amount']} "
            f"({packet['variance']['percentage_display']}). "
            f"The largest identified driver was {lead['driver']}, contributing "
            f"{lead['variance']} and supported by {len(lead['transaction_ids'])} transactions."
        )
        return json.dumps(
            {
                "headline": f"{account} {direction}",
                "summary": summary,
                "claim_ids": [claim["claim_id"] for claim in claims],
            }
        )
