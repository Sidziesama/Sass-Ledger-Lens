"""Adapter: score the `main` branch "Financial Variance Courtroom" (JavaScript) with the benchmark.

    COURTROOM_ROOT=/path/to/main-checkout \\
    python -m reliability.benchmark.evaluate --runner reliability.benchmark.adapters.courtroom_v1:run
    ...                                    --runner reliability.benchmark.adapters.courtroom_v1:run_normalized

Their engine (`engine.mjs`) takes {summaries:[{month,account,amount}],
transactions:[{id,date,month,account,counterparty,segment,category,amount,status:"posted"}]}
and requires every one of those transaction fields. Two modes:

  run             maps the canonical CSV columns 1:1 and leaves anything missing
                  blank -- their schema check decides (measures ingestion strictness)
  run_normalized  fills segment/category with "Unspecified", derives a date from the
                  period when absent, formats amounts to two decimals -- measures the
                  investigator, not the column contract

Nothing of theirs is modified; the engine is imported from COURTROOM_ROOT.
The prose in the RunResult is their engine's own claim text.
"""

import csv
import json
import os
import re
import subprocess
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
RUNNER = os.path.join(HERE, "courtroom_runner.mjs")
_NUM = re.compile(r"[-+]?\$?\d[\d,]*(?:\.\d+)?")

ISSUE_TO_FLAG = {"conflict": "DUPLICATE_TXN_ID", "duplicate": "DUPLICATE_TXN_ID", "currency": "MIXED_CURRENCY",
                 "date": "MALFORMED_DATE", "amount": "UNPARSEABLE_AMOUNT", "schema": "MISSING_COLUMNS",
                 "status": "CORRUPT_ROW"}


def _root():
    r = os.environ.get("COURTROOM_ROOT")
    if not r or not os.path.exists(os.path.join(r, "engine.mjs")):
        raise RuntimeError("set COURTROOM_ROOT to a checkout of main containing engine.mjs")
    return r


