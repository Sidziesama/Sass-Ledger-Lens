"""Data-quality gate. Runs before any financial meaning is assigned.

A data problem must never be narrated as a business event. A $90k gap between
the summary and the transactions is not "revenue growth we cannot explain"; it
is a reason to refuse to explain. Every check here produces a structured flag
with a severity, and the severity decides what the agent is allowed to say:

    blocker  -> attribution on the affected scope is refused; abstain
    warning  -> attribution proceeds with reduced data confidence and a caveat
    info     -> recorded, shown, does not change the analysis
"""

from collections import defaultdict
from statistics import mean, pstdev

from ..ingestion.normalize import norm_key

RECON_TOLERANCE_ABS = 1.00        # cents-level noise
RECON_TOLERANCE_PCT = 0.001       # 0.1%
OUTLIER_Z = 6.0
DUP_BLOCK_FLOOR = 5_000           # a possible duplicate below this is a note, not a reason to refuse
MIN_HISTORY_FOR_SEASONALITY = 13
MIN_HISTORY_FOR_TREND = 6


def _flag(code, severity, detail, scope=None, **extra):
    f = {"code": code, "severity": severity, "detail": detail, "scope": scope or {}}
    f.update(extra)
    return f


def run_gate(ds, period, prior_period):
    """Return a report: {passed, blockers, warnings, flags[], data_confidence, ...}."""
    flags = []
    rep = ds.parse_report

    # --- structural ---------------------------------------------------------
    for fname, cols in rep.get("missing_columns", {}).items():
        flags.append(_flag("MISSING_COLUMNS", "blocker",
                           f"{fname} is missing required columns: {', '.join(cols)}",
                           {"file": fname, "columns": cols}))
    for bad in rep.get("summary_rows_malformed", []) + rep.get("txn_rows_malformed", []):
        flags.append(_flag("CORRUPT_ROW", "warning",
                           f"row {bad['row']}: {bad['problem']}", {"row": bad["row"]}))
    for ap in rep.get("amount_problems", []):
        flags.append(_flag("UNPARSEABLE_AMOUNT", "warning",
                           f"{ap['file']}: {ap['problem']}",
                           {"transaction_id": ap["row"].get("transaction_id")}))
    for dp in rep.get("date_problems", []):
        sev = "warning" if "ambiguous" in dp["problem"] else "warning"
        flags.append(_flag("MALFORMED_DATE", sev, dp["problem"],
                           {"transaction_id": dp["row"].get("transaction_id")}))
    for pp in rep.get("period_problems", []):
        flags.append(_flag("MALFORMED_PERIOD", "warning", f"{pp['file']}: {pp['problem']}",
                           {"transaction_id": pp["row"].get("transaction_id")}))
    for lk in rep.get("lookalike_names", []):
        flags.append(_flag("LOOKALIKE_NAME", "warning",
                           f"'{lk['counterparty'] or lk['account']}' mixes scripts (possible spoofed name)",
                           {"transaction_id": lk["transaction_id"]}))
    if rep.get("section_inferred_accounts"):
        flags.append(_flag("SECTION_INFERRED", "info",
                           "statement section inferred from account names for: "
                           + ", ".join(rep["section_inferred_accounts"][:8]),
                           {"accounts": rep["section_inferred_accounts"]}))

    # --- periods ------------------------------------------------------------
    for p, label in ((period, "current"), (prior_period, "prior")):
        if p and p not in ds.periods:
            flags.append(_flag("MISSING_PERIOD", "blocker",
                               f"{label} period {p} has no data", {"period": p}))
    hist = len([p for p in ds.periods if p <= period])
    if hist < MIN_HISTORY_FOR_SEASONALITY:
        flags.append(_flag("INSUFFICIENT_HISTORY", "info",
                           f"{hist} periods available; seasonality claims require "
                           f"{MIN_HISTORY_FOR_SEASONALITY}, trend claims {MIN_HISTORY_FOR_TREND}",
                           {"periods": hist},
                           seasonality_allowed=hist >= MIN_HISTORY_FOR_SEASONALITY,
                           trend_allowed=hist >= MIN_HISTORY_FOR_TREND))
    # gaps in the period sequence
    if len(ds.periods) >= 2:
        def _next(p):
            y, m = int(p[:4]), int(p[5:])
            return f"{y + (m == 12):04d}-{(m % 12) + 1:02d}"
        for a, b in zip(ds.periods, ds.periods[1:]):
            if _next(a) != b:
                flags.append(_flag("PERIOD_GAP", "warning",
                                   f"no data between {a} and {b}", {"from": a, "to": b}))

    # --- transactions in scope ----------------------------------------------
    scope = [t for t in ds.transactions if t["period"] in (period, prior_period)]

    ids = defaultdict(list)
    for t in scope:
        ids[t["txn_id"]].append(t)
    for tid, rows in ids.items():
        if not tid:
            flags.append(_flag("MISSING_TXN_ID", "warning", f"{len(rows)} rows have no transaction_id"))
            continue
        if len(rows) > 1:
            same = all(r["amount"] == rows[0]["amount"] and r["counterparty_id"] == rows[0]["counterparty_id"]
                       for r in rows)
            sev = ("blocker" if same and abs(rows[0]["amount"]) >= DUP_BLOCK_FLOOR
                   else "warning" if same else "warning")
            flags.append(_flag("DUPLICATE_TXN_ID", sev,
                               f"transaction_id {tid} appears {len(rows)}x"
                               + (" with identical content" if same else " with differing content"),
                               {"transaction_id": tid, "account": rows[0]["gl_account"],
                                "amount": rows[0]["amount"], "period": rows[0]["period"]}))

    # probable duplicates: same account, counterparty and amount within 2 days,
    # under different ids. Exact same-day copies are the strongest signal.
    from datetime import date as _date
    def _d(t):
        try:
            return _date.fromisoformat(t["date"])
        except Exception:                                 # noqa: BLE001
            return None
    groups = defaultdict(list)
    for t in scope:
        groups[(t["period"], t["account_key"], t["counterparty_id"], round(t["amount"], 2))].append(t)
    for k, rows in groups.items():
        if len(rows) < 2 or len({r["txn_id"] for r in rows}) < 2:
            continue
        rows = sorted(rows, key=lambda r: r["date"])
        for a, b in zip(rows, rows[1:]):
            da, db = _d(a), _d(b)
            if da and db and abs((db - da).days) <= 2 and a["txn_id"] != b["txn_id"]:
                flags.append(_flag("PROBABLE_DUPLICATE",
                                   "blocker" if abs(a["amount"]) >= DUP_BLOCK_FLOOR else "info",
                                   f"{a['txn_id']} and {b['txn_id']} share account, counterparty and amount "
                                   f"({a['amount']:,.2f}) {abs((db - da).days)} day(s) apart",
                                   {"transaction_ids": [a["txn_id"], b["txn_id"]],
                                    "account": a["gl_account"], "amount": a["amount"],
                                    "period": a["period"]}))

    # reversals: equal and opposite, same counterparty, within scope
    by_cp = defaultdict(list)
    for t in scope:
        by_cp[(t["account_key"], t["counterparty_id"])].append(t)
    for k, rows in by_cp.items():
        pos = [r for r in rows if r["amount"] > 0]
        neg = [r for r in rows if r["amount"] < 0]
        used = set()
        for p in pos:
            for n in neg:
                if n["txn_id"] in used:
                    continue
                if abs(p["amount"] + n["amount"]) < 0.01:
                    used.add(n["txn_id"])
                    flags.append(_flag("REVERSAL_PAIR", "warning",
                                       f"{p['txn_id']} ({p['period']}, {p['amount']:,.2f}) is reversed by "
                                       f"{n['txn_id']} ({n['period']}, {n['amount']:,.2f})",
                                       {"transaction_ids": [p["txn_id"], n["txn_id"]],
                                        "account": p["gl_account"], "amount": abs(p["amount"]),
                                        "cross_period": p["period"] != n["period"]}))
                    break

    for t in scope:
        if t["date_ok"] and t["period"] and t["date"][:7] != t["period"]:
            flags.append(_flag("TXN_OUTSIDE_PERIOD", "warning",
                               f"{t['txn_id']} dated {t['date']} is booked to {t['period']}",
                               {"transaction_id": t["txn_id"], "period": t["period"]}))
        if not t["counterparty_name"]:
            flags.append(_flag("MISSING_COUNTERPARTY", "info",
                               f"{t['txn_id']} has no counterparty", {"transaction_id": t["txn_id"]}))

    currencies = {t["currency"] for t in scope if t["currency"]}
    if len(currencies) > 1:
        flags.append(_flag("MIXED_CURRENCY", "warning",
                           f"transactions carry multiple currencies: {', '.join(sorted(currencies))}. "
                           "Movements may include translation effects.", {"currencies": sorted(currencies)}))

    # account naming variants
    variants = defaultdict(set)
    for t in ds.transactions:
        variants[t["account_key"]].add(t["gl_account"])
    for s in ds.summary:
        variants[s["account_key"]].add(s["account"])
    for k, names in variants.items():
        if len(names) > 1:
            flags.append(_flag("INCONSISTENT_ACCOUNT_NAME", "warning",
                               "same account written as: " + " | ".join(sorted(names)),
                               {"variants": sorted(names)}))

    # sign consistency: a revenue account that is mostly negative, etc.
    for p in (period, prior_period):
        by_acct = defaultdict(list)
        for t in ds.txns(p):
            by_acct[t["gl_account"]].append(t["amount"])
        for a, amts in by_acct.items():
            if len(amts) >= 5:
                neg = sum(1 for x in amts if x < 0) / len(amts)
                if 0.35 < neg < 0.65:
                    flags.append(_flag("SIGN_INCONSISTENT", "warning",
                                       f"{a} in {p}: {neg:.0%} of rows are negative — mixed signs; "
                                       "gross activity and net movement differ",
                                       {"account": a, "period": p}))

    # --- reconciliation: the check that matters most --------------------------
    txn_tot = defaultdict(float)
    for t in ds.transactions:
        txn_tot[(t["period"], t["account_key"])] += t["amount"]
    sum_rows = defaultdict(list)
    for s in ds.summary:
        sum_rows[(s["period"], s["account_key"])].append(s)
    for (p, ak), rows in sum_rows.items():
        if p not in (period, prior_period):
            continue
        amounts = {round(r["amount"], 2) for r in rows}
        if len(amounts) > 1:
            flags.append(_flag("CONFLICTING_SUMMARY", "blocker",
                               f"{rows[0]['account']} in {p} has {len(rows)} conflicting summary rows: "
                               + ", ".join(f"{a:,.2f}" for a in sorted(amounts)),
                               {"account": rows[0]["account"], "period": p, "amounts": sorted(amounts)}))
            continue
        s_amt = rows[0]["amount"]
        t_amt = txn_tot.get((p, ak))
        if t_amt is None:
            if abs(s_amt) > 0:
                flags.append(_flag("NO_TRANSACTIONS_FOR_ACCOUNT", "blocker",
                                   f"{rows[0]['account']} in {p} reports {s_amt:,.2f} in the summary "
                                   "but has no transaction records; attribution cannot be completed",
                                   {"account": rows[0]["account"], "period": p, "summary": s_amt}))
            continue
        gap = s_amt - t_amt
        tol = max(RECON_TOLERANCE_ABS, abs(s_amt) * RECON_TOLERANCE_PCT)
        if abs(gap) > tol:
            flags.append(_flag("RECONCILIATION_GAP", "blocker",
                               f"{rows[0]['account']} in {p}: summary {s_amt:,.2f} vs transactions "
                               f"{t_amt:,.2f} — gap {gap:+,.2f}",
                               {"account": rows[0]["account"], "period": p,
                                "summary": s_amt, "transactions": t_amt, "gap": gap}))
    for (p, ak), amt in txn_tot.items():
        if p in (period, prior_period) and (p, ak) not in sum_rows:
            flags.append(_flag("MISSING_ACCOUNT_MAPPING", "warning",
                               f"transactions exist for an account absent from the summary in {p} "
                               f"(total {amt:,.2f})", {"account_key": ak, "period": p}))

    # --- outliers within account history ------------------------------------
    hist_by_acct = defaultdict(list)
    for t in ds.transactions:
        if t["period"] < period:
            hist_by_acct[t["account_key"]].append(abs(t["amount"]))
    for t in ds.txns(period):
        h = hist_by_acct.get(t["account_key"], [])
        if len(h) >= 20:
            mu, sd = mean(h), pstdev(h)
            if sd and (abs(t["amount"]) - mu) / sd > OUTLIER_Z:
                flags.append(_flag("EXTREME_OUTLIER", "info",
                                   f"{t['txn_id']} ({t['amount']:,.2f}) is {(abs(t['amount']) - mu) / sd:.0f} sigma "
                                   f"above typical {t['gl_account']} transactions",
                                   {"transaction_id": t["txn_id"], "account": t["gl_account"]}))

    # --- semantic inconsistencies (description says one thing, sign says another)
    for t in scope:
        d = t["description"].lower()
        if ("refund" in d or "credit memo" in d or "reversal" in d) and t["amount"] > 0 \
                and t["statement_section"] == "Revenue":
            flags.append(_flag("DESCRIPTION_SIGN_MISMATCH", "warning",
                               f"{t['txn_id']} is described as '{t['description']}' but is a positive "
                               "revenue amount; structured sign takes precedence",
                               {"transaction_id": t["txn_id"]}))

    blockers = [f for f in flags if f["severity"] == "blocker"]
    warnings = [f for f in flags if f["severity"] == "warning"]
    infos = [f for f in flags if f["severity"] == "info"]

    # data confidence: starts at 1, each blocker costs a lot, each warning a little
    conf = 1.0 - 0.35 * min(len(blockers), 2) - 0.05 * min(len(warnings), 6)
    blocked_accounts = sorted({f["scope"].get("account") for f in blockers if f["scope"].get("account")})
    return {
        "passed": not blockers,
        "data_confidence": round(max(conf, 0.0), 2),
        "blockers": blockers, "warnings": warnings, "infos": infos, "flags": flags,
        "blocked_accounts": blocked_accounts,
        "history_periods": hist,
        "seasonality_allowed": hist >= MIN_HISTORY_FOR_SEASONALITY,
        "trend_allowed": hist >= MIN_HISTORY_FOR_TREND,
        "dimensions_available": ds.dimensions,
    }
