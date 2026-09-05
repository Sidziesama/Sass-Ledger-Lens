"""PRISM instrumentation: Observe -> Improve -> Prove.

Every run emits a structured event stream. Traces are written locally as JSONL
regardless of connectivity, and forwarded to PRISM when the SDK and an API key
are present -- so a demo never depends on a network call, but the hosted traces
are real when they exist.

The events are chosen so a trace answers the questions we actually need to
improve the agent: did it pick the right variance, did it drill deep enough,
did it waste calls, and was every claim supported.
"""

import json
import os
import time
import uuid
from datetime import datetime, timezone

EVENTS = (
    "run_started", "data_loaded", "variance_detected", "variance_ranked",
    "memory_retrieved", "investigation_started", "tool_called", "driver_found",
    "evidence_retrieved", "hypothesis_proposed", "hypothesis_rejected",
    "investigation_stopped", "claim_verified", "claim_rejected",
    "explanation_generated", "prior_learned", "run_completed",
)


class Tracer:
    def __init__(self, run_id=None, out_dir="runs/traces", enabled=True):
        self.run_id = run_id or f"run_{uuid.uuid4().hex[:10]}"
        self.enabled = enabled
        self.events = []
        self.started = time.time()
        self.out_dir = out_dir
        self.tool_calls = 0
        self._prism = self._connect()

    def _connect(self):
        if not os.environ.get("PRISM_API_KEY"):
            return None
        try:
            import prismtrace
            return prismtrace.Client(api_key=os.environ["PRISM_API_KEY"],
                                     project=os.environ.get("PRISM_PROJECT", "ledger-lens"))
        except Exception:                                 # noqa: BLE001
            return None

    @property
    def prism_connected(self):
        return self._prism is not None

    def event(self, name, **payload):
        if not self.enabled:
            return
        e = {"run_id": self.run_id, "event": name,
             "ts": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
             "elapsed_ms": int((time.time() - self.started) * 1000),
             "seq": len(self.events), **payload}
        if name == "tool_called":
            self.tool_calls += 1
            e["tool_call_index"] = self.tool_calls
        self.events.append(e)
        if self._prism:
            try:
                self._prism.log(e)
            except Exception:                             # noqa: BLE001
                pass
        return e

    def summary(self):
        counts = {}
        for e in self.events:
            counts[e["event"]] = counts.get(e["event"], 0) + 1
        return {"run_id": self.run_id, "events": len(self.events),
                "tool_calls": self.tool_calls,
                "duration_ms": int((time.time() - self.started) * 1000),
                "event_counts": counts,
                "prism_connected": self.prism_connected}

    def flush(self):
        os.makedirs(self.out_dir, exist_ok=True)
        path = os.path.join(self.out_dir, f"{self.run_id}.jsonl")
        with open(path, "w") as f:
            for e in self.events:
                f.write(json.dumps(e, default=str) + "\n")
        return path
