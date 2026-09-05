"""Contracts between the benchmark and the system under test.

Two shapes matter:

  Case        one scenario with machine-checkable ground truth
  RunResult   what any Ledger Lens implementation must return for a period

Your teammate's investigator satisfies the benchmark by producing a RunResult.
The reference implementation in src/agent/reference.py does the same. The
evaluator does not care which one it is talking to.
"""

CASE_FIELDS = {
    "id": str, "category": str, "title": str, "period": str, "prior_period": str,
}
CATEGORIES = ("normal", "ambiguous", "data_quality", "adversarial", "memory")

GROUND_TRUTH_DEFAULTS = {
    "expected_material_variances": [],     # account names that MUST be investigated
    "expected_immaterial": [],             # account names that must NOT be top-ranked
    "expected_top_drivers": {},            # {account: [driver names]} that must be found
    "expected_unexplained_amount": None,   # {account: amount} or None
    "expected_unexplained_min_share": None,  # e.g. 0.4 -> must report >=40% unexplained
    "expected_data_quality_flags": [],     # gate codes that MUST appear
    "expected_no_data_quality_flags": [],  # gate codes that must NOT appear
    "expected_memory_usage": [],           # prior ids that must be applied
    "expected_memory_rejected": [],        # prior ids that must NOT be applied
    "forbidden_claims": [],                # plain phrases that must not appear
    "forbidden_patterns": [],              # regexes that must not appear
    "required_patterns": [],               # regexes that MUST appear in narrative
    "acceptable_confidence": ["high", "medium", "low"],
    "expected_abstention": False,          # must the system decline to attribute?
    "expected_abstention_scope": [],       # accounts on which abstention is required
    "max_tool_calls": 30,
    "notes": "",
}

RUN_RESULT_FIELDS = (
    "period", "prior_period",
    "data_quality",          # {passed, flags[], blocked_accounts[], data_confidence}
    "material_variances",    # [{account, variance, variance_pct, materiality, score, reason}]
    "not_investigated",      # [{account, reason}]   -- "why did you NOT investigate that"
    "claims",                # [claim dicts, each with kind/verified/transaction_ids]
    "narrative",             # the memo text with [claim_id] citations
    "confidence",            # uncertainty.assemble() output
    "unexplained",           # {account: amount}
    "memory_used",           # [prior ids applied]
    "memory_rejected",       # [{id, reason}] priors considered and rejected (stale/contradicted)
    "contradictions",        # [{description, sources[]}]
    "abstained",             # bool
    "abstained_scope",       # [accounts]
    "trace",                 # {tool_calls, events...}
)


# A multi-run case carries a sequence.json:
#   {"steps": [{"period", "prior_period", "feedback": [ops...], "ground_truth": {...}}, ...]}
# Steps share one memory file. Feedback ops are applied BEFORE the step runs:
#   {"op": "add", "type", "scope", "statement", "implication", "confidence",
#    "source_type", "valid_from", "valid_until", "expectation"}
#   {"op": "confirm" | "reject" | "contest", "id", "note"}
#   {"op": "correct", "id", "statement", "implication", "note"}
FEEDBACK_OPS = ("add", "confirm", "reject", "contest", "correct")


def new_sequence(id, category, title, steps, **case_gt):
    """A case whose ground truth is checked at each step of a run sequence."""
    c = new_case(id, category, title, steps[-1]["period"], steps[-1]["prior_period"], **case_gt)
    out = []
    for st in steps:
        g = dict(GROUND_TRUTH_DEFAULTS); g.update(st.get("ground_truth") or {})
        out.append({"period": st["period"], "prior_period": st["prior_period"],
                    "feedback": st.get("feedback") or [], "ground_truth": g,
                    "score": st.get("score", True)})
    c["sequence"] = {"steps": out}
    return c


def new_case(id, category, title, period, prior_period, **gt):
    assert category in CATEGORIES, category
    g = dict(GROUND_TRUTH_DEFAULTS)
    g.update(gt)
    return {"id": id, "category": category, "title": title,
            "period": period, "prior_period": prior_period, "ground_truth": g}


def validate_result(r):
    missing = [f for f in RUN_RESULT_FIELDS if f not in r]
    return missing