def _read(path):
    with open(path, newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def _nums(text):
    out = []
    for tok in _NUM.findall(text or ""):
        try:
            out.append(float(tok.replace("$", "").replace(",", "")))
        except ValueError:
            pass
    return out


def _build(case_dir, normalized):
    if normalized:
        from reliability.ingestion.normalize import SimpleDataset
        ds = SimpleDataset(case_dir)
        summaries = [{"month": s["period"], "account": s["account"], "amount": f"{s['amount']:.2f}"} for s in ds.summary]
        txns = [{"id": t["txn_id"], "date": t["date"] if t["date_ok"] else f"{t['period']}-15",
                 "month": t["period"], "account": t["gl_account"], "counterparty": t["counterparty_name"] or "Unspecified",
                 "segment": t.get("segment") or "Unspecified", "category": t.get("category") or "Unspecified",
                 "amount": f"{t['amount']:.2f}", "status": "posted",
                 **({"currency": t["currency"]} if t.get("currency") else {})} for t in ds.transactions]
    else:
        summaries = [{"month": r.get("period", ""), "account": r.get("account", ""), "amount": r.get("amount", "")}
                     for r in _read(os.path.join(case_dir, "monthly_summary.csv"))]
        txns = []
        for r in _read(os.path.join(case_dir, "transactions.csv")):
            row = {"id": r.get("transaction_id", ""), "date": r.get("date", ""), "month": r.get("period", "") or r.get("date", "")[:7],
                   "account": r.get("account", ""), "counterparty": r.get("counterparty", ""),
                   "segment": r.get("segment", ""), "category": r.get("category", ""),
                   "amount": r.get("amount", ""), "status": "posted"}
            if r.get("currency"):
                row["currency"] = r["currency"]
            txns.append(row)
    return {"summaries": summaries, "transactions": txns, "aliases": {}, "context": []}


def _memory_context(memory_path):
    """Their memory model: reviewer-approved entries with a validity window; a
    'cloud-baseline' carries an expected amount per period. Map what maps."""
    if not memory_path or not os.path.exists(memory_path):
        return [], {}
    with open(memory_path) as f:
        priors = json.load(f).get("priors", [])
    ctx, idmap = [], {}
    for p in priors:
        if p.get("status") in ("rejected", "superseded"):
            continue
        a = p.get("applies_to") or {}
        entry = {"id": p["id"], "kind": "context", "account": (p.get("scope") or {}).get("account", ""),
                 "title": p["statement"][:80], "detail": p["statement"],
                 "approved": p.get("source_type") == "user_verified" or p.get("status") == "confirmed",
                 "source": p.get("source", "system"), "validFrom": a.get("from_period") or "2000-01",
                 "validThrough": a.get("to_period") or "2099-12"}
        exp = p.get("expectation") or {}
        if exp.get("max_increase_pct") is not None:
            entry["kind"] = "cloud-baseline"
        ctx.append(entry); idmap[p["id"]] = entry
    return ctx, idmap


def _run(case_dir, period, prior_period, memory_path=None, normalized=False):
    root = _root()
    data = _build(case_dir, normalized)
    data["context"], idmap = _memory_context(memory_path)
    tmp = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False)
    json.dump(data, tmp); tmp.close()
    try:
        out = subprocess.run(["node", RUNNER, root, tmp.name, prior_period, period],
                             capture_output=True, text=True, timeout=120)
    finally:
        os.unlink(tmp.name)
    try:
        r = json.loads(out.stdout or "{}")
    except json.JSONDecodeError:
        r = {"error": (out.stderr or out.stdout)[:300]}
    if "error" in r:
        return _abstain(period, prior_period, r["error"])

    flags, blocked = [], []
    for i in r["issues"]:
        flags.append({"code": ISSUE_TO_FLAG.get(i["code"], "CORRUPT_ROW"), "severity": "warning",
                      "detail": f"{i['id']}: {i['message']}", "scope": {"account": i["account"], "transaction_id": i["id"]}})
    for q in r["quarantine"]:
        flags.append({"code": "DUPLICATE_TXN_ID", "severity": "warning", "detail": f"{q['id']}: {q['reason']}",
                      "scope": {"account": q["account"], "transaction_id": q["id"]}})
    for a in r["accounts"]:
        for t in a["ties"]:
            if t["ok"]:
                continue
            code = ("NO_TRANSACTIONS_FOR_ACCOUNT" if t["count"] == 0 and t.get("gap") not in (None, 0) else
                    "CONFLICTING_SUMMARY" if "Exactly one summary" in (t["reason"] or "") and t["count"] > 0 else
                    "MISSING_PERIOD" if "Exactly one summary" in (t["reason"] or "") else
                    "RECONCILIATION_GAP")
            flags.append({"code": code, "severity": "blocker", "detail": f"{a['account']} {t['month']}: {t['reason']}",
                          "scope": {"account": a["account"], "period": t["month"], "gap": (t.get("gap") or 0) / 100}})
        if not a["valid"]:
            blocked.append(a["account"])

    material = [{"account": a["account"], "prior": (a["previous"] or 0) / 100, "current": (a["current"] or 0) / 100,
                 "variance": (a["delta"] or 0) / 100, "variance_pct": a["percent"], "materiality": "high",
                 "score": a["score"], "reason": "delta >= $10,000 (engine policy)", "historical_z": None, "components": None}
                for a in r["accounts"] if a["material"]]
    not_inv = [{"account": a["account"], "variance": (a["delta"] or 0) / 100, "reason": "below $10,000 engine threshold"}
               for a in r["accounts"] if not a["material"]]

    claims, sentences, unexplained = [], [], {}
    acct_delta = {a["account"]: (a["delta"] or 0) / 100 for a in r["accounts"]}
    for c in r["claims"]:
        kind = {"movement": "observation", "drivers": "attribution", "broad-growth": "attribution",
                "cloud-context": "context", "cloud-exclusive": "causal", "causal": "causal"}.get(c["type"], "attribution")
        verified = c["status"] in ("approved", "qualified")
        drivers = [d["name"] for d in c.get("drivers", [])[:3]] if c["type"] == "drivers" else []
        top3 = sum(d["delta"] for d in c.get("drivers", [])[:3]) / 100 if c["type"] == "drivers" else None
        claims.append({"claim_id": c["id"], "claim": f"{c['title']}. {c['text']}".strip(". ") + ".", "kind": kind,
                       "account": c["account"], "variance": acct_delta.get(c["account"]),
                       "driver_amount": top3, "contribution_pct": None, "drivers": drivers,
                       "transaction_ids": c["rowIds"] or ["summary"], "calculation": c.get("formula"),
                       "detector": f"courtroom:{c['type']}", "confidence": 1.0, "supporting_priors": [],
                       "verified": verified, "verification_note": f"engine status {c['status']}",
                       "numbers": _nums(c["text"]) + _nums(c.get("formula") or "")})
        if verified:
            sentences.append(f"{c['text']} [{c['id']}]")
        if c["type"] == "drivers" and verified and acct_delta.get(c["account"]):
            unexplained[c["account"]] = round(abs(acct_delta[c["account"]] - (top3 or 0)), 2)

    mem_used = [m["id"] for m in r["memories"] if m["status"] == "active" and m["id"] in idmap]
    mem_rej = [{"id": m["id"], "reason": m["reason"]} for m in r["memories"] if m["status"] != "active" and m["id"] in idmap]
    mat_blocked = [a for a in blocked if any(m["account"] == a for m in material)]
    total_var = sum(abs(m["variance"]) for m in material) or 0.0
    total_unexp = sum(unexplained.get(m["account"], abs(m["variance"])) for m in material)
    attr = (1 - total_unexp / total_var) if total_var else 0.0
    overall = "low" if mat_blocked else ("high" if attr >= 0.8 and sentences else "medium" if sentences else "low")
    return {
        "period": period, "prior_period": prior_period,
        "data_quality": {"passed": not blocked, "data_confidence": 1.0 if not flags else 0.6, "flags": flags,
                         "blocked_accounts": blocked},
        "material_variances": material, "not_investigated": not_inv, "claims": claims,
        "narrative": " ".join(sentences) or "No approved or qualified claims.",
        "confidence": {"data": 1.0 if not blocked else 0.3, "attribution": round(max(attr, 0.0), 3), "context": 0.35,
                       "evidence_coverage_pct": r.get("coverage"), "unexplained_amount": round(total_unexp, 2),
                       "unexplained_share": round(total_unexp / total_var, 3) if total_var else None,
                       "contradictions": 0, "overall": overall, "reasons": [f"{r['rejected']} rejected, {r['blocked']} blocked"]},
        "unexplained": unexplained, "memory_used": mem_used, "memory_rejected": mem_rej, "contradictions": [],
        "abstained": bool(mat_blocked), "abstained_scope": mat_blocked,
        "trace": {"tool_calls": len(r["claims"]), "runner": "main courtroom (JS)"},
    }


