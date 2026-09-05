"""Pluggable LLM providers for explanation generation."""

import json
import os
import time
from typing import Protocol

import httpx


class LLMResponseError(ValueError):
    """A safe diagnostic for malformed model responses (never includes credentials)."""


def _extract_json_object(text: str) -> str | None:
    """Return the first complete JSON object embedded in model prose or fences."""
    decoder = json.JSONDecoder()
    for index, character in enumerate(text):
        if character != "{":
            continue
        try:
            value, end = decoder.raw_decode(text[index:])
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            return text[index : index + end]
    return None


def _wrap_grounded_prose(text: str, prompt: str) -> str | None:
    """Adapt raw local-model prose to the evidence-bound explanation contract."""
    summary = text.strip()
    if not summary:
        return None
    try:
        packet = json.loads(prompt)
        account = packet["account"]
        claim_ids = [claim["claim_id"] for claim in packet["claims"]]
    except (json.JSONDecodeError, KeyError, TypeError):
        return None
    if not claim_ids:
        return None
    return json.dumps(
        {
            "headline": f"{account} variance",
            "summary": summary,
            # Raw local APIs cannot enforce a citation response schema. Bind the
            # prose conservatively to every verified claim supplied to the model;
            # the explainer still rejects any unsupported numeric statement.
            "claim_ids": claim_ids,
        }
    )


