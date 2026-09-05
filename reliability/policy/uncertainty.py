"""The uncertainty model. Four measured dimensions, one categorical verdict.

There is no single "93.7% confident" number anywhere in Ledger Lens, because no
such number could be defended. Instead:

    data          is the input trustworthy?            (from the quality gate)
    attribution   how much of the movement is explained by identified drivers?
    context       how strong is the evidence for the INTERPRETATION of drivers?
    evidence      what share of claims survived independent verification?

and a verdict of HIGH / MEDIUM / LOW derived from explicit rules that a reader
can check. Fluent prose never moves any of these.
"""

HIGH, MEDIUM, LOW = "high", "medium", "low"

# Context evidence strength by source. A reviewer-verified fact is worth far more
# than a pattern the system inferred, which is worth more than a hypothesis.
SOURCE_WEIGHT = {"user_verified": 1.0, "system_inferred": 0.6, "hypothesis": 0.25}


def attribution_confidence(variance, attributed, contradictions=0):
    """Share of the movement explained, penalised for contradictory evidence."""
    if not variance:
        return 0.0, 0.0
    explained = min(abs(attributed) / abs(variance), 1.0)
    unexplained = abs(variance) - abs(attributed) if abs(attributed) < abs(variance) else 0.0
    score = explained * (0.75 ** contradictions)
    return round(score, 3), round(unexplained, 2)


def context_confidence(priors_used, detector_findings, contradictions=0, causal_claims=0,
                       causal_supported=0):
    """How much do we trust the *interpretation*, not just the arithmetic?

    Pure attribution with no interpretation is honest but low-context; that is
    fine. What is not fine is causal language with nothing behind it, which is
    penalised hard.
    """
    parts = []
    for p in priors_used:
        parts.append(SOURCE_WEIGHT.get(p.get("source_type", "system_inferred"), 0.5)
                     * p.get("confidence", 0.5))
    for f in detector_findings:
        parts.append(f.get("confidence", 0.6))
    base = (sum(parts) / len(parts)) if parts else 0.35
    base *= (0.7 ** contradictions)
    if causal_claims:
        unsupported = causal_claims - causal_supported
        base *= (0.5 ** unsupported)
    return round(min(base, 1.0), 3)


def classify(data, attribution, context, evidence_coverage, has_blocker=False,
             unexplained_share=None, weak_context=False):
    """Explicit, inspectable rules. Returns (verdict, reasons[])."""
    reasons = []
    if has_blocker:
        reasons.append("data-quality blocker on the analysed scope")
        return LOW, reasons
    if evidence_coverage is not None and evidence_coverage < 100:
        reasons.append(f"evidence coverage {evidence_coverage:.0f}% (< 100%)")
    if data < 0.8:
        reasons.append(f"data confidence {data:.2f}")
    if attribution < 0.5:
        reasons.append(f"only {attribution:.0%} of the movement is attributed")
    if unexplained_share is not None and unexplained_share > 0.3:
        reasons.append(f"{unexplained_share:.0%} of the movement remains unexplained")
    if weak_context:
        reasons.append("interpretation rests on a contested or unverified prior")

    if data >= 0.9 and attribution >= 0.8 and (evidence_coverage or 0) >= 100 and not reasons:
        return HIGH, ["data reconciled", f"{attribution:.0%} attributed", "all claims verified"]
    if data >= 0.7 and attribution >= 0.5 and (evidence_coverage or 0) >= 90:
        return MEDIUM, reasons or ["major drivers established; interpretation or residual uncertain"]
    return LOW, reasons or ["insufficient evidence for a strong conclusion"]


def assemble(gate, variance, attributed, priors_used, detector_findings, claimset,
             contradictions=0, causal_claims=0, causal_supported=0, blocked=False,
             weak_context=False):
    attr, unexplained = attribution_confidence(variance, attributed, contradictions)
    ctx = context_confidence(priors_used, detector_findings, contradictions,
                             causal_claims, causal_supported)
    cov = claimset.evidence_coverage() if claimset else None
    share = (unexplained / abs(variance)) if variance else None
    verdict, why = classify(gate["data_confidence"], attr, ctx, cov, blocked, share, weak_context)
    return {
        "data": gate["data_confidence"],
        "attribution": attr,
        "context": ctx,
        "evidence_coverage_pct": cov,
        "unexplained_amount": unexplained,
        "unexplained_share": round(share, 3) if share is not None else None,
        "contradictions": contradictions,
        "overall": verdict,
        "reasons": why,
    }
