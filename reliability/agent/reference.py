"""Reference investigator: the deterministic system-under-test.

No language model is involved. Everything here is arithmetic, policy and
templates, which is the point: this is the floor. Any investigator your team
ships must do at least this well on the benchmark, and an LLM-driven one can
only add interpretation on top of these facts -- never replace them.

Policy in one line:  calculate, reconcile, investigate, challenge, quantify the
residual, cite, abstain.
"""

import json
import os
import re
from collections import defaultdict

from ..evidence.claims import Claim, ClaimSet
from ..finance import detectors as D
from ..finance.metrics import expectation
from ..ingestion.normalize import SimpleDataset
from ..memory.store import PriorStore
from ..observability.prism import Tracer
from ..quality.gate import run_gate
from ..policy.language import lint
from ..policy.uncertainty import assemble

DIMS = ("counterparty", "segment", "department", "category", "product", "geography")
MAX_ACCOUNTS = 4
DEFAULT_POLICY = {"min_dollar": 1_000, "min_pct": 0.0, "critical_accounts": [],
                  "sensitivity": "normal"}

TOP_DRIVER_COVERAGE, TOP3_COVERAGE = 0.70, 0.60
SINGLE_TXN_SHARE = 0.70
CONCENTRATION_SHARE = 0.80
DISTRIBUTED_TOP3 = 0.35
DISTRIBUTED_MIN_MEMBERS = 20
UNEXPLAINED_REPORT_SHARE = 0.15


def _shift_period(period, months):
    y, m = int(period[:4]), int(period[5:])
    m += months
    y += (m - 1) // 12
    m = (m - 1) % 12 + 1
    return f"{y:04d}-{m:02d}"


def _money(v):
    """Signed currency: -$40,000 stays negative. Direction words are not enough
    when a balance itself goes below zero."""
    return f"-${abs(v):,.0f}" if v < 0 else f"${v:,.0f}"


def _signed(v):
    return f"+${v:,.0f}" if v >= 0 else f"-${abs(v):,.0f}"


def _dim_value(t, dim):
    return t["counterparty_name"] if dim == "counterparty" else t.get(dim, "")


def _account_totals(ds, period):
    out = defaultdict(float)
    for t in ds.txns(period):
        out[t["account_key"]] += t["amount"]
    return out


def _summary_totals(ds, period):
    """Per-account summary totals. Accounts with CONFLICTING rows are omitted,
    so the caller falls back to transaction totals rather than summing two
    different claims about the same number."""
    out, names, seen = {}, {}, defaultdict(set)
    for s in ds.summary:
        if s["period"] == period:
            seen[s["account_key"]].add(round(s["amount"], 2))
            out[s["account_key"]] = out.get(s["account_key"], 0.0) + s["amount"]
            names[s["account_key"]] = s["account"]
    for k, vals in seen.items():
        if len(vals) > 1:
            out.pop(k, None)
    return out, names


def _decompose(ds, p0, p1, account_key, dim, where=None):
    """MECE attribution of one account's movement along one dimension.

    `where` narrows to a subset (e.g. segment == "Enterprise") so the agent can
    drill Revenue -> Enterprise -> Acme instead of stopping at the segment.
    """
    a, b, ids_b, ids_a, cnt = defaultdict(float), defaultdict(float), defaultdict(list), defaultdict(list), 0
    for t in ds.txns(p0):
        if t["account_key"] == account_key and (where is None or where(t)):
            k = _dim_value(t, dim) or "(blank)"
            a[k] += t["amount"]; ids_a[k].append(t["txn_id"])
    for t in ds.txns(p1):
        if t["account_key"] == account_key and (where is None or where(t)):
            k = _dim_value(t, dim) or "(blank)"
            b[k] += t["amount"]; ids_b[k].append(t["txn_id"]); cnt += 1
    rows = []
    for k in set(a) | set(b):
        pa, pb = a.get(k, 0.0), b.get(k, 0.0)
        rows.append({"name": k, "prior": round(pa, 2), "current": round(pb, 2),
                     "change": round(pb - pa, 2),
                     "change_pct": round((pb - pa) / abs(pa) * 100, 1) if pa else None,
                     "status": "new" if not pa and pb else "inactive" if pa and not pb
                     else "up" if pb > pa else "down",
                     "txn_ids": ids_b.get(k, []) + ids_a.get(k, [])})
    total = sum(r["change"] for r in rows)
    rows.sort(key=lambda r: -abs(r["change"]))
    same = [r for r in rows if r["change"] and (r["change"] > 0) == (total > 0)] if total else []
    opp = [r for r in rows if r["change"] and (r["change"] > 0) != (total > 0)] if total else []
    top1 = same[0]["change"] / total if same and total else 0.0
    top3 = sum(r["change"] for r in same[:3]) / total if same and total else 0.0
    return {"dimension": dim, "rows": rows, "total": round(total, 2), "members": len(rows),
            "same": same, "opposing": opp, "top1_share": round(top1, 4),
            "top3_share": round(top3, 4), "txn_count_current": cnt,
            "blank_share": round(sum(r["change"] for r in rows if r["name"] == "(blank)") / total, 3)
            if total else 0.0}


