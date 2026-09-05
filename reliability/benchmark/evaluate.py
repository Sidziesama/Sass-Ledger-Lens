"""Benchmark evaluator. Runs every case against a system-under-test and scores it.

    python -m benchmark.evaluate                 # reference investigator
    python -m benchmark.evaluate --runner pkg.mod:fn   # any callable with the
                                                 # signature run(case_dir, period,
                                                 # prior_period, memory_path)

Every check is machine-evaluable. A failed check is mapped to a failure class
from the taxonomy so the Observe -> Improve -> Prove loop has something to act on.
"""

import argparse
import csv
import importlib
import json
import os
import re
import shutil
import sys
import tempfile
from collections import Counter, defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, ROOT)

from reliability.benchmark.schema import GROUND_TRUTH_DEFAULTS, validate_result       # noqa: E402
from reliability.benchmark.taxonomy import classify                                    # noqa: E402
from reliability.policy.language import lint                                  # noqa: E402
from reliability.memory.store import PriorStore                                 # noqa: E402


def apply_feedback(memory_path, ops):
    """Reviewer actions between runs, applied to the shared memory file."""
    if not ops:
        return
    store = PriorStore(memory_path)
    for op in ops:
        kind = op["op"]
        if kind == "add":
            store.add(op["type"], op["scope"], op["statement"], op.get("implication", ""),
                      {"source": "reviewer_feedback"}, op.get("confidence", 0.9),
                      source_type=op.get("source_type", "user_verified"), source="finance_reviewer",
                      valid_from=op.get("valid_from"), valid_until=op.get("valid_until"),
                      expectation=op.get("expectation"), status="confirmed")
        elif kind in ("confirm", "reject", "contest"):
            store.set_status(op["id"], {"confirm": "confirmed", "reject": "rejected", "contest": "contested"}[kind],
                             note=op.get("note"), by="finance_reviewer")
        elif kind == "correct":
            store.correct(op["id"], op["statement"], op.get("implication"), note=op.get("note"))
    store.save()


def run_sequence(case, runner):
    """Run every step against one memory file; score the steps that ask to be scored."""
    mem = os.path.join(tempfile.mkdtemp(), "memory.json")
    seed = os.path.join(case["dir"], "memory.json")
    if os.path.exists(seed):
        shutil.copy(seed, mem)
    else:
        PriorStore(mem).save()
    merged = {"checks": {}, "failed": [], "classes": []}
    last_result = None
    for i, st in enumerate(case["sequence"]["steps"], 1):
        apply_feedback(mem, st["feedback"])
        result = runner(case["dir"], st["period"], st["prior_period"], mem)
        last_result = result
        if not st.get("score", True):
            continue
        sc = score({"ground_truth": st["ground_truth"]}, result, case["dir"])
        for k, v in sc["checks"].items():
            merged["checks"][f"step{i}:{k}"] = v
        merged["failed"] += [f"step{i}:{k}" for k in sc["failed"]]
        merged["classes"] += sc["classes"]
    merged["classes"] = sorted(set(merged["classes"]))
    merged["passed"] = not merged["failed"]
    n = len(merged["checks"]) or 1
    merged["score"] = round((n - len(merged["failed"])) / n, 3)
    merged["memory_final"] = PriorStore(mem).summary()
    return merged, last_result


def load_cases(root=os.path.join(HERE, "cases"), only=None):
    out = []
    for d in sorted(os.listdir(root)):
        cj = os.path.join(root, d, "case.json")
        if os.path.exists(cj) and (not only or only in d):
            with open(cj) as f:
                case = json.load(f)
            gt = dict(GROUND_TRUTH_DEFAULTS); gt.update(case.get("ground_truth", {}))
            case["ground_truth"] = gt
            case["dir"] = os.path.join(root, d)
            sj = os.path.join(root, d, "sequence.json")
            if os.path.exists(sj):
                with open(sj) as f:
                    case["sequence"] = json.load(f)
            out.append(case)
    return out


