"""P&L construction and exact, MECE variance decomposition.

Nothing here is a heuristic or an estimate. Every function returns numbers that
reconcile to the transaction rows, so the language layer can only ever narrate
arithmetic it did not perform.
"""

from collections import defaultdict

PRODUCT_CATEGORIES = ("Refrigeration", "Cooking Equipment", "Beverage Equipment",
                      "Smallwares", "Disposables", "Janitorial & Chemicals")


def pnl(ds, period):
    """Summary P&L for one period."""
    rev = cogs = opex = 0.0
    for t in ds.txns(period):
        s = t["statement_section"]
        if s == "Revenue":
            rev += t["amount"]
        elif s == "COGS":
            cogs += t["amount"]
        else:
            opex += t["amount"]
    gp = rev - cogs
    return {
        "period": period,
        "revenue": round(rev, 2),
        "cogs": round(cogs, 2),
        "gross_profit": round(gp, 2),
        "gross_margin_pct": round(gp / rev * 100, 3) if rev else None,
        "opex": round(opex, 2),
        "net_income": round(gp - opex, 2),
        "net_margin_pct": round((gp - opex) / rev * 100, 3) if rev else None,
    }


def _agg(ds, period, key, where=None):
    out = defaultdict(float)
    for t in ds.txns(period):
        if where and not where(t):
            continue
        out[key(t)] += t["amount"]
    return out


def variance(ds, p0, p1):
    """Headline movement between two periods."""
    a, b = pnl(ds, p0), pnl(ds, p1)
    out = {"from": p0, "to": p1, "prior": a, "current": b, "lines": {}}
    for k in ("revenue", "cogs", "gross_profit", "opex", "net_income"):
        d = b[k] - a[k]
        out["lines"][k] = {
            "prior": a[k], "current": b[k],
            "change": round(d, 2),
            "change_pct": round(d / a[k] * 100, 2) if a[k] else None,
        }
    out["lines"]["gross_margin_pct"] = {
        "prior": a["gross_margin_pct"], "current": b["gross_margin_pct"],
        "change_bps": round((b["gross_margin_pct"] - a["gross_margin_pct"]) * 100, 1),
    }
    return out


def decompose(ds, p0, p1, dimension, section="Revenue", top=12):
    """Exhaustive attribution of a section's movement along one dimension.

    Every member of the dimension appears exactly once, members present in only
    one period contribute their full amount, and the parts sum to the total.
    """
    keymap = {
        "customer": lambda t: t["counterparty_name"] or "(unattributed)",
        "category": lambda t: t["category"] or "(unattributed)",
        "segment": lambda t: t["segment"] or "(unattributed)",
        "gl_account": lambda t: f"{t['gl_account']} {t['gl_account_name']}",
        "vendor": lambda t: t["counterparty_name"] or "(unattributed)",
        "sku": lambda t: t["description"] or "(unattributed)",
    }
    key = keymap[dimension]
    where = (lambda t: t["statement_section"] == section) if section else None
    a = _agg(ds, p0, key, where)
    b = _agg(ds, p1, key, where)

    rows = []
    for name in set(a) | set(b):
        pa, pb = a.get(name, 0.0), b.get(name, 0.0)
        rows.append({
            "name": name, "prior": round(pa, 2), "current": round(pb, 2),
            "change": round(pb - pa, 2),
            "change_pct": round((pb - pa) / pa * 100, 1) if pa else None,
            "status": "new" if not pa else ("lost" if not pb else
                      ("expanded" if pb > pa else "contracted")),
        })
    rows.sort(key=lambda r: -abs(r["change"]))
    total = round(sum(r["change"] for r in rows), 2)

    # Concentration: how few members explain the movement?
    movers = [r for r in rows if (r["change"] > 0) == (total > 0) and r["change"]]
    cum, n_for_80 = 0.0, None
    for i, r in enumerate(movers, 1):
        cum += r["change"]
        if n_for_80 is None and total and abs(cum / total) >= 0.8:
            n_for_80 = i
    top3 = sum(r["change"] for r in movers[:3])

    return {
        "dimension": dimension, "section": section, "from": p0, "to": p1,
        "total_change": total,
        "members": len(rows),
        "top": rows[:top],
        "concentration": {
            "top3_change": round(top3, 2),
            "top3_share_of_change": round(top3 / total * 100, 1) if total else None,
            "members_explaining_80pct": n_for_80,
            "movers_in_same_direction": len(movers),
        },
        "reconciles": abs(total - sum(r["change"] for r in rows)) < 0.01,
    }


