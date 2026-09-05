"""Turn a completed run into durable priors.

Only findings that were confirmed by a deterministic detector become priors.
The agent never learns from its own prose.
"""


def propose(store, run_id, period, findings, expectation=None):
    """Convert this run's verified findings into candidate priors."""
    added = []

    for f in findings.get("reclass", []):
        added.append(store.add(
            type="accounting_policy",
            scope={"vendor": f["counterparty"],
                   "accounts": [x["gl_account"] for x in f["moved_out_of"]]
                               + [x["gl_account"] for x in f["moved_into"]]},
            statement=(f"{f['counterparty']} spend was reclassified from "
                       f"{', '.join(x['gl_account_name'] for x in f['moved_out_of'])} into "
                       f"{', '.join(x['gl_account_name'] for x in f['moved_into'])} "
                       f"in {period} (${f['amount']:,.0f}/mo). Net income unaffected."),
            implication=("Gross margin and opex are not comparable across this boundary. "
                         "Restate prior periods before comparing, or compare net income."),
            basis={"run_id": run_id, "period": period, "detector": "reclass",
                   "amount": f["amount"], "offset_ratio": f["offset_ratio"]},
            confidence=f["confidence"],
            applies_to={"from_period": period}))

    for f in findings.get("timing", []):
        added.append(store.add(
            type="timing_pattern",
            scope={"customer": f["member"]},
            statement=(f"{f['member']} has a large order whose landing month moves between "
                       f"periods (${abs(f['yoy_change_in_current_period']):,.0f} scale). "
                       f"In {period} it landed here; the prior period was correspondingly light."),
            implication=("Compare this account year-on-year, or across the adjacent month pair. "
                         "A month-on-month move for this account is usually timing, not growth."),
            basis={"run_id": run_id, "period": period, "detector": "timing_shift",
                   "offset_ratio": f["offset_ratio"],
                   "evidence": [e["txn_id"] for e in f.get("evidence", [])]},
            confidence=f["confidence"],
            applies_to={}))

    for f in findings.get("one_time", []):
        memo = next((e["memo"] for e in f.get("evidence", []) if e.get("memo")), "")
        added.append(store.add(
            type="one_time",
            scope={"gl_account": f["gl_account"], "period": period},
            statement=(f"{f['gl_account_name']} in {period} contained a non-recurring item of "
                       f"${f['excess']:,.0f} ({f['z_score']:.1f} sigma above its own history)"
                       + (f": {memo}" if memo else "") + "."),
            implication=("Exclude from run-rate and from any forward extrapolation. "
                         "The following period will look improved for no operational reason."),
            basis={"run_id": run_id, "period": period, "detector": "one_time",
                   "excess": f["excess"], "z_score": f["z_score"],
                   "evidence": [e["txn_id"] for e in f.get("evidence", [])]},
            confidence=f["confidence"],
            applies_to={"only_period": period}))

    for f in findings.get("silent_churn", [])[:8]:
        added.append(store.add(
            type="structural",
            scope={"customer": f["customer"], "category": f["category"]},
            statement=(f"{f['customer']} bought {f['category']} in {f['months_active']} of "
                       f"{f['months_available']} months (~${f['avg_monthly_revenue']:,.0f}/mo) "
                       f"and has bought none since {f['last_purchase_period']}."),
            implication=(f"Treat continued absence as ${f['annualised_run_rate_lost']:,.0f} of "
                         "annualised revenue at risk. This produces no transaction, so it will "
                         "never appear in a variance report."),
            basis={"run_id": run_id, "period": period, "detector": "silent_churn",
                   "avg_monthly": f["avg_monthly_revenue"],
                   "consistency_pct": f["consistency_pct"]},
            confidence=f["confidence"],
            applies_to={"from_period": f["last_purchase_period"]}))

    for f in findings.get("ar_deterioration", []):
        added.append(store.add(
            type="counterparty",
            scope={"customer": f["customer"], "aspect": "payment_behaviour"},
            statement=(f"{f['customer']} now pays {f['avg_days_late_recent']:.0f} days late, "
                       f"up from {f['avg_days_late_prior']:.0f}."),
            implication=("Discount revenue growth from this account when assessing quality. "
                         "Rising days-late alongside rising volume is a warning, not a win."),
            basis={"run_id": run_id, "period": period, "detector": "ar_deterioration",
                   "deterioration_days": f["deterioration_days"]},
            confidence=f["confidence"],
            applies_to={}))

    if expectation and expectation.get("available"):
        month = int(period[5:])
        added.append(store.add(
            type="seasonality",
            scope={"month": month, "metric": expectation["metric"]},
            statement=(f"Month {month:02d} carries a seasonal index of "
                       f"{expectation['seasonal_index']} "
                       f"(prior month {expectation['seasonal_index_prior_month']}), "
                       f"estimated from {expectation['history_periods']} periods."),
            implication=("Judge this month against its seasonal expectation, not against "
                         "the previous month."),
            basis={"run_id": run_id, "period": period, "detector": "seasonal_index",
                   "index": expectation["seasonal_index"]},
            confidence=0.7,
            applies_to={"months": [month]}))

    return [a for a in added if a]
