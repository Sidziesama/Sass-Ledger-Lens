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
        json_mode: bool = True,
    ):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.timeout = timeout
        self.json_mode = json_mode

    @classmethod
    def from_env(cls) -> "OpenAICompatibleProvider | None":
        base_url = os.getenv("LEDGER_LENS_LLM_BASE_URL")
        api_key = os.getenv("LEDGER_LENS_LLM_API_KEY")
        model = os.getenv("LEDGER_LENS_LLM_MODEL")
        if not all((base_url, api_key, model)):
            return None
        return cls(
            base_url=base_url,
            api_key=api_key,
            model=model,
            timeout=float(os.getenv("LEDGER_LENS_LLM_TIMEOUT", "120")),
            json_mode=os.getenv("LEDGER_LENS_LLM_JSON_MODE", "true").lower() == "true",
        )

    def generate(self, *, system: str, prompt: str) -> str:
        body = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0,
            "max_tokens": 1024,
        }
        if self.json_mode:
            body["response_format"] = {"type": "json_object"}
        response = httpx.post(
            f"{self.base_url}/chat/completions",
            headers={"Authorization": f"Bearer {self.api_key}"},
            json=body,
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
        statements = packet["approved_statements"]
        return json.dumps(
            {
                "headline": packet["approved_headlines"][0],
                "summary": " ".join(item["text"] for item in statements),
                "claim_ids": [claim["claim_id"] for claim in packet["claims"]],
            }
        )