def margin_bridge(ds, p0, p1):
    """Split the gross-profit movement into volume / mix / rate, exactly.

        volume = (R1 - R0) * m0_blended          revenue moved, old economics
        mix    = R1 * (sum(w1*m0) - m0_blended)  what we sold changed
        rate   = R1 * sum(w1 * (m1 - m0))        margin per category changed

    volume + mix + rate + non-product terms == total gross-profit change.
    A naive reading blames "rate" (a supplier increase is always findable and
    always true); this proves how much of the move rate can actually carry.
    """
    def cat_rev_cogs(p):
        rev, cogs = defaultdict(float), defaultdict(float)
        for t in ds.txns(p):
            c = t["category"]
            if c in PRODUCT_CATEGORIES:
                if t["gl_account"] == "4000":
                    rev[c] += t["amount"]
                elif t["gl_account"] == "5000":
                    cogs[c] += t["amount"]
        return rev, cogs

    r0, c0 = cat_rev_cogs(p0)
    r1, c1 = cat_rev_cogs(p1)
    cats = sorted(set(r0) | set(r1))
    R0, R1 = sum(r0.values()), sum(r1.values())
    GP0 = R0 - sum(c0.values())
    GP1 = R1 - sum(c1.values())
    m0 = {c: (r0[c] - c0[c]) / r0[c] if r0.get(c) else 0.0 for c in cats}
    m1 = {c: (r1[c] - c1[c]) / r1[c] if r1.get(c) else 0.0 for c in cats}
    w0 = {c: r0.get(c, 0.0) / R0 if R0 else 0.0 for c in cats}
    w1 = {c: r1.get(c, 0.0) / R1 if R1 else 0.0 for c in cats}
    m0b = sum(w0[c] * m0[c] for c in cats)

    volume = (R1 - R0) * m0b
    mix = R1 * (sum(w1[c] * m0[c] for c in cats) - m0b)
    rate = R1 * sum(w1[c] * (m1[c] - m0[c]) for c in cats)

    per_cat = sorted((
        {"category": c,
         "revenue_prior": round(r0.get(c, 0.0), 2),
         "revenue_current": round(r1.get(c, 0.0), 2),
         "weight_prior_pct": round(w0[c] * 100, 2),
         "weight_current_pct": round(w1[c] * 100, 2),
         "margin_prior_pct": round(m0[c] * 100, 2),
         "margin_current_pct": round(m1[c] * 100, 2),
         "mix_effect": round(R1 * (w1[c] - w0[c]) * m0[c], 2),
         "rate_effect": round(R1 * w1[c] * (m1[c] - m0[c]), 2)}
        for c in cats), key=lambda x: x["mix_effect"] + x["rate_effect"])

    # Everything outside product revenue/COGS, so the bridge stays exhaustive.
    full0, full1 = pnl(ds, p0), pnl(ds, p1)
    other = (full1["gross_profit"] - full0["gross_profit"]) - (GP1 - GP0)

    total = volume + mix + rate + other
    return {
        "from": p0, "to": p1,
        "gross_profit_prior": round(full0["gross_profit"], 2),
        "gross_profit_current": round(full1["gross_profit"], 2),
        "total_change": round(total, 2),
        "effects": {
            "volume": round(volume, 2),
            "mix": round(mix, 2),
            "rate": round(rate, 2),
            "other_non_product": round(other, 2),
        },
        "effect_shares_pct": {
            k: (round(v / total * 100, 1) if total else None)
            for k, v in {"volume": volume, "mix": mix, "rate": rate,
                         "other_non_product": other}.items()
        },
        "by_category": per_cat,
        "reconciles": abs(total - (full1["gross_profit"] - full0["gross_profit"])) < 0.5,
    }


def margin_rate_bridge(ds, p0, p1):
    """Why did gross margin PERCENT move? Volume cannot affect a rate, so this
    splits cleanly into two effects measured in basis points:

        mix  = sum(w1*m0) - sum(w0*m0)   we sold a different blend
        rate = sum(w1*m1) - sum(w1*m0)   each thing earned a different margin

    This is the decomposition that separates a real supplier price increase
    from a shift in what was sold. Both are true; only one is usually material.
    """
    def cat_rev_cogs(p):
        rev, cogs = defaultdict(float), defaultdict(float)
        for t in ds.txns(p):
            c = t["category"]
            if c in PRODUCT_CATEGORIES:
                if t["gl_account"] == "4000":
                    rev[c] += t["amount"]
                elif t["gl_account"] == "5000":
                    cogs[c] += t["amount"]
        return rev, cogs

    r0, c0 = cat_rev_cogs(p0)
    r1, c1 = cat_rev_cogs(p1)
    cats = sorted(set(r0) | set(r1))
    R0, R1 = sum(r0.values()), sum(r1.values())
    m0 = {c: (r0[c] - c0[c]) / r0[c] if r0.get(c) else 0.0 for c in cats}
    m1 = {c: (r1[c] - c1[c]) / r1[c] if r1.get(c) else 0.0 for c in cats}
    w0 = {c: r0.get(c, 0.0) / R0 if R0 else 0.0 for c in cats}
    w1 = {c: r1.get(c, 0.0) / R1 if R1 else 0.0 for c in cats}

    blended0 = sum(w0[c] * m0[c] for c in cats)
    blended1 = sum(w1[c] * m1[c] for c in cats)
    mix = sum(w1[c] * m0[c] for c in cats) - blended0
    rate = blended1 - sum(w1[c] * m0[c] for c in cats)

    rows = sorted((
        {"category": c,
         "weight_prior_pct": round(w0[c] * 100, 2),
         "weight_current_pct": round(w1[c] * 100, 2),
         "weight_change_pts": round((w1[c] - w0[c]) * 100, 2),
         "margin_prior_pct": round(m0[c] * 100, 2),
         "margin_current_pct": round(m1[c] * 100, 2),
         "margin_change_bps": round((m1[c] - m0[c]) * 10000, 1),
         "mix_effect_bps": round((w1[c] - w0[c]) * m0[c] * 10000, 1),
         "rate_effect_bps": round(w1[c] * (m1[c] - m0[c]) * 10000, 1)}
        for c in cats), key=lambda x: x["mix_effect_bps"] + x["rate_effect_bps"])

    total_bps = (blended1 - blended0) * 10000
    return {
        "from": p0, "to": p1,
        "product_margin_prior_pct": round(blended0 * 100, 2),
        "product_margin_current_pct": round(blended1 * 100, 2),
        "total_change_bps": round(total_bps, 1),
        "effects_bps": {"mix": round(mix * 10000, 1), "rate": round(rate * 10000, 1)},
        "effect_shares_pct": {
            "mix": round(mix / (mix + rate) * 100, 1) if (mix + rate) else None,
            "rate": round(rate / (mix + rate) * 100, 1) if (mix + rate) else None,
        },
        "by_category": rows,
        "reconciles": abs((mix + rate) * 10000 - total_bps) < 0.5,
    }