def _compact_evidence_prompt(prompt: str) -> str:
    """Reduce a verified evidence packet to the facts needed for concise prose."""
    try:
        packet = json.loads(prompt)
        variance = packet["variance"]
        drivers = "; ".join(
            f"{claim['driver']} {claim['variance']} ({claim['transaction_count']} transactions)"
            for claim in packet["claims"]
        )
        disclosures = "; ".join(packet.get("required_disclosures", []))
        coverage_display = packet.get(
            "coverage_percentage_display", f"{packet['coverage_percentage']}%"
        )
        return (
            f"Account: {packet['account']}. Prior: {variance['prior_amount']}. "
            f"Current: {variance['current_amount']}. Variance: {variance['amount']} "
            f"({variance['percentage_display']}). Coverage: {coverage_display}. "
            f"Evidence sufficient: {packet['evidence_sufficient']}. "
            f"Verified drivers: {drivers}. Required disclosures: {disclosures}. "
            "Include every required disclosure verbatim."
        )
    except (json.JSONDecodeError, KeyError, TypeError):
        return prompt


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
        timeout: float = 180,
        max_busy_retries: int = 5,
        max_tokens: int = 768,
        disable_reasoning: bool = True,
    ):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.timeout = timeout
        self.max_busy_retries = max_busy_retries
        self.max_tokens = max_tokens
        self.disable_reasoning = disable_reasoning

    @classmethod
    def from_env(cls) -> "OpenAICompatibleProvider | None":
        base_url = os.getenv("LEDGER_LENS_LLM_BASE_URL")
        api_key = os.getenv("LEDGER_LENS_LLM_API_KEY")
        model = os.getenv("LEDGER_LENS_LLM_MODEL")
        if not all((base_url, api_key, model)):
            return None
        timeout = float(os.getenv("LEDGER_LENS_LLM_TIMEOUT", "180"))
        max_tokens = int(os.getenv("LEDGER_LENS_LLM_MAX_TOKENS", "768"))
        disable_reasoning = os.getenv("LEDGER_LENS_LLM_DISABLE_REASONING", "true").lower() in {
            "1",
            "true",
            "yes",
        }
        return cls(
            base_url=base_url,
            api_key=api_key,
            model=model,
            timeout=timeout,
            max_tokens=max_tokens,
            disable_reasoning=disable_reasoning,
        )

    def generate(self, *, system: str, prompt: str) -> str:
        system_content = system
        request_prompt = prompt
        if self.disable_reasoning:
            system_content = (
                "/no_think\nWrite one concise financial variance explanation using only "
                "facts and numbers present in the supplied evidence packet. Do not calculate, "
                "infer causes, or add facts. Return plain prose only."
            )
            request_prompt = _compact_evidence_prompt(prompt)
        for attempt in range(self.max_busy_retries + 1):
            retry_delay = None
            with httpx.stream(
                "POST",
                f"{self.base_url}/chat/completions",
                headers={"Authorization": f"Bearer {self.api_key}"},
                json={
                    "model": self.model,
                    "messages": [
                        {
                            "role": "system",
                            "content": system_content,
                        },
                        {"role": "user", "content": request_prompt},
                    ],
                    "temperature": 0,
                    "max_tokens": self.max_tokens,
                    # GIDE's local endpoint emits tokens reliably as SSE while a
                    # long non-streamed request may be disconnected by its server.
                    "stream": True,
                },
                timeout=self.timeout,
            ) as response:
                if response.status_code == 429 and attempt < self.max_busy_retries:
                    retry_after = response.headers.get("Retry-After", "1")
                    try:
                        retry_delay = float(retry_after)
                    except ValueError:
                        retry_delay = 1
                else:
                    response.raise_for_status()
                    content_type = response.headers.get("content-type", "")
                    if "text/event-stream" in content_type:
                        lines = (
                            response.iter_lines()
                            if hasattr(response, "iter_lines")
                            else getattr(response, "text", "").splitlines()
                        )
                        payload = self._stream_payload(lines)
                    else:
                        read = getattr(response, "read", None)
                        if callable(read):
                            read()
                        payload = response.json()
                    return self._completion_content(payload, prompt)
            if retry_delay is not None:
                time.sleep(min(max(retry_delay, 0.1), 5))
        raise LLMResponseError("model remained busy after retry budget was exhausted")

    @staticmethod
    def _stream_payload(lines) -> dict:
        content_parts: list[str] = []
        reasoning_parts: list[str] = []
        finish_reason = None
        for line in lines:
            if not line.startswith("data:"):
                continue
            data = line[5:].strip()
            if not data or data == "[DONE]":
                continue
            try:
                chunk = json.loads(data)
                choice = chunk["choices"][0]
                delta = choice.get("delta", {})
            except (json.JSONDecodeError, KeyError, IndexError, TypeError) as exc:
                raise LLMResponseError("model returned a malformed streaming chunk") from exc
            if isinstance(delta.get("content"), str):
                content_parts.append(delta["content"])
            reasoning = delta.get("reasoning_content", delta.get("reasoning"))
            if isinstance(reasoning, str):
                reasoning_parts.append(reasoning)
            finish_reason = choice.get("finish_reason") or finish_reason
        return {
            "choices": [
                {
                    "finish_reason": finish_reason,
                    "message": {
                        "content": "".join(content_parts),
                        "reasoning_content": "".join(reasoning_parts),
                    },
                }
            ]
        }

    @staticmethod
    def _completion_content(payload: dict, prompt: str) -> str:
        try:
            choice = payload["choices"][0]
            message = choice["message"]
        except (KeyError, IndexError, TypeError) as exc:
            raise LLMResponseError("chat completion did not contain a message choice") from exc

        # Reasoning models may expose their work separately and occasionally place
        # the requested object there when the final content field is empty.
        candidates = [
            message.get("content"),
            message.get("reasoning_content"),
            message.get("reasoning"),
        ]
        for candidate in candidates:
            if not isinstance(candidate, str):
                continue
            extracted = _extract_json_object(candidate)
            if extracted is not None:
                return extracted

        content = message.get("content")
        if isinstance(content, str):
            wrapped = _wrap_grounded_prose(content, prompt)
            if wrapped is not None:
                return wrapped

        finish_reason = choice.get("finish_reason", "unknown")
        field_lengths = {
            key: len(value)
            for key, value in message.items()
            if key in {"content", "reasoning_content", "reasoning"} and isinstance(value, str)
        }
        raise LLMResponseError(
            "model returned no JSON object "
            f"(finish_reason={finish_reason}; text_field_lengths={field_lengths})"
        )


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
        disclosures = packet.get("required_disclosures", [])
        if disclosures:
            summary = " ".join([summary, *[f"{item}." for item in disclosures]])
        return json.dumps(
            {
                "headline": f"{account} {direction}",
                "summary": summary,
                "claim_ids": [claim["claim_id"] for claim in claims],
            }
        )
