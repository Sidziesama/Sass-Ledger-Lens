"""The memo. A model may write it; the engine decides whether it ships.

Inputs are the verified claims only. The model is asked to write four to seven
plain sentences citing claim ids, and its draft goes through the same linter as
everything else: causal verbs without a causal claim, false precision, and any
figure that does not trace to a claim. A draft that fails is not patched or
softened -- it is replaced by the templated memo, and the failure is recorded.

That record is the point. Over a benchmark it becomes a measured rejection rate
for the model step, which is the honest answer to "how often would this thing
have hallucinated if you let it".
"""

import re

from ..policy.language import lint
from .prompts import NARRATIVE_SYSTEM, NARRATIVE_USER


def _headline(result):
    lines = []
    for m in result["material_variances"]:
        pct = f" ({m['variance_pct']:+.1f}%)" if m.get("variance_pct") is not None else ""
        lines.append(f"- {m['account']}: {m['prior']:,.0f} -> {m['current']:,.0f}, "
                     f"{m['variance']:+,.0f}{pct}, materiality {m['materiality']}")
    return "\n".join(lines) or "- no material movements"


def _naive(result):
    """What a delta-only tool would have said. Shown to the model as a warning,
    and kept in the artifact so the demo can contrast it."""
    mv = result["material_variances"]
    if not mv:
        return "Nothing to report."
    top = mv[0]
    pct = f" ({top['variance_pct']:+.1f}%)" if top.get("variance_pct") is not None else ""
    drv = next((c for c in result["claims"] if c.get("kind") == "attribution" and c.get("drivers")
                and (c.get("account") or "") == top["account"]), None)
    tail = f", primarily driven by {', '.join(drv['drivers'][:3])}" if drv else ""
    return f"{top['account']} {'increased' if top['variance'] > 0 else 'decreased'} {abs(top['variance']):,.0f}{pct}{tail}."


def _citable(claims):
    return "\n".join(f"{c['claim_id']}: {c['claim']}" for c in claims if c.get("verified"))


# sentence boundary: end punctuation + space, unless what follows is a citation
_SENT = re.compile(r"(?<=[.!?])\s+(?!\[claim_)")
_MD = re.compile(r"(\*\*|__|^#{1,6}\s+|^\s*[-*•]\s+|`)", re.M)


def _strip_markdown(text):
    """Formatting is not content. Asterisks, headings and bullets are removed
    before linting; words and numbers are never touched."""
    t = _MD.sub("", text)
    t = re.sub(r"^\s*(finance memo|memo)\s*:?\s*$", "", t, flags=re.I | re.M)
    return re.sub(r"\s+", " ", t).strip()


def write_memo(llm, result, priors_text="(none)"):
    """Return {text, source, violations, draft}. `text` is always safe to show."""
    template = result["narrative"]
    verified = [c for c in result["claims"] if c.get("verified")]
    if llm is None or not llm.available or not verified:
        return {"text": template, "source": "template", "violations": [], "draft": None}

    prompt = NARRATIVE_USER.format(period=result["period"], prior_period=result["prior_period"],
                                   claims=_citable(verified))
    draft, _ = llm.chat(NARRATIVE_SYSTEM, [{"role": "user", "content": prompt}], max_tokens=400)
    if not draft:
        return {"text": template, "source": "template", "violations": [{"type": "MODEL_UNAVAILABLE"}],
                "draft": None}
    draft = _strip_markdown(draft)

    causal_ids = [c["claim_id"] for c in verified if c.get("kind") == "causal"]
    ids = {c["claim_id"] for c in verified}

    # A sentence that is a verbatim quote of a verified claim is traceable by
    # construction: resolve its citation rather than reject it. Anything that
    # is not an exact quote must carry its own [claim_id]. Counted, never reworded.
    def _norm(t):
        t = re.sub(r"\[claim_\d+\]", "", t)
        return re.sub(r"[^a-z0-9%$.]+", " ", t.lower()).strip()
    by_text = {_norm(c["claim"]): c["claim_id"] for c in verified}
    resolved, out = 0, []
    for sent in _SENT.split(draft):
        if sent.strip() and not (set(re.findall(r"\[(claim_\d+)\]", sent)) & ids):
            cid = by_text.get(_norm(sent))
            if cid:
                sent = f"{sent.strip()} [{cid}]"; resolved += 1
        out.append(sent)
    draft = " ".join(out)

    violations = lint(draft, verified, causal_ids)
    for sent in _SENT.split(draft):
        if sent.strip() and not (set(re.findall(r"\[(claim_\d+)\]", sent)) & ids):
            violations.append({"type": "UNCITED_SENTENCE", "sentence": sent.strip()[:160]})
    if violations:
        return {"text": template, "source": "template (model draft rejected)",
                "violations": violations, "draft": draft, "resolved_quotes": resolved}
    return {"text": draft, "source": f"model:{llm.describe()}", "violations": [], "draft": draft,
            "resolved_quotes": resolved}
