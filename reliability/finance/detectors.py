"""Falsification checks.

The agent proposes an explanation; these try to kill it. Anything that survives
is reported, anything that dies is reported as a rejected hypothesis -- which is
often more useful, because the rejected one is what a human would have believed.

Every detector returns evidence: the actual transaction rows behind the claim.
"""

from collections import defaultdict
from statistics import mean, pstdev


def _by(ds, period, keyfn, where=None):
    out = defaultdict(float)
    for t in ds.txns(period):
        if where and not where(t):
            continue
        out[keyfn(t)] += t["amount"]
    return out


def _shift(period, months):
    y, m = int(period[:4]), int(period[5:])
    m += months
    y += (m - 1) // 12
    m = (m - 1) % 12 + 1
    return f"{y:04d}-{m:02d}"


# ---------------------------------------------------------------------------
def detect_reclass(ds, p0, p1, min_amount=15_000):
    """Did money move BETWEEN GL accounts without the business changing?

    A reclassification looks exactly like a cost blow-out in one account and a
    saving in another. The tell is the same counterparty, similar amounts,
    opposite directions, and no change in net income.
    """
    a = _by(ds, p0, lambda t: (t["counterparty_name"], t["gl_account"], t["gl_account_name"]))
    b = _by(ds, p1, lambda t: (t["counterparty_name"], t["gl_account"], t["gl_account_name"]))
    vend = defaultdict(lambda: {"out": [], "in": []})
    for k in set(a) | set(b):
        name, acct, acct_name = k
        d = b.get(k, 0.0) - a.get(k, 0.0)
        if abs(d) < min_amount:
            continue
        vend[name]["out" if d < 0 else "in"].append(
            {"gl_account": acct, "gl_account_name": acct_name,
             "prior": round(a.get(k, 0.0), 2), "current": round(b.get(k, 0.0), 2),
             "change": round(d, 2)})

    findings = []
    for name, sides in vend.items():
        if not (sides["out"] and sides["in"]):
            continue
        gone = -sum(x["change"] for x in sides["out"])
        came = sum(x["change"] for x in sides["in"])
        offset = min(gone, came) / max(gone, came) if max(gone, came) else 0
        if offset < 0.7:
            continue
        memos = sorted({t["memo"] for t in ds.txns(p1)
                        if t["counterparty_name"] == name and t["memo"]})
        findings.append({
            "counterparty": name,
            "moved_out_of": sides["out"], "moved_into": sides["in"],
            "amount": round(min(gone, came), 2),
            "offset_ratio": round(offset, 3),
            "memos": memos,
            "verdict": "reclassification — no economic change",
            "confidence": round(min(0.99, 0.6 + offset * 0.35), 2),
        })
    return sorted(findings, key=lambda f: -f["amount"])


# ---------------------------------------------------------------------------
def detect_timing_shift(ds, p0, p1, dimension="customer", min_amount=50_000):
    """Is this growth, or is it the same order landing in a different month?

    Compared year-on-year, a genuine gain is up in p1 and flat in p0. A timing
    slip is up in p1 and down in p0 by a similar amount -- the two offset.
    """
    keyfn = {"customer": lambda t: t["counterparty_name"],
             "category": lambda t: t["category"]}[dimension]
    where = lambda t: t["statement_section"] == "Revenue"

    p0_ly, p1_ly = _shift(p0, -12), _shift(p1, -12)
    if p0_ly not in ds.periods or p1_ly not in ds.periods:
        return []

    cur0, cur1 = _by(ds, p0, keyfn, where), _by(ds, p1, keyfn, where)
    ly0, ly1 = _by(ds, p0_ly, keyfn, where), _by(ds, p1_ly, keyfn, where)

    findings = []
    for name in set(cur1) | set(cur0):
        yoy1 = cur1.get(name, 0.0) - ly1.get(name, 0.0)
        yoy0 = cur0.get(name, 0.0) - ly0.get(name, 0.0)
        if abs(yoy1) < min_amount or yoy1 * yoy0 >= 0:
            continue
        offset = min(abs(yoy1), abs(yoy0)) / max(abs(yoy1), abs(yoy0))
        if offset < 0.55:
            continue
        ev = [t for t in ds.txns(p1)
              if keyfn(t) == name and t["statement_section"] == "Revenue"]
        ev.sort(key=lambda t: -t["amount"])
        findings.append({
            "member": name,
            "yoy_change_in_current_period": round(yoy1, 2),
            "yoy_change_in_prior_period": round(yoy0, 2),
            "offset_ratio": round(offset, 3),
            "net_across_both_periods": round(yoy1 + yoy0, 2),
            "verdict": ("timing shift between periods, not incremental volume"
                        if offset > 0.7 else "partial timing shift"),
            "confidence": round(min(0.97, 0.5 + offset * 0.45), 2),
            "evidence": [{"txn_id": t["txn_id"], "date": t["date"], "doc_id": t["doc_id"],
                          "description": t["description"], "amount": t["amount"],
                          "memo": t["memo"]} for t in ev[:4]],
        })
    return sorted(findings, key=lambda f: -abs(f["yoy_change_in_current_period"]))


