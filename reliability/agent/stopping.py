"""When is an investigation finished?

Without an explicit rule an agent either stops at the account level -- "revenue
went up 18%", the exact failure the brief calls out -- or drills forever and
burns the budget. Both are visible in a trace, so both are fixable.

An investigation is sufficient when the drivers found actually explain the
movement, and each one is backed by transactions.
"""

TOP_DRIVER_COVERAGE = 0.70      # one dimension explains most of the move
TOP3_COVERAGE = 0.60            # or three named drivers do
MAX_DEPTH = 4
MAX_TOOL_CALLS = 24


def coverage(decomposition):
    """Share of the movement explained by same-direction movers."""
    total = decomposition.get("total_change") or 0.0
    if not total:
        return 0.0, 0.0
    movers = [r for r in decomposition["top"] if (r["change"] > 0) == (total > 0)]
    top1 = movers[0]["change"] / total if movers else 0.0
    top3 = sum(r["change"] for r in movers[:3]) / total if movers else 0.0
    return round(top1, 4), round(top3, 4)


def evaluate(state):
    """Decide whether to keep digging. Returns (stop, reason)."""
    if state["tool_calls"] >= MAX_TOOL_CALLS:
        return True, f"tool-call budget reached ({MAX_TOOL_CALLS})"
    if state["depth"] >= MAX_DEPTH:
        return True, f"maximum investigation depth reached ({MAX_DEPTH})"

    best = state.get("best_decomposition")
    if not best:
        return False, "no decomposition yet — cannot explain the movement"

    top1, top3 = coverage(best)
    if not state.get("has_transaction_evidence"):
        return False, "drivers identified but not yet traced to transactions"
    if top1 >= TOP_DRIVER_COVERAGE:
        return True, (f"top driver explains {top1:.0%} of the movement "
                      f"(threshold {TOP_DRIVER_COVERAGE:.0%}), evidence retrieved")
    if top3 >= TOP3_COVERAGE:
        return True, (f"top three drivers explain {top3:.0%} of the movement "
                      f"(threshold {TOP3_COVERAGE:.0%}), evidence retrieved")
    return False, (f"drivers explain only {max(top1, top3):.0%} of the movement — "
                   "insufficient, investigate another dimension")