def _rank(ds, p0, p1, gate, policy):
    """Rank movements. Returns (investigate[], not_investigated[])."""
    s0, n0 = _summary_totals(ds, p0)
    s1, n1 = _summary_totals(ds, p1)
    t0, t1 = _account_totals(ds, p0), _account_totals(ds, p1)
    names = {}
    for t in ds.transactions:
        names.setdefault(t["account_key"], t["gl_account"])
    names.update(n0); names.update(n1)
    keys = set(s0) | set(s1) | set(t0) | set(t1)

    sec_move = defaultdict(float)
    rows = []
    for k in keys:
        prior = s0[k] if k in s0 else t0.get(k, 0.0)
        cur = s1[k] if k in s1 else t1.get(k, 0.0)
        sec = next((t["statement_section"] for t in ds.transactions if t["account_key"] == k), "Opex")
        v = cur - prior
        rows.append({"account": names.get(k, k), "key": k, "section": sec, "prior": round(prior, 2),
                     "current": round(cur, 2), "variance": round(v, 2),
                     "variance_pct": round(v / abs(prior) * 100, 2) if prior else None,
                     "zero_prior_base": prior == 0 and cur != 0,
                     "has_transactions": k in t0 or k in t1})
        sec_move[sec] += abs(v)
    sec_size = defaultdict(float)
    for r in rows:
        sec_size[r["section"]] += abs(r["prior"]) or abs(r["current"])

    hist_ok = gate["trend_allowed"]
    hist = defaultdict(list)
    if hist_ok:
        for p in ds.periods:
            if p < p1:
                tot = _account_totals(ds, p)
                for k in keys:
                    hist[k].append(tot.get(k, 0.0))

    investigate, skipped = [], []
    critical = {c.lower() for c in policy["critical_accounts"]}
    for r in rows:
        base = sec_size[r["section"]] or 1.0
        A = min(abs(r["variance"]) / (0.05 * base), 1.0)      # 5% of the section saturates
        tiny = abs(r["variance"]) < 0.01 * base
        P = min(abs(r["variance_pct"] or 0.0), 100.0) / 100.0
        z = 0.0
        if hist_ok and len(hist[r["key"]]) >= 6:
            from statistics import mean, pstdev
            mu, sd = mean(hist[r["key"]]), pstdev(hist[r["key"]])
            z = abs(r["current"] - mu) / sd if sd else 0.0
        H = min(z / 4.0, 1.0)
        C = min(abs(r["variance"]) / (sec_move[r["section"]] or 1.0), 1.0)
        score = 0.40 * A + 0.15 * P + 0.25 * H + 0.20 * C
        r.update({"score": round(score, 3), "historical_z": round(z, 2),
                  "components": {"absolute": round(A, 3), "percentage": round(P, 3),
                                 "historical": round(H, 3), "contribution": round(C, 3)}})

        overrides = []
        if r["account"].lower() in critical:
            overrides.append("critical account per policy")
        if r["zero_prior_base"] and abs(r["variance"]) >= policy["min_dollar"]:
            overrides.append("first activity in a previously unused account")
        if any(f["scope"].get("account") == r["account"] and f["code"] in
               ("PROBABLE_DUPLICATE", "DUPLICATE_TXN_ID", "EXTREME_OUTLIER") for f in gate["flags"]):
            overrides.append("data-quality flag on this account")

        if abs(r["variance"]) < policy["min_dollar"] and not overrides:
            r["reason"] = f"below policy minimum of {_money(policy['min_dollar'])} (moved {_money(r['variance'])})"
            skipped.append(r); continue
        if (score < 0.12 or (tiny and z < 2.0)) and not overrides:
            pct = f"{r['variance_pct']:+.0f}%" if r["variance_pct"] is not None else "n/a"
            r["reason"] = (f"immaterial: {_money(r['variance'])} ({pct}), "
                           f"{C:.0%} of its section's movement, z={z:.1f}")
            skipped.append(r); continue
        r["materiality"] = "high" if score >= 0.55 or overrides else "medium" if score >= 0.25 else "low"
        r["reason"] = "; ".join(overrides) if overrides else (
            f"score {score:.2f}: {_money(r['variance'])} is {C:.0%} of its section's movement"
            + (f", {z:.1f} sigma from its history" if z else ""))
        investigate.append(r)
    investigate.sort(key=lambda r: (-(1 if r["materiality"] == "high" else 0), -r["score"]))
    return investigate[:MAX_ACCOUNTS], skipped + investigate[MAX_ACCOUNTS:]


