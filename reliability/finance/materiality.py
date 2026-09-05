"""Materiality scoring — deciding what deserves an investigation.

A controller does not care that office supplies moved $1,000 -> $1,100 while
revenue moved $2M. Scoring every movement the same way is the single fastest
way to make an agent look unserious, and it burns tool calls on noise.

    M = w_A*A + w_P*P + w_H*H + w_C*C

    A  normalised absolute dollar movement
    P  percentage movement (capped, so tiny bases cannot dominate)
    H  historical abnormality — how strange is this move for THIS account
    C  contribution to the total movement of its statement section

Every component is transparent and inspectable; there is no learned model here
and there does not need to be.
"""

from statistics import mean, pstdev

from .variance import pnl

WEIGHTS = {"absolute": 0.40, "percentage": 0.15, "historical": 0.25, "contribution": 0.20}
PCT_CAP = 100.0          # a 4000% move on a tiny account is not 40x more interesting
BANDS = ((0.70, "high"), (0.40, "medium"), (0.0, "low"))


def _section_totals(ds, period):
    out = {}
    for t in ds.txns(period):
        out[t["statement_section"]] = out.get(t["statement_section"], 0.0) + t["amount"]
    return out


def account_series(ds, account, upto):
    vals = []
    for p in ds.periods:
        if p >= upto:
            break
        s = sum(t["amount"] for t in ds.txns(p) if t["gl_account"] == account)
        vals.append(s)
    return vals


def rank_material_variances(ds, p0, p1, min_abs=5_000):
    """Score and rank every GL account's movement between two periods."""
    cur, prior, names, sections = {}, {}, {}, {}
    for p, bucket in ((p0, prior), (p1, cur)):
        for t in ds.txns(p):
            a = t["gl_account"]
            bucket[a] = bucket.get(a, 0.0) + t["amount"]
            names[a] = t["gl_account_name"]
            sections[a] = t["statement_section"]

    accounts = set(cur) | set(prior)
    raw = []
    for a in accounts:
        c, pr = cur.get(a, 0.0), prior.get(a, 0.0)
        raw.append({"gl_account": a, "gl_account_name": names.get(a, a),
                    "statement_section": sections.get(a, ""),
                    "prior": round(pr, 2), "current": round(c, 2),
                    "variance": round(c - pr, 2),
                    "variance_pct": round((c - pr) / pr * 100, 2) if pr else None})

    max_abs = max((abs(r["variance"]) for r in raw), default=1.0) or 1.0
    sec_move = {}
    t0, t1 = _section_totals(ds, p0), _section_totals(ds, p1)
    for s in set(t0) | set(t1):
        sec_move[s] = abs(t1.get(s, 0.0) - t0.get(s, 0.0)) or 1.0

    out = []
    for r in raw:
        if abs(r["variance"]) < min_abs:
            continue
        A = abs(r["variance"]) / max_abs
        P = min(abs(r["variance_pct"] or 0.0), PCT_CAP) / PCT_CAP
        hist = account_series(ds, r["gl_account"], p1)
        if len(hist) >= 6:
            mu, sd = mean(hist), pstdev(hist)
            z = abs(r["current"] - mu) / sd if sd else 0.0
        else:
            z = 0.0
        H = min(z / 4.0, 1.0)
        C = min(abs(r["variance"]) / sec_move.get(r["statement_section"], 1.0), 1.0)

        score = (WEIGHTS["absolute"] * A + WEIGHTS["percentage"] * P
                 + WEIGHTS["historical"] * H + WEIGHTS["contribution"] * C)
        band = next(label for cut, label in BANDS if score >= cut)
        r.update({
            "materiality_score": round(score, 3),
            "materiality": band,
            "components": {"absolute": round(A, 3), "percentage": round(P, 3),
                           "historical": round(H, 3), "contribution": round(C, 3)},
            "historical_z": round(z, 2),
        })
        out.append(r)

    return sorted(out, key=lambda r: -r["materiality_score"])


def investigation_queue(ds, p0, p1, limit=4):
    """The accounts an analyst would actually open, highest value first."""
    ranked = rank_material_variances(ds, p0, p1)
    return [r for r in ranked if r["materiality"] in ("high", "medium")][:limit]