# ---------------------------------------------------------------------------
def detect_one_time(ds, period, z=3.0, min_amount=25_000):
    """Line items far outside their own account's history. Do not extrapolate these."""
    hist = ds.history_before(period)
    if len(hist) < 6:
        return []
    series = defaultdict(dict)
    for p in hist + [period]:
        for k, v in _by(ds, p, lambda t: (t["gl_account"], t["gl_account_name"])).items():
            series[k][p] = v

    findings = []
    for (acct, name), vals in series.items():
        past = [vals.get(p, 0.0) for p in hist]
        cur = vals.get(period)
        if cur is None or len(past) < 6:
            continue
        mu, sd = mean(past), pstdev(past)
        if sd <= 0 or abs(cur - mu) < min_amount or abs(cur - mu) / sd < z:
            continue
        rows = [t for t in ds.txns(period) if t["gl_account"] == acct]
        rows.sort(key=lambda t: -t["amount"])
        findings.append({
            "gl_account": acct, "gl_account_name": name,
            "current": round(cur, 2), "historical_mean": round(mu, 2),
            "excess": round(cur - mu, 2), "z_score": round((cur - mu) / sd, 2),
            "verdict": "non-recurring item — exclude from run-rate",
            "confidence": round(min(0.97, 0.55 + min((cur - mu) / sd, 8) * 0.05), 2),
            "evidence": [{"txn_id": t["txn_id"], "date": t["date"],
                          "counterparty": t["counterparty_name"],
                          "description": t["description"], "amount": t["amount"],
                          "memo": t["memo"]} for t in rows[:4]],
        })
    return sorted(findings, key=lambda f: -abs(f["excess"]))


# ---------------------------------------------------------------------------
def detect_silent_churn(ds, period, lookback=3, min_history=10, min_monthly=4_000,
                        section="Revenue", dim="category"):
    """Revenue that stopped arriving.

    A variance report can only see rows that exist. This finds counterparty x
    `dim` relationships that were reliably present for many months and have
    since produced nothing at all. No transaction is created when a customer
    stops buying, so this is invisible to any period-over-period difference.

    Works on any dataset exposing statement_section / counterparty_id; `dim`
    falls back to the counterparty alone when the column is absent.
    """
    periods = [p for p in ds.periods if p <= period]
    if len(periods) < min_history + lookback:
        return []
    recent, hist = periods[-lookback:], periods[:-lookback]

    amounts = defaultdict(float)
    seen = defaultdict(set)
    names = {}
    for p in periods:
        for t in ds.txns(p):
            if t["statement_section"] != section or not t["counterparty_id"]:
                continue
            k = (t["counterparty_id"], (t.get(dim) or "") if dim else "")
            amounts[(k, p)] += t["amount"]
            seen[k].add(p)
            names[t["counterparty_id"]] = t["counterparty_name"]

    findings = []
    for k, months in seen.items():
        cid, cat = k
        h = [p for p in hist if p in months]
        if len(h) < min_history or any(p in months for p in recent):
            continue
        avg = sum(amounts[(k, p)] for p in h) / len(h)
        if avg < min_monthly:
            continue
        last = max(h)
        ev = [t for t in ds.txns(last)
              if t["counterparty_id"] == cid and (t.get(dim) or "") == cat and t["statement_section"] == section]
        findings.append({
            "customer_id": cid, "customer": names[cid], "category": cat or "(all)",
            "section": section,
            "months_active": len(h), "months_available": len(hist),
            "consistency_pct": round(len(h) / len(hist) * 100, 1),
            "avg_monthly_revenue": round(avg, 2),
            "last_purchase_period": last,
            "silent_for_months": lookback,
            "annualised_run_rate_lost": round(avg * 12, 2),
            "verdict": "recurring revenue stopped — no transaction exists to flag this",
            "confidence": round(min(0.96, 0.5 + len(h) / len(hist) * 0.45), 2),
            "evidence": [{"txn_id": t["txn_id"], "date": t["date"], "doc_id": t.get("doc_id", ""),
                          "description": t["description"], "amount": t["amount"],
                          "memo": t.get("memo", "")} for t in sorted(ev, key=lambda x: -x["amount"])[:3]],
        })
    return sorted(findings, key=lambda f: -f["avg_monthly_revenue"])


# ---------------------------------------------------------------------------
def detect_ar_deterioration(ds, period, lookback=6, min_worsening=8):
    """Is the growth we booked actually collectable? Quality-of-revenue check."""
    periods = [p for p in ds.periods if p <= period]
    recent = set(periods[-3:])
    older = set(periods[-lookback - 3:-3])

    late = defaultdict(lambda: {"recent": [], "older": []})
    amt = defaultdict(float)
    for inv in ds.invoices:
        p = inv["issue_date"][:7]
        if p in recent:
            late[inv["customer_name"]]["recent"].append(inv["days_late"])
            amt[inv["customer_name"]] += inv["amount"]
        elif p in older:
            late[inv["customer_name"]]["older"].append(inv["days_late"])

    findings = []
    for name, d in late.items():
        if len(d["recent"]) < 2 or len(d["older"]) < 3:
            continue
        r, o = mean(d["recent"]), mean(d["older"])
        if r - o < min_worsening:
            continue
        findings.append({
            "customer": name,
            "avg_days_late_recent": round(r, 1),
            "avg_days_late_prior": round(o, 1),
            "deterioration_days": round(r - o, 1),
            "revenue_at_risk_recent": round(amt[name], 2),
            "verdict": "payment behaviour deteriorating — revenue quality declining",
            "confidence": round(min(0.95, 0.5 + (r - o) / 60), 2),
        })
    return sorted(findings, key=lambda f: -f["deterioration_days"])
