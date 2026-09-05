"""Failure taxonomy. Every failed benchmark run is classified into exactly these.

This is what turns "the agent was wrong" into something you can fix and then
prove you fixed. It feeds the PRISM Observe -> Improve -> Prove loop directly.
"""

CLASSES = (
    "DATA_QUALITY_FAILURE",          # a data problem was missed, or narrated as business
    "ARITHMETIC_FAILURE",            # a stated figure does not reproduce from the records
    "MATERIALITY_FAILURE",           # wrong things investigated / right things ignored
    "INVESTIGATION_SELECTION_FAILURE",  # right account, wrong dimension or path
    "PREMATURE_STOPPING",            # stopped before drivers explained the movement
    "OVER_INVESTIGATION",            # burned budget on a distributed / immaterial move
    "DRIVER_ATTRIBUTION_FAILURE",    # named the wrong driver, or missed the true one
    "RECONCILIATION_FAILURE",        # summary/transaction gap not surfaced
    "UNSUPPORTED_CAUSALITY",         # correlation narrated as cause
    "HALLUCINATED_CLAIM",            # figure or fact with no deterministic origin
    "MEMORY_RETRIEVAL_FAILURE",      # relevant prior existed and was not used
    "STALE_MEMORY_FAILURE",          # expired prior was applied
    "MEMORY_OVERRELIANCE",           # prior applied without checking current evidence
    "CONTRADICTION_HANDLING_FAILURE",  # conflicting evidence silently resolved
    "CONFIDENCE_CALIBRATION_FAILURE",  # verdict outside the acceptable set
    "EVIDENCE_LINEAGE_FAILURE",      # claim cites records that do not exist / do not sum
    "ABSTENTION_FAILURE",            # answered when it should have abstained, or vice versa
    "TOOL_FAILURE",                  # a tool errored or returned garbage
)

# Which scoring checks map to which class.
CHECK_TO_CLASS = {
    "data_quality_flags": "DATA_QUALITY_FAILURE",
    "reconciliation_detected": "RECONCILIATION_FAILURE",
    "material_variances": "MATERIALITY_FAILURE",
    "top_drivers": "DRIVER_ATTRIBUTION_FAILURE",
    "forbidden_claims": "UNSUPPORTED_CAUSALITY",
    "forbidden_patterns": "HALLUCINATED_CLAIM",
    "required_patterns": "PREMATURE_STOPPING",
    "unexplained_amount": "PREMATURE_STOPPING",
    "arithmetic": "ARITHMETIC_FAILURE",
    "lineage": "EVIDENCE_LINEAGE_FAILURE",
    "confidence": "CONFIDENCE_CALIBRATION_FAILURE",
    "abstention": "ABSTENTION_FAILURE",
    "memory_used": "MEMORY_RETRIEVAL_FAILURE",
    "memory_rejected": "STALE_MEMORY_FAILURE",
    "tool_budget": "OVER_INVESTIGATION",
    "tool_error": "TOOL_FAILURE",
    "causal_lint": "UNSUPPORTED_CAUSALITY",
    "number_lint": "HALLUCINATED_CLAIM",
}


def classify(failed_checks):
    return sorted({CHECK_TO_CLASS.get(c, "TOOL_FAILURE") for c in failed_checks})
