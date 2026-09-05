"""Run Ledger Lens on one period.

    python -m reliability.agent.run <case_dir> <period> [--prior 2026-07] [--memory runs/memory.json] [--llm] [--json out.json]

--llm asks GIDE's local model to write the memo from the verified claims; the
draft is linted and replaced by the templated memo if it fails. Without --llm
(or without a reachable model) the run is fully deterministic.
"""

import argparse
import json
import sys

from ..memory.store import PriorStore
from .llm import LLM
from .memo import write_memo
from .reference import run


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("case_dir"); ap.add_argument("period")
    ap.add_argument("--prior"); ap.add_argument("--memory"); ap.add_argument("--llm", action="store_true")
    ap.add_argument("--json"); ap.add_argument("-q", "--quiet", action="store_true")
    a = ap.parse_args(argv)

    result = run(a.case_dir, a.period, a.prior, a.memory)
    llm = LLM(verbose=not a.quiet) if a.llm else None
    priors_text = PriorStore(a.memory).as_briefing(a.period) if a.memory else "(none)"
    memo = write_memo(llm, result, priors_text)
    result["memo"] = memo

    if a.json:
        with open(a.json, "w") as f:
            json.dump(result, f, indent=2, default=str)
    if not a.quiet:
        c = result["confidence"]
        print(f"Ledger Lens  {result['prior_period']} -> {result['period']}   "
              f"confidence: {c['overall'].upper()}  ({'; '.join(c['reasons'])})")
        print(f"memo source: {memo['source']}")
        if memo["violations"]:
            print("model draft rejected:", json.dumps(memo["violations"])[:400])
        print()
        print(memo["text"])
        print()
        dq = result["data_quality"]
        if dq["flags"]:
            print("data quality:", ", ".join(sorted({f['code'] for f in dq['flags']})))
        if result["not_investigated"]:
            print("not investigated:", "; ".join(f"{r['account']} ({r['reason']})" for r in result["not_investigated"][:4]))
        if result["memory_used"] or result["memory_rejected"]:
            print("memory used:", result["memory_used"], "| rejected:", [r["id"] for r in result["memory_rejected"]])
    return 0


if __name__ == "__main__":
    sys.exit(main())
