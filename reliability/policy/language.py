"""Language policy linter.

The words must carry exactly as much certainty as the evidence. This runs over
the final narrative and fails it on three things:

  1. Causal verbs ("caused", "because of", "resulted from", "led to") with no
     verified causal claim behind the sentence. Attribution language ("driven
     by", "concentrated in", "attributable to") is allowed: it describes where
     the money moved, not why.
  2. Numbers that do not appear in any verified claim. Every dollar figure and
     percentage in the memo must trace to a claim the engine produced. This is
     the hallucination tripwire.
  3. False precision and nonsense: "93.72% confident", "infinity percent".

The linter is deterministic. A narrative that fails is rewritten or replaced
with the templated fallback; it is never shown as-is.
"""

import re

CAUSAL = re.compile(
    r"\b(caused|causes|causing|because of|resulted from|as a result of|led to|leads to|"
    r"owing to|thanks to|attributable to the decision|in response to|"
    r"triggered by|stems from|stemming from)\b", re.I)
FALSE_PRECISION = re.compile(r"\b\d{2}\.\d{2,}\s?%\s*(confident|confidence|certain)", re.I)
NONSENSE = re.compile(r"\b(infinit(y|e|ely)|inf%|nan%|undefined%)\b", re.I)
# A figure may end a sentence ("... of $84,000.") -- a trailing period followed by
# a non-digit must not make the regex backtrack to a shorter, wrong number.
NUMBER = re.compile(r"(?<![\w.])[-+]?\$?\s?\d[\d,]*(?:\.\d+)?\s?(?:%|k|K|m|M|bps|pp|pts)?(?![\w]|\.\d)")


def _to_number(tok):
    s = tok.strip().rstrip(",").replace("$", "").replace(",", "").replace(" ", "")
    mult = 1.0
    unit = None
    for suf, mu in (("bps", 1), ("pp", 1), ("pts", 1), ("%", 1), ("k", 1e3), ("K", 1e3),
                    ("m", 1e6), ("M", 1e6)):
        if s.endswith(suf):
            unit = suf if suf in ("bps", "pp", "pts", "%") else None
            s = s[: -len(suf)]
            mult = mu
            break
    try:
        return float(s) * mult, unit
    except ValueError:
        return None, None


def _claim_numbers(claims):
    nums = set()
    for c in claims:
        for k in ("variance", "driver_amount", "contribution_pct", "prior", "current",
                  "change", "change_pct", "amount", "expected", "surprise", "surprise_pct",
                  "excess", "avg_monthly_revenue", "annualised_run_rate_lost",
                  "total_change_bps", "mix_bps", "rate_bps", "deterioration_days",
                  "avg_days_late_recent", "avg_days_late_prior", "gap", "count", "members"):
            v = c.get(k) if isinstance(c, dict) else getattr(c, k, None)
            if isinstance(v, (int, float)):
                nums.add(round(float(v), 2))
        for v in (c.get("numbers") or []) if isinstance(c, dict) else []:
            nums.add(round(float(v), 2))
    return nums


def _matches(value, unit, pool, tol=0.02):
    """A narrative number matches a claim number if within 2% or rounding.

    Signs are compared on magnitude: the memo writes "decreased by $50,000"
    while the engine stores -50000. The direction word is the sign.
    """
    value = abs(value)
    for n in pool:
        n = abs(n)
        if n == 0:
            if abs(value) < 0.5:
                return True
            continue
        if abs(value - n) <= max(abs(n) * tol, 0.5):
            return True
        # allow K/M rounding of dollars: 180K vs 179,812
        if abs(value - n) <= max(abs(n) * 0.06, 0.5) and (unit is None and value >= 1000):
            return True
        # allow rounded percentages: 64% vs 63.89
        if unit == "%" and abs(value - n) <= 0.6:
            return True
    return False


def lint(narrative, claims, causal_claim_ids=()):
    """Return list of violations. Empty list == narrative passes."""
    violations = []
    if not narrative:
        return violations
    sentences = re.split(r"(?<=[.!?])\s+", narrative.strip())
    for s in sentences:
        cited = set(re.findall(r"\[(claim_\d+)\]", s))
        if CAUSAL.search(s) and not (cited & set(causal_claim_ids)):
            violations.append({"type": "UNSUPPORTED_CAUSALITY", "sentence": s.strip(),
                               "match": CAUSAL.search(s).group(0)})
    if FALSE_PRECISION.search(narrative):
        violations.append({"type": "FALSE_PRECISION", "match": FALSE_PRECISION.search(narrative).group(0)})
    if NONSENSE.search(narrative):
        violations.append({"type": "NONSENSE_FIGURE", "match": NONSENSE.search(narrative).group(0)})

    pool = _claim_numbers(claims)
    for tok in NUMBER.findall(narrative):
        raw = tok.strip()
        if re.fullmatch(r"\d{4}(-\d{2})?", raw) or raw in ("1", "2", "3", "one"):
            continue                                    # years, periods, ordinals
        v, unit = _to_number(raw)
        if v is None or (abs(v) < 10 and unit is None):
            continue                                    # small counts like "3 customers"
        if not _matches(v, unit, pool):
            violations.append({"type": "UNGROUNDED_NUMBER", "match": raw})
    return violations