def _txn_index(case_dir):
    ids, by_acct = set(), defaultdict(lambda: defaultdict(float))
    from reliability.ingestion.normalize import SimpleDataset
    ds = SimpleDataset(case_dir)
    for t in ds.transactions:
        ids.add(t["txn_id"]); by_acct[t["gl_account"].lower()][t["period"]] += t["amount"]
    summ, seen = defaultdict(dict), defaultdict(set)
    for s in ds.summary:
        a = s["account"].lower()
        seen[(a, s["period"])].add(round(s["amount"], 2))
        summ[a][s["period"]] = summ[a].get(s["period"], 0) + s["amount"]
    # conflicting summary rows: the "true" figure is undefined, so do not use it
    for (a, p), vals in seen.items():
        if len(vals) > 1:
            summ[a].pop(p, None)
    return ids, by_acct, summ


def score(case, result, case_dir):
    gt = case["ground_truth"]
    checks = {}
    def chk(name, passed, detail=""):
        checks[name] = {"passed": bool(passed), "detail": detail}

    missing = validate_result(result)
    chk("contract", not missing, f"missing fields: {missing}" if missing else "ok")
    if missing:
        return _finish(checks)

    narrative = result.get("narrative") or ""
    claims = result.get("claims") or []
    verified = [c for c in claims if c.get("verified")]
    all_text = narrative + " " + " ".join(c.get("claim", "") for c in claims)
    flags = {f["code"] for f in result["data_quality"]["flags"]}
    investigated = [m["account"] for m in result["material_variances"]]
    inv_l = {a.lower() for a in investigated}

    # data quality
    exp = set(gt["expected_data_quality_flags"])
    chk("data_quality_flags", exp <= flags, f"expected {sorted(exp)}, got {sorted(flags & exp)}; all flags {sorted(flags)}")
    bad = set(gt["expected_no_data_quality_flags"]) & flags
    chk("no_false_flags", not bad, f"unexpected flags {sorted(bad)}" if bad else "ok")
    if "RECONCILIATION_GAP" in exp:
        chk("reconciliation_detected", "RECONCILIATION_GAP" in flags)

    # materiality
    miss = [a for a in gt["expected_material_variances"] if a.lower() not in inv_l]
    chk("material_variances", not miss, f"not investigated: {miss}; investigated {investigated}")
    wrong = [a for a in gt["expected_immaterial"] if a.lower() in inv_l]
    chk("immaterial_ignored", not wrong, f"investigated immaterial: {wrong}" if wrong else "ok")

    # drivers
    for acct, drivers in gt["expected_top_drivers"].items():
        found = []
        for d in drivers:
            hit = any(d.lower() in " ".join(c.get("drivers") or []).lower() or d.lower() in c.get("claim", "").lower()
                      for c in verified if (c.get("account") or "").lower() == acct.lower())
            found.append(hit)
        chk(f"top_drivers[{acct}]", all(found),
            f"expected {drivers}, found {[d for d, h in zip(drivers, found) if h]}")

    # unexplained
    if gt["expected_unexplained_min_share"] is not None:
        sh = result["confidence"].get("unexplained_share") or 0
        ok = sh >= gt["expected_unexplained_min_share"] or bool(re.search(r"not attributed to any identified driver", all_text))
        chk("unexplained_amount", ok, f"unexplained share {sh}")

    # language
    for ph in gt["forbidden_claims"]:
        chk(f"forbidden_claim[{ph[:30]}]", ph.lower() not in all_text.lower())
    for rx in gt["forbidden_patterns"]:
        m = re.search(rx, all_text, re.I)
        chk(f"forbidden_pattern[{rx[:30]}]", not m, f"matched: {m.group(0)!r}" if m else "ok")
    for rx in gt["required_patterns"]:
        chk(f"required_pattern[{rx[:30]}]", re.search(rx, all_text, re.I) is not None)
    viol = lint(narrative, verified, [c["claim_id"] for c in verified if c.get("kind") == "causal"])
    chk("causal_lint", not [v for v in viol if v["type"] == "UNSUPPORTED_CAUSALITY"],
        json.dumps([v for v in viol if v["type"] == "UNSUPPORTED_CAUSALITY"])[:200])
    chk("number_lint", not [v for v in viol if v["type"] in ("UNGROUNDED_NUMBER", "FALSE_PRECISION", "NONSENSE_FIGURE")],
        json.dumps([v for v in viol if v["type"] != "UNSUPPORTED_CAUSALITY"])[:200])

    # confidence + abstention
    chk("confidence", result["confidence"]["overall"] in gt["acceptable_confidence"],
        f"got {result['confidence']['overall']}, acceptable {gt['acceptable_confidence']}")
    chk("abstention", bool(result["abstained"]) == bool(gt["expected_abstention"]),
        f"abstained={result['abstained']}, expected={gt['expected_abstention']}")
    sc = {a.lower() for a in result.get("abstained_scope", [])}
    miss_scope = [a for a in gt["expected_abstention_scope"] if a.lower() not in sc]
    chk("abstention_scope", not miss_scope, f"missing scope {miss_scope}" if miss_scope else "ok")

    # memory
    mu = set(result.get("memory_used") or [])
    mr = {r["id"] for r in result.get("memory_rejected") or []}
    chk("memory_used", set(gt["expected_memory_usage"]) <= mu, f"used {sorted(mu)}")
    chk("memory_rejected", set(gt["expected_memory_rejected"]) <= mr and not (set(gt["expected_memory_rejected"]) & mu),
        f"rejected {sorted(mr)}, used {sorted(mu)}")

    # lineage: cited transaction ids must exist; arithmetic: observations must reproduce
    ids, by_acct, summ = _txn_index(case_dir)
    bad_ids = [i for c in verified for i in c.get("transaction_ids", []) if i not in ids and i not in ("summary", "n/a")]
    chk("lineage", not bad_ids, f"cited ids not in records: {bad_ids[:5]}" if bad_ids else "ok")
    arith_bad = []
    for c in verified:
        if c.get("kind") == "observation" and c.get("account") and c.get("variance") is not None:
            a = c["account"].lower()
            src = summ.get(a) or {}
            if result["period"] not in src or result["prior_period"] not in src:
                src = by_acct.get(a) or {}
            truth = src.get(result["period"], 0.0) - src.get(result["prior_period"], 0.0)
            if abs(truth - c["variance"]) > 1.0:
                arith_bad.append((c["account"], c["variance"], round(truth, 2)))
    chk("arithmetic", not arith_bad, f"mismatch: {arith_bad}" if arith_bad else "ok")

    tc = result.get("trace", {}).get("tool_calls", 0)
    chk("tool_budget", tc <= gt["max_tool_calls"], f"{tc} calls, max {gt['max_tool_calls']}")
    return _finish(checks)