def _abstain(period, prior_period, why):
    txt = f"LedgerLens courtroom could not analyse this period: {why}."
    code = "MISSING_PERIOD" if "period" in why.lower() else "MISSING_COLUMNS" if "row needs" in why.lower() or "evidence" in why.lower() else "CORRUPT_ROW"
    return {"period": period, "prior_period": prior_period,
            "data_quality": {"passed": False, "data_confidence": 0.0, "blocked_accounts": [],
                             "flags": [{"code": code, "severity": "blocker", "detail": why, "scope": {}}]},
            "material_variances": [], "not_investigated": [],
            "claims": [{"claim_id": "claim_001", "claim": txt, "kind": "abstention", "account": None, "variance": None,
                        "driver_amount": None, "contribution_pct": None, "drivers": [], "transaction_ids": ["n/a"],
                        "calculation": None, "detector": "engine", "confidence": 1.0, "supporting_priors": [],
                        "verified": True, "verification_note": "", "numbers": []}],
            "narrative": f"{txt} [claim_001]",
            "confidence": {"data": 0.0, "attribution": 0.0, "context": 0.0, "evidence_coverage_pct": None,
                           "unexplained_amount": None, "unexplained_share": None, "contradictions": 0,
                           "overall": "low", "reasons": [why]},
            "unexplained": {}, "memory_used": [], "memory_rejected": [], "contradictions": [],
            "abstained": True, "abstained_scope": [], "trace": {"tool_calls": 0, "runner": "main courtroom (JS)"}}


def run(case_dir, period, prior_period, memory_path=None):
    return _run(case_dir, period, prior_period, memory_path, normalized=False)


def run_normalized(case_dir, period, prior_period, memory_path=None):
    return _run(case_dir, period, prior_period, memory_path, normalized=True)
