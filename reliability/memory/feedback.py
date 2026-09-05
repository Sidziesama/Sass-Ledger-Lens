"""Reviewer feedback CLI. The human side of the learning loop.

    python -m reliability.memory.feedback --memory runs/memory.json list
    python -m reliability.memory.feedback --memory runs/memory.json confirm PR-0003
    python -m reliability.memory.feedback --memory runs/memory.json reject  PR-0003 --note "not a reclass"
    python -m reliability.memory.feedback --memory runs/memory.json correct PR-0003 \\
        --statement "Freight moved to COGS from January per new policy" --note "policy memo 12 Jan"
    python -m reliability.memory.feedback --memory runs/memory.json add \\
        --account "Cloud Expense" --statement "AWS migration elevates cloud spend through September" \\
        --implication "expect up to +30% a month" --valid-from 2026-07 --valid-until 2026-09 \\
        --max-increase-pct 30

Every action is versioned in the prior's history; nothing is overwritten.
"""

import argparse
import json

from .store import PriorStore, TYPES


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--memory", required=True)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list")
    for c in ("confirm", "reject", "contest"):
        p = sub.add_parser(c); p.add_argument("id"); p.add_argument("--note")
    p = sub.add_parser("correct"); p.add_argument("id"); p.add_argument("--statement", required=True)
    p.add_argument("--implication"); p.add_argument("--note")
    p = sub.add_parser("add")
    p.add_argument("--type", default="counterparty", choices=TYPES)
    p.add_argument("--account", required=True); p.add_argument("--entity")
    p.add_argument("--statement", required=True); p.add_argument("--implication", default="")
    p.add_argument("--confidence", type=float, default=0.9)
    p.add_argument("--valid-from"); p.add_argument("--valid-until")
    p.add_argument("--max-increase-pct", type=float); p.add_argument("--direction", choices=["up", "down"])
    args = ap.parse_args(argv)

    store = PriorStore(args.memory)
    if args.cmd == "list":
        for pr in store.priors:
            a = pr.get("applies_to") or {}
            print(f"{pr['id']}  [{pr['status']:9}] {pr['type']:17} conf {pr['confidence']:.2f}  "
                  f"{pr.get('source_type', '?'):15} "
                  f"{a.get('from_period', '…')}→{a.get('to_period', '…')}  {pr['statement'][:90]}")
        print(json.dumps(store.summary()))
        return 0
    if args.cmd in ("confirm", "reject", "contest"):
        pr = store.set_status(args.id, {"confirm": "confirmed", "reject": "rejected", "contest": "contested"}[args.cmd],
                              note=args.note, by="finance_reviewer")
    elif args.cmd == "correct":
        pr = store.correct(args.id, args.statement, args.implication, note=args.note)
    else:
        scope = {"account": args.account}
        if args.entity:
            scope["entity"] = args.entity
        exp = {}
        if args.max_increase_pct is not None:
            exp["max_increase_pct"] = args.max_increase_pct
        if args.direction:
            exp["direction"] = args.direction
        pid = store.add(args.type, scope, args.statement, args.implication, {"source": "reviewer"},
                        args.confidence, source_type="user_verified", source="finance_reviewer",
                        valid_from=args.valid_from, valid_until=args.valid_until,
                        expectation=exp or None, status="confirmed")
        pr = next(x for x in store.priors if x["id"] == pid)
    store.save()
    print(json.dumps({k: pr[k] for k in ("id", "type", "status", "confidence", "source_type",
                                         "version", "statement", "implication", "applies_to")}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