def _finish(checks):
    failed = [k for k, v in checks.items() if not v["passed"]]
    base = [k.split("[")[0] for k in failed]
    return {"checks": checks, "failed": failed, "passed": not failed,
            "classes": classify(base), "score": round((len(checks) - len(failed)) / len(checks), 3)}


def resolve_runner(spec):
    if not spec:
        from reliability.agent.reference import run
        return run, "reference"
    mod, fn = spec.split(":")
    return getattr(importlib.import_module(mod), fn), spec


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--runner", default=None)
    ap.add_argument("--only", default=None)
    ap.add_argument("--out", default=os.path.join(HERE, "results"))
    ap.add_argument("-v", "--verbose", action="store_true")
    ap.add_argument("--llm", action="store_true",
                    help="also have GIDE's model draft each memo; report how many drafts the linter rejects")
    args = ap.parse_args(argv)
    runner, rname = resolve_runner(args.runner)
    llm = None
    memo_stats = Counter()
    if args.llm:
        from reliability.agent.llm import LLM
        from reliability.agent.memo import write_memo
        llm = LLM()
        print(f"model memo mode: {llm.describe()}")
    os.makedirs(args.out, exist_ok=True)
    cases = load_cases(only=args.only)
    rows, class_hist, cat_stats = [], Counter(), defaultdict(lambda: [0, 0])
    for case in cases:
        mem = os.path.join(case["dir"], "memory.json")
        mem_tmp = None
        if os.path.exists(mem):
            mem_tmp = os.path.join(tempfile.mkdtemp(), "memory.json"); shutil.copy(mem, mem_tmp)
        try:
            if case.get("sequence"):
                sc, result = run_sequence(case, runner)
            else:
                result = runner(case["dir"], case["period"], case["prior_period"], mem_tmp)
                sc = score(case, result, case["dir"])
            err = None
        except Exception as e:                            # noqa: BLE001
            import traceback
            result, err = None, f"{type(e).__name__}: {e}\n{traceback.format_exc()[-600:]}"
        if err:
            sc = {"checks": {"tool_error": {"passed": False, "detail": err}}, "failed": ["tool_error"],
                  "passed": False, "classes": ["TOOL_FAILURE"], "score": 0.0}
        memo = None
        if llm is not None and result and result.get("claims"):
            memo = write_memo(llm, result)
            if any(v["type"] == "MODEL_UNAVAILABLE" for v in memo["violations"]):
                memo_stats["unavailable"] += 1
            else:
                memo_stats["accepted" if memo["source"].startswith("model") else "rejected"] += 1
                for v in memo["violations"]:
                    memo_stats[f"violation:{v['type']}"] += 1
        rows.append({"id": case["id"], "category": case["category"], "title": case["title"],
                     "passed": sc["passed"], "score": sc["score"], "failed": sc["failed"],
                     "classes": sc["classes"], "checks": sc["checks"],
                     "narrative": (result or {}).get("narrative"),
                     "confidence": (result or {}).get("confidence", {}).get("overall"),
                     "memo": memo})
        for c in sc["classes"]:
            class_hist[c] += 1
        cat_stats[case["category"]][1] += 1
        cat_stats[case["category"]][0] += int(sc["passed"])
        mark = "PASS" if sc["passed"] else "FAIL"
        print(f"{mark}  {case['id']:32} {sc['score']:.2f}  {', '.join(sc['classes'])}")
        if args.verbose or not sc["passed"]:
            for k in sc["failed"]:
                print(f"       - {k}: {sc['checks'][k]['detail'][:160]}")
            if args.verbose and result:
                print("       > " + (result.get("narrative") or "")[:400])

    total = len(rows); passed = sum(r["passed"] for r in rows)
    print(f"\n{passed}/{total} cases passed  ({passed / total:.0%})  runner={rname}")
    for cat, (p, n) in sorted(cat_stats.items()):
        print(f"  {cat:14} {p}/{n}")
    if class_hist:
        print("failure classes:")
        for c, n in class_hist.most_common():
            print(f"  {n:3}  {c}")
    if llm is not None:
        acc, rej, na = memo_stats.get("accepted", 0), memo_stats.get("rejected", 0), memo_stats.get("unavailable", 0)
        print(f"model memos: {acc} accepted, {rej} rejected by the linter, {na} model unavailable"
              + (f"  ({acc / (acc + rej):.0%} clean)" if acc + rej else ""))
        for k, n in memo_stats.most_common():
            if k.startswith("violation:"):
                print(f"  {n:3}  {k[10:]}")
    with open(os.path.join(args.out, "latest.json"), "w") as f:
        json.dump({"runner": rname, "passed": passed, "total": total, "by_category": dict(cat_stats),
                   "failure_classes": dict(class_hist), "model_memos": dict(memo_stats),
                   "cases": rows}, f, indent=2, default=str)
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
