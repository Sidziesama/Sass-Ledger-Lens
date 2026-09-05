"""The priors ledger — what the agent has learned about THIS business.

This is the difference between a variance tool and an analyst. A tool sees a
delta. An analyst knows that November is always strong, that Copper Fork's
stocking order moves around, that freight was reclassified in January, and that
the settlement in June will not repeat.

Priors are durable, inspectable, evidence-backed, and revisable. Every one
records where it came from, so a reader can audit why the agent believes it.
They are proposed by runs, and confirmed or rejected by a human -- an agent that
silently learns wrong things is worse than one that learns nothing.
"""

import json
import os
from datetime import datetime, timezone

TYPES = (
    "seasonality",          # this month is structurally strong/weak
    "timing_pattern",       # a recurring item whose landing month moves
    "recurring_item",       # a steady, expected line
    "one_time",             # happened once; never extrapolate it
    "accounting_policy",    # a reclass or definitional change; breaks comparability
    "counterparty",         # how a specific customer or vendor behaves
    "structural",           # a standing relationship, e.g. a monthly program
    "threshold",            # what this business considers material
)

STATUSES = ("proposed", "confirmed", "rejected", "superseded", "contested")
SOURCE_TYPES = ("user_verified", "system_inferred", "hypothesis")


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class PriorStore:
    def __init__(self, path):
        self.path = path
        self.priors = []
        self.runs = []
        self._load()

    # -- persistence ---------------------------------------------------------
    def _load(self):
        if os.path.exists(self.path):
            with open(self.path) as f:
                d = json.load(f)
            self.priors = d.get("priors", [])
            self.runs = d.get("runs", [])

    def save(self):
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        tmp = self.path + ".tmp"
        with open(tmp, "w") as f:
            json.dump({"priors": self.priors, "runs": self.runs,
                       "updated_at": _now()}, f, indent=2)
        os.replace(tmp, self.path)

    # -- writing -------------------------------------------------------------
    def _next_id(self):
        return f"PR-{len(self.priors) + 1:04d}"

    def add(self, type, scope, statement, implication, basis,
            confidence=0.6, applies_to=None, status="proposed",
            source_type="system_inferred", source="detector",
            valid_from=None, valid_until=None, expectation=None):
        """Add a prior, or reinforce an existing one about the same thing.

        Reinforcement matters: a pattern seen in three runs should be trusted
        more than one seen once, and the ledger should say so rather than
        accumulating near-duplicates.
        """
        assert type in TYPES, f"unknown prior type: {type}"
        key = (type, json.dumps(scope, sort_keys=True))
        for p in self.priors:
            if (p["type"], json.dumps(p["scope"], sort_keys=True)) == key \
                    and p["status"] != "rejected":
                p["times_observed"] += 1
                p["confidence"] = round(min(0.98, p["confidence"] + 0.08), 2)
                p["last_observed_at"] = _now()
                p.setdefault("observations", []).append(basis)
                p["statement"] = statement
                p["implication"] = implication
                return p["id"]

        assert source_type in SOURCE_TYPES, source_type
        a = dict(applies_to or {})
        if valid_from:
            a["from_period"] = valid_from
        if valid_until:
            a["to_period"] = valid_until
        pid = self._next_id()
        self.priors.append({
            "id": pid, "type": type, "scope": scope,
            "statement": statement, "implication": implication,
            "basis": basis, "observations": [basis],
            "confidence": round(confidence, 2),
            "applies_to": a,
            "valid_from": a.get("from_period"), "valid_until": a.get("to_period"),
            "expectation": expectation,          # e.g. {"account": "Cloud", "max_increase_pct": 30}
            "status": status,
            "source_type": source_type,          # user_verified | system_inferred | hypothesis
            "source": source,
            "verification_status": "verified" if source_type == "user_verified" else "unverified",
            "version": 1, "history": [],
            "times_observed": 1, "times_applied": 0,
            "learned_at": _now(), "last_observed_at": _now(), "last_confirmed_at": None,
            "user_note": None,
        })
        return pid

    def set_status(self, pid, status, note=None, by="reviewer"):
        assert status in STATUSES
        for p in self.priors:
            if p["id"] == pid:
                p.setdefault("history", []).append(
                    {"version": p.get("version", 1), "status": p["status"],
                     "confidence": p["confidence"], "statement": p["statement"],
                     "changed_at": _now(), "by": by, "note": note})
                p["version"] = p.get("version", 1) + 1
                p["status"] = status
                if note:
                    p["user_note"] = note
                if status == "confirmed":
                    p["confidence"] = round(min(0.99, max(p["confidence"], 0.9)), 2)
                    p["source_type"] = "user_verified"
                    p["verification_status"] = "verified"
                    p["last_confirmed_at"] = _now()
                elif status == "rejected":
                    p["confidence"] = 0.0
                elif status == "contested":
                    p["confidence"] = round(p["confidence"] * 0.5, 2)
                    p["verification_status"] = "contested"
                return p
        raise KeyError(pid)

    def correct(self, pid, new_statement, new_implication=None, note=None, by="reviewer"):
        """Reviewer correction: a new version, with the old one kept in history."""
        p = self.set_status(pid, "confirmed", note=note, by=by)
        p["statement"] = new_statement
        if new_implication:
            p["implication"] = new_implication
        return p

    def record_run(self, run):
        self.runs.append(run)

    # -- reading -------------------------------------------------------------
    def active(self):
        return [p for p in self.priors if p["status"] in ("proposed", "confirmed")]

    def relevant(self, period):
        """Priors that bear on this period. Keeps the agent's context small and
        the reasoning auditable: it can only invoke priors listed here."""
        month = int(period[5:])
        out = []
        for p in self.active():
            a = p.get("applies_to") or {}
            if a.get("months") and month not in a["months"]:
                continue
            if a.get("from_period") and period < a["from_period"]:
                continue
            if a.get("only_period") and period != a["only_period"]:
                continue
            if a.get("to_period") and period > a["to_period"]:
                continue
            out.append(p)
            p["times_applied"] += 1
        return sorted(out, key=lambda p: -p["confidence"])

    def retrieve(self, period):
        """Priors for this period, plus the ones considered and REJECTED and why.

        A stale prior is more dangerous than no prior. Returning the rejects
        lets the run say "I saw the AWS-migration note; it expired in September."
        """
        month = int(period[5:])
        used, rejected = [], []
        for p in self.priors:
            if p["status"] == "rejected":
                rejected.append({"id": p["id"], "reason": "rejected by reviewer"})
                continue
            if p["status"] == "superseded":
                continue
            a = p.get("applies_to") or {}
            if a.get("to_period") and period > a["to_period"]:
                rejected.append({"id": p["id"], "reason": f"expired after {a['to_period']}"})
                continue
            if a.get("from_period") and period < a["from_period"]:
                rejected.append({"id": p["id"], "reason": f"not valid before {a['from_period']}"})
                continue
            if a.get("months") and month not in a["months"]:
                continue
            if a.get("only_period") and period != a["only_period"]:
                continue
            p["times_applied"] += 1
            used.append(p)
        return sorted(used, key=lambda p: -p["confidence"]), rejected

    def summary(self):
        by_type, by_status = {}, {}
        for p in self.priors:
            by_type[p["type"]] = by_type.get(p["type"], 0) + 1
            by_status[p["status"]] = by_status.get(p["status"], 0) + 1
        return {"total": len(self.priors), "by_type": by_type,
                "by_status": by_status, "runs": len(self.runs)}

    def as_briefing(self, period, limit=14):
        """Render priors as text for the language layer. The agent may cite only
        what appears here, by id."""
        rel = self.relevant(period)[:limit]
        if not rel:
            return "(no priors yet — this is the first analysis of this business)"
        lines = []
        for p in rel:
            lines.append(
                f"[{p['id']}] ({p['type']}, confidence {p['confidence']}, "
                f"status {p['status']}, observed {p['times_observed']}x)\n"
                f"    {p['statement']}\n"
                f"    implication: {p['implication']}")
        return "\n".join(lines)
