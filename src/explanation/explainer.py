"""Generate LLM prose and reject facts that are not in deterministic evidence."""

import json
import re
from decimal import Decimal
from time import perf_counter
from uuid import uuid4

from pydantic import ValidationError

from src.agent import AccountInvestigation
from src.evidence import ClaimLineage
from src.observability import NullTraceObserver, TraceEvent, TraceObserver

from .models import ExplanationDraft, GroundedExplanation
from .providers import ExplanationProvider

SYSTEM_PROMPT = """You explain financial variances using only the supplied evidence packet.
Return one JSON object with headline, summary, and claim_ids. Every factual statement must be
supported by the cited claim IDs. Do not calculate, estimate, infer causes, or introduce numbers
that are absent from the packet. If evidence is incomplete, say so explicitly."""


class UngroundedExplanationError(ValueError):
    pass


def _number_tokens(text: str) -> set[str]:
    tokens = re.findall(r"(?<![A-Za-z])[-+]?\$?\d[\d,]*(?:\.\d+)?%?", text)
    normalized = set()
    for token in tokens:
        value = token.replace("$", "").replace(",", "").lstrip("+")
        normalized.add(value)
    return normalized


def build_evidence_packet(
    investigation: AccountInvestigation, claims: list[ClaimLineage]
) -> dict:
    variance = investigation.variance
    return {
        "account": variance.account,
        "periods": {
            "prior": investigation.prior_period.isoformat(),
            "current": investigation.current_period.isoformat(),
        },
        "variance": {
            "prior_amount": str(variance.prior_amount),
            "current_amount": str(variance.current_amount),
            "amount": f"{variance.variance:+}",
            "absolute_amount": str(abs(variance.variance)),
            "percentage": str(variance.variance_pct) if variance.variance_pct is not None else None,
            "absolute_percentage": (
                str(abs(variance.variance_pct)) if variance.variance_pct is not None else "not-applicable"
            ),
            "percentage_display": (
                f"{abs(variance.variance_pct)}%" if variance.variance_pct is not None else "not-applicable"
            ),
        },
        "coverage_percentage": str(investigation.stop_decision.coverage * Decimal("100")),
        "evidence_sufficient": investigation.stop_decision.evidence_sufficient,
        "claims": [
            {
                "claim_id": claim.claim_id,
                "dimension": claim.dimension,
                "driver": claim.driver,
                "prior_amount": str(claim.calculation.prior_amount),
                "current_amount": str(claim.calculation.current_amount),
                "variance": f"{claim.calculation.variance:+}",
                "contribution_percentage": (
                    str(claim.calculation.contribution_pct)
                    if claim.calculation.contribution_pct is not None
                    else None
                ),
                "transaction_ids": [tx.transaction_id for tx in claim.transactions],
                "transaction_count": len(claim.transactions),
            }
            for claim in claims
        ],
        "business_context": [context.model_dump(mode="json") for context in investigation.business_context],
    }


class EvidenceBoundExplainer:
    def __init__(self, provider: ExplanationProvider, observer: TraceObserver | None = None):
        self.provider = provider
        self.observer = observer or NullTraceObserver()

    def explain(
        self, investigation: AccountInvestigation, claims: list[ClaimLineage]
    ) -> GroundedExplanation:
        if not claims:
            raise UngroundedExplanationError("cannot explain an account without evidence claims")
        packet = build_evidence_packet(investigation, claims)
        run_id = f"explanation-{uuid4()}"
        self.observer.start_run(run_id)
        started = perf_counter()
        try:
            raw = self.provider.generate(system=SYSTEM_PROMPT, prompt=json.dumps(packet))
            draft = ExplanationDraft.model_validate_json(raw)
            self._validate_grounding(draft, packet)
            result = GroundedExplanation(
                **draft.model_dump(),
                account=investigation.variance.account,
                provider=self.provider.name,
            )
            self.observer.record(
                TraceEvent(
                    step_type="llm_call",
                    label="Generate evidence-bound explanation",
                    input_summary=f"{len(claims)} verified claims",
                    output_summary=f"{len(draft.claim_ids)} cited claims; grounding passed",
                    duration_ms=int((perf_counter() - started) * 1000),
                )
            )
            self.observer.finish_run("success")
            return result
        except Exception as exc:
            self.observer.record(
                TraceEvent(
                    step_type="error",
                    label="Explanation rejected",
                    output_summary=f"{type(exc).__name__}: {exc}",
                    duration_ms=int((perf_counter() - started) * 1000),
                    status="error",
                )
            )
            self.observer.finish_run("error")
            raise

    @staticmethod
    def _validate_grounding(draft: ExplanationDraft, packet: dict) -> None:
        known_ids = {claim["claim_id"] for claim in packet["claims"]}
        cited_ids = set(draft.claim_ids)
        unknown = cited_ids - known_ids
        if unknown:
            raise UngroundedExplanationError(
                f"explanation cites unknown claims: {', '.join(sorted(unknown))}"
            )
        if not cited_ids:
            raise UngroundedExplanationError("explanation must cite at least one claim")

        allowed_text = json.dumps(packet, sort_keys=True)
        allowed_numbers = _number_tokens(allowed_text)
        used_numbers = _number_tokens(f"{draft.headline} {draft.summary}")
        unsupported = used_numbers - allowed_numbers
        if unsupported:
            raise UngroundedExplanationError(
                f"explanation contains unsupported numbers: {', '.join(sorted(unsupported))}"
            )