def run(case_dir, period, prior_period=None, memory_path=None, tracer=None, policy=None):
    ds = SimpleDataset(case_dir)
    prior_period = prior_period or ds.prior(period)
    tr = tracer or Tracer(enabled=True)
    pol = dict(DEFAULT_POLICY)
    pp = os.path.join(case_dir, "policy.json")
    if os.path.exists(pp):
        pol.update(json.load(open(pp)))
    if policy:
        pol.update(policy)
    tr.event("run_started", period=period, prior_period=prior_period)
    tr.event("data_loaded", transactions=len(ds.transactions), periods=len(ds.periods),
             dimensions=ds.dimensions)

    gate = run_gate(ds, period, prior_period)
    tr.event("data_quality", passed=gate["passed"], blockers=len(gate["blockers"]),
             warnings=len(gate["warnings"]))
    claims = ClaimSet()
    contradictions, memory_used, memory_rejected = [], [], []
    store = PriorStore(memory_path) if memory_path else None
    priors, rejected = (store.retrieve(period) if store else ([], []))
    memory_rejected = rejected
    tr.event("memory_retrieved", used=[p["id"] for p in priors], rejected=rejected)

    fatal = [f for f in gate["blockers"] if f["code"] in ("MISSING_COLUMNS", "MISSING_PERIOD")]
    if fatal:
        text = "Ledger Lens cannot analyse this period: " + "; ".join(f["detail"] for f in fatal) + "."
        c = claims.add(Claim(text, kind="abstention", detector="gate", confidence=1.0))
        tr.event("run_completed", abstained=True)
        return _result(period, prior_period, gate, [], [], claims, text + f" [{c.id}]",
                       assemble(gate, 0, 0, [], [], claims, blocked=True), {}, [], memory_rejected,
                       [], True, [], tr)

    investigate, not_inv = _rank(ds, prior_period, period, gate, pol)
    tr.event("variance_ranked", investigate=[r["account"] for r in investigate],
             skipped=len(not_inv))

    unexplained, abstained_scope = {}, []
    total_attr, total_var = 0.0, 0.0
    detector_findings = []
    sentences = []

    for r in investigate:
        acct, key, V = r["account"], r["key"], r["variance"]
        tr.event("investigation_started", account=acct, variance=V)
        # -- observation (always) ------------------------------------------
        if r["zero_prior_base"]:
            obs = (f"{acct} moved from $0 to {_money(r['current'])}; percentage change is not "
                   f"meaningful because the prior-period base was zero.")
        else:
            obs = (f"{acct} {'increased' if V > 0 else 'decreased'} from {_money(r['prior'])} to "
                   f"{_money(r['current'])}, a change of {_signed(V)}"
                   + (f" ({r['variance_pct']:+.1f}%)" if r["variance_pct"] is not None else "") + ".")
        c_obs = Claim(obs, account=acct, variance=V, kind="observation", calculation=
                      f"{r['current']:,.2f} - {r['prior']:,.2f} = {V:,.2f}", confidence=1.0,
                      numbers=[r["prior"], r["current"], V, r["variance_pct"]])
        c_obs.transaction_ids = ["summary"]      # observation is a summary-level fact
        claims.add(c_obs); sentences.append(f"{obs} [{c_obs.id}]")

        # -- blocked? -----------------------------------------------------------
        block = [f for f in gate["blockers"] if f["scope"].get("account") == acct]
        if block or not r["has_transactions"]:
            why = "; ".join(f["detail"] for f in block) if block else \
                  "no transaction records exist for this account"
            txt = f"Ledger Lens cannot reliably attribute {acct}: {why}."
            c = claims.add(Claim(txt, account=acct, kind="abstention", detector="gate", confidence=1.0,
                                 numbers=[f["scope"].get(k) for f in block for k in ("summary", "transactions", "gap", "amount")]
                                         + [a for f in block for a in (f["scope"].get("amounts") or [])]))
            sentences.append(f"{txt} [{c.id}]")
            abstained_scope.append(acct); unexplained[acct] = V
            tr.event("investigation_stopped", account=acct, reason="data quality blocker")
            continue

        total_var += abs(V)
        # -- reclass / reversal checks first (they change what V means) ----------
        for f in D.detect_reclass(ds, prior_period, period, min_amount=max(1000, abs(V) * 0.3)):
            if any(x["gl_account"] == acct for x in f["moved_out_of"] + f["moved_into"]):
                outs = ", ".join(x["gl_account_name"] for x in f["moved_out_of"])
                ins = ", ".join(x["gl_account_name"] for x in f["moved_into"])
                txt = (f"{_money(abs(f['amount']))} of {f['counterparty']} activity moved from {outs} to {ins} "
                       f"with no change in net activity; this is consistent with a reclassification "
                       f"rather than an economic change.")
                c = claims.add(Claim(txt, account=acct, variance=V, driver_amount=f["amount"] * (1 if V > 0 else -1),
                                     drivers=[f["counterparty"]], kind="attribution", detector="reclass",
                                     confidence=f["confidence"], numbers=[f["amount"]],
                                     transaction_ids=[t["txn_id"] for t in ds.txns(period)
                                                      if t["counterparty_name"] == f["counterparty"]][:10]))
                sentences.append(f"{txt} [{c.id}]"); detector_findings.append(f)
                total_attr += f["amount"]; tr.event("driver_found", account=acct, kind="reclass")
        for f in gate["flags"]:
            if f["code"] == "REVERSAL_PAIR" and f["scope"].get("account") == acct and f["scope"].get("cross_period"):
                amt = f["scope"]["amount"]
                txt = (f"{_money(amt)} of the movement in {acct} is the reversal of {f['scope']['transaction_ids'][0]} "
                       f"booked in {prior_period}; the underlying activity did not change by that amount.")
                c = claims.add(Claim(txt, account=acct, variance=V, driver_amount=-amt if V < 0 else amt,
                                     drivers=[f["scope"]["transaction_ids"][0]], kind="attribution",
                                     detector="reversal", confidence=0.9, numbers=[amt],
                                     transaction_ids=f["scope"]["transaction_ids"]))
                sentences.append(f"{txt} [{c.id}]"); total_attr += amt

        # -- single-transaction concentration -----------------------------------
        cur_rows = [t for t in ds.txns(period) if t["account_key"] == key]
        big = max(cur_rows, key=lambda t: abs(t["amount"]), default=None)
        if big and V and abs(big["amount"]) / abs(V) >= SINGLE_TXN_SHARE and \
                (big["amount"] > 0) == (V > 0):
            share = abs(big["amount"]) / abs(V)
            txt = (f"A single transaction, {big['txn_id']} ({big['counterparty_name']}, "
                   f"{_money(big['amount'])}), accounts for {share:.0%} of the movement in {acct}; "
                   f"the movement is not a broad increase across the account.")
            c = claims.add(Claim(txt, account=acct, variance=V, driver_amount=big["amount"],
                                 drivers=[big["counterparty_name"]], kind="attribution",
                                 detector="single_txn", confidence=1.0, numbers=[big["amount"], share * 100],
                                 calculation=f"{big['amount']:,.2f} / {V:,.2f} = {share:.1%}",
                                 transaction_ids=[big["txn_id"]]))
            sentences.append(f"{txt} [{c.id}]"); tr.event("driver_found", account=acct, kind="single_txn")

        # -- dimensional drill: choose the dimension that explains the most ------
        dims = [d for d in DIMS if d == "counterparty" or d in ds.dimensions]
        decs = {}
        for d in dims:
            dec = _decompose(ds, prior_period, period, key, d)
            tr.event("tool_called", tool="breakdown_by_dimension", account=acct, dimension=d,
                     top3_share=dec["top3_share"], members=dec["members"])
            if dec["blank_share"] > 0.5:
                continue                                   # dimension mostly missing: unusable
            decs[d] = dec
        best_d, best = max(decs.items(), key=lambda kv: kv[1]["top3_share"], default=(None, None))
        missing_dims = [d for d in ("segment", "department", "category", "product", "geography")
                        if d not in ds.dimensions]

        attributed_here = 0.0
        if best and best["total"]:
            # opposing movements that net out (§C14)
            gross_pos = sum(r["change"] for r in best["rows"] if r["change"] > 0)
            gross_neg = -sum(r["change"] for r in best["rows"] if r["change"] < 0)
            if gross_pos and gross_neg and min(gross_pos, gross_neg) >= 0.5 * max(gross_pos, gross_neg) \
                    and min(gross_pos, gross_neg) >= 0.2 * abs(V) and best["opposing"]:
                up = best["same"][0] if V > 0 else best["opposing"][0]
                dn = best["opposing"][0] if V > 0 else best["same"][0]
                if up["change"] < 0:
                    up, dn = dn, up
                txt = (f"The net movement in {acct} hides opposing changes by {best_d}: "
                       f"{up['name']} {_signed(up['change'])} against {dn['name']} {_signed(dn['change'])}; "
                       f"gross activity moved far more than the {_money(abs(V))} net figure suggests.")
                c = claims.add(Claim(txt, account=acct, variance=V, kind="attribution", detector="offset",
                                     drivers=[up["name"], dn["name"]], confidence=1.0, numbers=[up["change"], dn["change"], V],
                                     transaction_ids=(up["txn_ids"] + dn["txn_ids"])[:12]))
                c.driver_amount = None
                sentences.append(f"{txt} [{c.id}]"); tr.event("driver_found", account=acct, kind="offsetting")

            same = best["same"]
            if best["top3_share"] < DISTRIBUTED_TOP3 and best["members"] >= DISTRIBUTED_MIN_MEMBERS:
                txt = (f"The movement in {acct} is distributed across {best['members']} {best_d} values "
                       f"and {best['txn_count_current']} transactions with no dominant driver; the largest "
                       f"three explain {best['top3_share']:.0%}.")
                c = claims.add(Claim(txt, account=acct, variance=V, kind="attribution", detector="distributed",
                                     confidence=1.0, drivers=[r["name"] for r in same[:3]],
                                     numbers=[best["members"], best["txn_count_current"], best["top3_share"] * 100],
                                     transaction_ids=[i for r in same[:3] for i in r["txn_ids"]][:12]))
                sentences.append(f"{txt} [{c.id}]")
                tr.event("investigation_stopped", account=acct, reason="distributed movement")
            elif same:
                top = same[:3]
                amt = sum(r["change"] for r in top)
                share = amt / V
                names_ = ", ".join(r["name"] for r in top)
                # new / inactive wording (§C12, §C13)
                parts = []
                for drv in top:
                    if drv["status"] == "new":
                        parts.append(f"{drv['name']} had no activity in {prior_period} and {_money(drv['current'])} "
                                     f"in {period} (new {best_d})")
                    elif drv["status"] == "inactive":
                        parts.append(f"{drv['name']} had {_money(drv['prior'])} in {prior_period} and no activity in "
                                     f"{period}; the data does not establish whether the relationship ended")
                    else:
                        parts.append(f"{drv['name']} {_signed(drv['change'])}")
                txt = (f"By {best_d}, {'; '.join(parts)} — together {_money(amt)}, "
                       f"or {share:.0%} of the movement in {acct}.")
                c = claims.add(Claim(txt, account=acct, variance=V, driver_amount=amt,
                                     drivers=[r["name"] for r in top], kind="attribution",
                                     calculation=f"({' + '.join(f'{r['change']:,.0f}' for r in top)}) / {V:,.0f} = {share:.1%}",
                                     confidence=1.0,
                                     numbers=[amt, share * 100] + [x for d in top for x in (d["change"], d["current"], d["prior"])],
                                     transaction_ids=[i for r in top for i in r["txn_ids"]][:15]))
                sentences.append(f"{txt} [{c.id}]")
                attributed_here = abs(amt)
                tr.event("driver_found", account=acct, dimension=best_d, top3_share=best["top3_share"])
                # Drill one level deeper: a segment is not a driver, a customer is.
                # Stopping at "Enterprise +$158K" is the failure the brief names.
                if best_d != "counterparty":
                    lead = same[0]["name"]
                    sub = _decompose(ds, prior_period, period, key, "counterparty",
                                     where=lambda t, d=best_d, v=lead: (_dim_value(t, d) or "(blank)") == v)
                    tr.event("tool_called", tool="breakdown_by_dimension", account=acct,
                             dimension="counterparty", filter={best_d: lead}, depth=2,
                             top3_share=sub["top3_share"])
                    if sub["same"]:
                        s3 = sub["same"][:3]
                        amt2 = sum(x["change"] for x in s3)
                        share2 = amt2 / V
                        txt = (f"Within {lead}, by counterparty: "
                               + "; ".join(f"{x['name']} {_signed(x['change'])}" for x in s3)
                               + f" — together {_money(amt2)}, or {share2:.0%} of the total movement in {acct}.")
                        c5 = claims.add(Claim(txt, account=acct, variance=V, driver_amount=amt2,
                                              drivers=[x["name"] for x in s3], kind="attribution",
                                              calculation=f"({' + '.join(f'{x['change']:,.0f}' for x in s3)}) / {V:,.0f} = {share2:.1%}",
                                              confidence=1.0,
                                              numbers=[amt2, share2 * 100] + [x["change"] for x in s3],
                                              transaction_ids=[i for x in s3 for i in x["txn_ids"]][:15]))
                        sentences.append(f"{txt} [{c5.id}]")
                        names_ = ", ".join(x["name"] for x in s3)
                        tr.event("driver_found", account=acct, dimension="counterparty", depth=2,
                                 top3_share=sub["top3_share"])
                # concentration (§C30)
                if best["top1_share"] >= CONCENTRATION_SHARE:
                    txt = (f"The movement in {acct} is concentrated: {same[0]['name']} alone accounts for "
                           f"{best['top1_share']:.0%}; it is not broad-based.")
                    c2 = claims.add(Claim(txt, account=acct, variance=V, driver_amount=same[0]["change"],
                                          drivers=[same[0]["name"]], kind="attribution", detector="concentration",
                                          confidence=1.0, numbers=[best["top1_share"] * 100], transaction_ids=same[0]["txn_ids"][:10]))
                    sentences.append(f"{txt} [{c2.id}]")
                # outlier masking the rest (§C29)
                if same[0]["change"] / V > 1.0:
                    rest = V - same[0]["change"]
                    txt = (f"Excluding {same[0]['name']}, {acct} {'declined' if rest < 0 else 'rose'} by "
                           f"{_money(abs(rest))}; the headline movement depends entirely on that one {best_d}.")
                    c3 = claims.add(Claim(txt, account=acct, variance=V, driver_amount=rest, kind="attribution",
                                          detector="masking", drivers=[same[0]["name"]], confidence=1.0, numbers=[rest],
                                          calculation=f"{V:,.0f} - {same[0]['change']:,.0f} = {rest:,.0f}",
                                          transaction_ids=[i for r in same[1:6] for i in r["txn_ids"]][:10]
                                          or same[0]["txn_ids"][:3]))
                    sentences.append(f"{txt} [{c3.id}]")
                # causal abstention: attribution is not explanation
                if share >= 0.5 and not any(p.get("scope", {}).get("account", "").lower() == acct.lower()
                                            for p in priors):
                    txt = f"The available data does not establish why {names_} activity changed."
                    c4 = claims.add(Claim(txt, account=acct, kind="abstention", confidence=1.0))
                    c4.transaction_ids = ["n/a"]
                    sentences.append(f"{txt} [{c4.id}]")
        if missing_dims and best and best["top3_share"] < TOP3_COVERAGE:
            txt = (f"Attribution of {acct} is limited to {', '.join(decs.keys())}: the data carries no "
                   f"{', '.join(missing_dims[:3])} field.")
            c = claims.add(Claim(txt, account=acct, kind="limitation", confidence=1.0)); c.transaction_ids = ["n/a"]
            sentences.append(f"{txt} [{c.id}]")

        # -- seasonality (only with enough history) -------------------------------
        # "Is this normal?" is answered the way a controller answers it: what did
        # this calendar month do in prior years? A +40% December is not an event
        # if the last two Decembers were +41% and +39%.
        if gate["seasonality_allowed"] and r["section"] in ("Revenue",) and abs(V) > 0 \
                and r["variance_pct"] is not None:
            import calendar
            from statistics import mean, pstdev
            mname = calendar.month_name[int(period[5:])]
            prior_years = []
            for back in (12, 24, 36):
                pa, pb = _shift_period(period, -back - 1), _shift_period(period, -back)
                if pa in ds.periods and pb in ds.periods:
                    ta = sum(t["amount"] for t in ds.txns(pa) if t["account_key"] == key)
                    tb = sum(t["amount"] for t in ds.txns(pb) if t["account_key"] == key)
                    if ta:
                        prior_years.append(round((tb - ta) / abs(ta) * 100, 1))
            tr.event("tool_called", tool="compare_same_month_history", account=acct, prior_years=prior_years)
            if prior_years:
                tol = max(10.0, 1.5 * (pstdev(prior_years) if len(prior_years) > 1 else 0.0))
                normal = abs(r["variance_pct"] - mean(prior_years)) <= tol
                hist_txt = " and ".join(f"{x:+.0f}%" for x in prior_years)
                txt = (f"This movement is {'large but historically normal' if normal else 'outside its historical pattern'}: "
                       f"{mname} moved {r['variance_pct']:+.0f}% this year against {hist_txt} in the "
                       f"{len(prior_years)} prior year{'s' if len(prior_years) > 1 else ''}.")
                c = claims.add(Claim(txt, account=acct, kind="context", detector="seasonality", confidence=0.85,
                                     numbers=[r["variance_pct"]] + prior_years + [len(prior_years)]))
                c.transaction_ids = ["n/a"]
                sentences.append(f"{txt} [{c.id}]")

        # -- one-time items ---------------------------------------------------------
        if gate["trend_allowed"]:
            for f in D.detect_one_time(ds, period, min_amount=max(1000, abs(V) * 0.3)):
                if f["gl_account"] == acct:
                    txt = (f"{acct} contains a non-recurring item of {_money(f['excess'])} "
                           f"({f['z_score']:.0f} sigma above its own history); it should not be extrapolated.")
                    c = claims.add(Claim(txt, account=acct, kind="attribution", detector="one_time",
                                         confidence=f["confidence"], driver_amount=f["excess"], variance=V, numbers=[f["excess"], f["z_score"]],
                                         transaction_ids=[e["txn_id"] for e in f["evidence"]]))
                    sentences.append(f"{txt} [{c.id}]"); detector_findings.append(f)

        # -- memory: use, verify, or reject ------------------------------------------
        for p in priors:
            if (p.get("scope", {}).get("account") or "").lower() != acct.lower():
                continue
            memory_used.append(p["id"])
            exp = p.get("expectation") or {}
            pct = r["variance_pct"]
            if exp.get("max_increase_pct") is not None and pct is not None:
                if pct <= exp["max_increase_pct"]:
                    txt = (f"This movement is consistent with the reviewer-provided context in {p['id']} "
                           f"({p['statement']}); the observed {pct:+.1f}% is within the anticipated range of "
                           f"up to +{exp['max_increase_pct']:.0f}%.")
                else:
                    txt = (f"{p['id']} anticipated increases of at most +{exp['max_increase_pct']:.0f}% "
                           f"({p['statement']}); the observed {pct:+.1f}% exceeds that range, so the learned "
                           f"context does not explain this movement and it is treated as an exception.")
                    contradictions.append({"description": f"{acct} exceeds range in {p['id']}",
                                           "sources": [p["id"], "current period"]})
            elif exp.get("direction"):
                agrees = (exp["direction"] == "down") == (V < 0)
                if agrees:
                    txt = f"This movement is consistent with {p['id']}: {p['statement']}."
                else:
                    txt = (f"The available sources conflict: {p['id']} states that {p['statement']}, "
                           f"but {acct} moved {_signed(V)} in the opposite direction. "
                           f"The prior is marked contested and confidence is reduced.")
                    contradictions.append({"description": f"{p['id']} contradicted by {acct} movement",
                                           "sources": [p["id"], "current period"]})
                    if store:
                        store.set_status(p["id"], "contested", note=f"contradicted in {period}", by="system")
            else:
                txt = f"Context from memory {p['id']} applies: {p['statement']}."
            c = claims.add(Claim(txt, account=acct, kind="context", prior_ids=[p["id"]],
                                 confidence=p["confidence"],
                                 numbers=[r["variance_pct"], (p.get("expectation") or {}).get("max_increase_pct"), V]))
            c.transaction_ids = ["n/a"]
            sentences.append(f"{txt} [{c.id}]")
        for rj in rejected:
            if store:
                pr = next((x for x in store.priors if x["id"] == rj["id"]), None)
                if pr and (pr.get("scope", {}).get("account") or "").lower() == acct.lower():
                    txt = f"{rj['id']} ({pr['statement']}) was not applied: {rj['reason']}."
                    c = claims.add(Claim(txt, account=acct, kind="context", confidence=1.0)); c.transaction_ids = ["n/a"]
                    sentences.append(f"{txt} [{c.id}]")

        # -- residual -------------------------------------------------------------------
        attr_total = attributed_here
        resid = max(abs(V) - attr_total, 0.0) if attr_total else abs(V)
        if best and best["top3_share"] >= 0.999:
            resid = 0.0
        share = resid / abs(V) if V else 0.0
        if share >= UNEXPLAINED_REPORT_SHARE and not (best and best["top3_share"] < DISTRIBUTED_TOP3
                                                      and best["members"] >= DISTRIBUTED_MIN_MEMBERS):
            txt = (f"{_money(resid)} ({share:.0%}) of the movement in {acct} is not attributed to any "
                   f"identified driver.")
            c = claims.add(Claim(txt, account=acct, kind="residual", confidence=1.0, driver_amount=resid, variance=V,
                                 numbers=[resid, share * 100]))
            c.transaction_ids = ["n/a"]
            sentences.append(f"{txt} [{c.id}]")
        unexplained[acct] = round(resid, 2)
        total_attr += attr_total
        tr.event("investigation_stopped", account=acct,
                 reason=f"top3 {best['top3_share']:.0%}" if best else "no decomposition")

    if store:
        store.save()

    if not investigate:
        txt = "No financially material or historically unusual movements were identified for this period."
        c = claims.add(Claim(txt, kind="observation", confidence=1.0)); c.transaction_ids = ["summary"]
        sentences.append(f"{txt} [{c.id}]")

    narrative = " ".join(sentences)
    violations = lint(narrative, [c.to_dict() for c in claims.verified()])
    if violations:
        bad = {v.get("sentence") for v in violations if v.get("sentence")}
        narrative = " ".join(s for s in sentences if s not in bad)
        tr.event("claim_rejected", violations=violations)

    blocked = bool(abstained_scope) or not gate["passed"]
    conf = assemble(gate, total_var, total_attr, priors, detector_findings, claims,
                    contradictions=len(contradictions), blocked=blocked and bool(abstained_scope))
    tr.event("explanation_generated", claims=len(claims.claims), verified=len(claims.verified()),
             confidence=conf["overall"])
    tr.event("run_completed", abstained=bool(abstained_scope))
    return _result(period, prior_period, gate, investigate, not_inv, claims, narrative, conf,
                   unexplained, memory_used, memory_rejected, contradictions,
                   bool(abstained_scope) or not investigate and not gate["passed"], abstained_scope, tr)


def _result(period, prior, gate, inv, not_inv, claims, narrative, conf, unexplained,
            mem_used, mem_rej, contradictions, abstained, scope, tr):
    return {
        "period": period, "prior_period": prior,
        "data_quality": {"passed": gate["passed"], "data_confidence": gate["data_confidence"],
                         "flags": gate["flags"], "blocked_accounts": gate["blocked_accounts"]},
        "material_variances": [{k: r.get(k) for k in ("account", "prior", "current", "variance",
                                                       "variance_pct", "materiality", "score", "reason",
                                                       "historical_z", "components")} for r in inv],
        "not_investigated": [{"account": r["account"], "variance": r["variance"], "reason": r["reason"]}
                             for r in not_inv],
        "claims": claims.to_dict()["claims"],
        "narrative": narrative,
        "confidence": conf,
        "unexplained": unexplained,
        "memory_used": sorted(set(mem_used)),
        "memory_rejected": mem_rej,
        "contradictions": contradictions,
        "abstained": abstained,
        "abstained_scope": scope,
        "trace": tr.summary(),
    }
