"""Turn a completed run into durable priors.

Only findings that were confirmed by a deterministic detector become priors.
The agent never learns from its own prose, and everything it learns is filed
as `system_inferred` / `proposed` -- a reviewer confirms, corrects or rejects.

What each finding teaches the NEXT run:

  reclass       an accounting-policy boundary: comparisons across it are not
                like-for-like (valid from this period onward, both accounts)
  one_time      the following period will look "improved" for no reason
                (valid for exactly the next period, direction opposite the spike)
  silent_churn  a relationship that went quiet keeps being quiet: revenue at
                risk that no variance will ever show (valid from last purchase)
  timing        a recurring item whose landing month moves
"""


def _next(period):
    y, m = int(period[:4]), int(period[5:])
    return f"{y + (m == 12):04d}-{(m % 12) + 1:02d}"


def propose(store, run_id, period, findings, expectation=None):
    """Convert this run's verified findings into candidate priors. Returns ids."""
    added = []

    for f in findings.get("reclass", []):
        outs = [x["gl_account_name"] for x in f["moved_out_of"]]
        ins = [x["gl_account_name"] for x in f["moved_into"]]
        for acct in outs + ins:
            added.append(store.add(
                type="accounting_policy",
                scope={"account": acct, "vendor": f["counterparty"]},
                statement=(f"{f['counterparty']} spend was reclassified from {', '.join(outs)} into "
                           f"{', '.join(ins)} in {period} (${f['amount']:,.0f}/mo); net income unaffected"),
                implication=(f"{acct} is not comparable across {period}; compare net income, or restate "
                             "the earlier period, before reading this line as an economic change"),
                basis={"run_id": run_id, "period": period, "detector": "reclass",
                       "amount": f["amount"], "offset_ratio": f["offset_ratio"]},
                confidence=f["confidence"], applies_to={"from_period": period},
                source_type="system_inferred", source="detector:reclass"))

    for f in findings.get("one_time", []):
        acct = f.get("gl_account_name") or f["gl_account"]
        memo = next((e.get("memo") or e.get("description") for e in f.get("evidence", [])
                     if e.get("memo") or e.get("description")), "")
        nxt = _next(period)
        added.append(store.add(
            type="one_time",
            scope={"account": acct, "period": period},
            statement=(f"{acct} in {period} contained a non-recurring item of ${f['excess']:,.0f} "
                       f"({f['z_score']:.1f} sigma above its own history)" + (f": {memo}" if memo else "")),
            implication=(f"expect {acct} to fall back in {nxt}; that decrease is the item not repeating, "
                         "not a saving, and must not be extrapolated"),
            basis={"run_id": run_id, "period": period, "detector": "one_time",
                   "excess": f["excess"], "z_score": f["z_score"],
                   "evidence": [e["txn_id"] for e in f.get("evidence", [])]},
            confidence=f["confidence"],
            applies_to={"from_period": nxt, "to_period": nxt},
            expectation={"direction": "down" if f["excess"] > 0 else "up"},
            source_type="system_inferred", source="detector:one_time"))

    for f in findings.get("silent_churn", [])[:8]:
        acct = f.get("account") or "Revenue"
        what = f"{f['category']} " if f.get("category") and f["category"] != "(all)" else ""
        added.append(store.add(
            type="structural",
            scope={"account": acct, "customer": f["customer"], "category": f.get("category", "")},
            statement=(f"{f['customer']} bought {what}in {f['months_active']} of {f['months_available']} months "
                       f"(~${f['avg_monthly_revenue']:,.0f}/mo) and has bought none since {f['last_purchase_period']}"),
            implication=(f"treat continued silence as ${f['annualised_run_rate_lost']:,.0f} of annualised "
                         f"{acct} at risk; it creates no transaction and will never appear in a variance"),
            basis={"run_id": run_id, "period": period, "detector": "silent_churn",
                   "avg_monthly": f["avg_monthly_revenue"], "consistency_pct": f["consistency_pct"]},
            confidence=f["confidence"], applies_to={"from_period": f["last_purchase_period"]},
            source_type="system_inferred", source="detector:silent_churn"))

    for f in findings.get("timing", []):
        added.append(store.add(
            type="timing_pattern",
            scope={"account": f.get("account") or "Revenue", "customer": f["member"]},
            statement=(f"{f['member']} has a large order whose landing month moves between periods "
                       f"(${abs(f['yoy_change_in_current_period']):,.0f} scale); in {period} it landed here "
                       "and the prior period was correspondingly light"),
            implication=("compare this account year-on-year or across the adjacent month pair; a "
                         "month-on-month move for it is usually timing, not growth"),
            basis={"run_id": run_id, "period": period, "detector": "timing_shift",
                   "offset_ratio": f["offset_ratio"]},
            confidence=f["confidence"], applies_to={},
            source_type="system_inferred", source="detector:timing_shift"))

    return [a for a in added if a]
