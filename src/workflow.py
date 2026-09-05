"""One run lifecycle for investigation, explanation, validation, and telemetry."""

from dataclasses import dataclass
from decimal import Decimal
from typing import Any
from uuid import uuid4

import httpx
from pydantic import ValidationError

from src.agent import FinancialTools, Investigator
from src.evidence import build_claim_lineage
from src.explanation import (
    EvidenceBoundExplainer,
    TemplateExplanationProvider,
    UngroundedExplanationError,
)
from src.observability import InMemoryTraceObserver, TraceEvent
from src.observability.tracing import RunStepObserver


def reconciliation_issues(account, summaries, transactions):
    issues = []
    for period in (account.prior_period, account.current_period):
        rows = [
            r for r in summaries if r.account == account.variance.account and r.period == period
        ]
        detail = [
            t for t in transactions if t.account == account.variance.account and t.period == period
        ]
        if not rows:
            issues.append(f"missing_summary:{period}")
            continue
        if not detail:
            issues.append(f"missing_transactions:{period}")
            continue
        currencies = {r.currency for r in rows} | {t.currency for t in detail}
        if len(currencies) != 1:
            issues.append(f"currency_mismatch:{period}")
            continue
        residual = sum((r.amount for r in rows), Decimal(0)) - sum(
            (t.amount for t in detail), Decimal(0)
        )
        if residual:
            issues.append(f"unreconciled:{period}:residual={residual}")
    return issues


def build_artifact(
    result, transactions, events, provider=None, *, observer=None, summaries=None
) -> dict[str, Any]:
    explanation_provider = provider or TemplateExplanationProvider()
    accounts = []
    for account in result.accounts:
        issues = (
            reconciliation_issues(account, summaries, transactions) if summaries is not None else []
        )
        claims = build_claim_lineage(account, transactions) if not issues else []
        explanation = None
        explanation_warning = None
        if claims:
            try:
                explanation = EvidenceBoundExplainer(explanation_provider, observer).explain(
                    account, claims
                )
            except (
                httpx.HTTPError,
                ValidationError,
                UngroundedExplanationError,
                ValueError,
                KeyError,
                IndexError,
                TypeError,
            ) as exc:
                explanation_warning = f"Configured explanation failed ({type(exc).__name__}); using verified template."
                explanation = EvidenceBoundExplainer(
                    TemplateExplanationProvider(), observer
                ).explain(account, claims)
        status = (
            "blocked" if issues else "complete" if account.stop_decision.should_stop else "partial"
        )
        if observer:
            observer.record(
                TraceEvent(
                    step_type="validation",
                    label="Validate account result",
                    output_summary=f"status={status}; issues={','.join(issues) or 'none'}",
                )
            )
        accounts.append(
            {
                "account": account.variance.account,
                "status": status,
                "reliability_issues": issues,
                "explanation_warning": explanation_warning,
                "prior_amount": str(account.variance.prior_amount),
                "current_amount": str(account.variance.current_amount),
                "variance": str(account.variance.variance),
                "variance_pct": (
                    str(account.variance.variance_pct)
                    if account.variance.variance_pct is not None
                    else None
                ),
                "investigated_dimension": account.dimension,
                "coverage": str(account.stop_decision.coverage),
                "evidence_sufficient": status == "complete",
                "stop_reason": account.stop_decision.reason,
                "drivers": [
                    {
                        "driver": driver.driver,
                        "variance": str(driver.variance),
                        "contribution_pct": (
                            str(driver.contribution_pct)
                            if driver.contribution_pct is not None
                            else None
                        ),
                        "transaction_ids": list(driver.transaction_ids),
                    }
                    for driver in account.drivers
                ],
                "claims": [claim.model_dump(mode="json") for claim in claims],
                "explanation": explanation.model_dump(mode="json") if explanation else None,
                "business_context": [
                    context.model_dump(mode="json") for context in account.business_context
                ],
            }
        )
    return {
        "run_id": result.run_id,
        "prior_period": result.prior_period.isoformat(),
        "current_period": result.current_period.isoformat(),
        "accounts": accounts,
        "trace": [event.as_prism_step() for event in events],
    }


@dataclass
class WorkflowResult:
    result: Any
    artifact: dict
    observer: Any


def run_workflow(
    summaries,
    transactions,
    prior,
    current,
    absolute,
    percentage,
    *,
    provider=None,
    observer=None,
    memory=None,
    target_coverage=Decimal("0.80"),
    max_drivers=5,
):
    if current <= prior:
        raise ValueError("current_period must be after prior_period")
    observer = observer or InMemoryTraceObserver()
    run_id = str(uuid4())
    observer.start_run(run_id)
    steps = RunStepObserver(observer)
    try:
        result = Investigator(
            FinancialTools(summaries, transactions),
            memory=memory,
            observer=steps,
            target_coverage=target_coverage,
            max_drivers=max_drivers,
        ).investigate(prior, current, absolute, percentage)
        from dataclasses import replace

        result = replace(result, run_id=run_id)
        artifact = build_artifact(
            result, transactions, observer.events, provider, observer=steps, summaries=summaries
        )
        statuses = [account["status"] for account in artifact["accounts"]]
        artifact["status"] = (
            "complete"
            if all(s == "complete" for s in statuses)
            else "blocked"
            if all(s == "blocked" for s in statuses)
            else "partial"
        )
        steps.record(
            TraceEvent(
                step_type="final_answer",
                label="Workflow completed",
                output_summary=f"status={artifact['status']}; {len(statuses)} accounts",
            )
        )
        observer.finish_run("success")
        artifact["trace"] = [event.as_prism_step() for event in observer.events]
        artifact["telemetry"] = {"status": getattr(observer, "delivery_status", "local_only")}
        if getattr(observer, "receipt", None):
            artifact["telemetry"]["receipt_id"] = observer.receipt.get("id")
        return WorkflowResult(result, artifact, observer)
    except Exception as exc:
        steps.record(
            TraceEvent(
                step_type="error",
                label="Workflow failed",
                output_summary=type(exc).__name__,
                status="error",
            )
        )
        observer.finish_run("error")
        raise
