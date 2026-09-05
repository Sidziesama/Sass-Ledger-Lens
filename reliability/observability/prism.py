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
        """prismtrace-sdk 0.4: PRISMtrace(api_key, host, project_id).submit_trajectory(steps).

        Credentials: PRISMTRACE_API_KEY + PRISMTRACE_PROJECT_ID (PRISM_* also accepted).
        Host resolves from PRISMTRACE_HOST / PRISMTRACE_ENDPOINT, else the SDK default.
        Missing credentials mean local JSONL only -- never an error.
        """
        # Same names the main-branch tracer uses, so one .env serves both versions.
        key = os.environ.get("PRISMTRACE_API_KEY") or os.environ.get("PRISM_API_KEY")
        proj = os.environ.get("PRISMTRACE_PROJECT_ID") or os.environ.get("PRISM_PROJECT_ID")
        if not (key and proj):
            return None
        try:
            from prismtrace import PRISMtrace
            from prismtrace._config import resolve_host
            return PRISMtrace(api_key=key, host=resolve_host(None), project_id=proj)
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
        return e

    # -- PRISM trajectory ------------------------------------------------------
    STEP_TYPE = {"tool_called": "tool_call", "explanation_generated": "final_answer",
                 "run_completed": "final_answer"}

    def _steps(self):
        """Events -> PRISM steps. One reasoning/tool/final step per event, with
        the duration between consecutive events as the step latency."""
        steps, prev = [], 0
        for e in self.events:
            payload = {k: v for k, v in e.items()
                       if k not in ("run_id", "event", "ts", "elapsed_ms", "seq")}
            st = {"step_type": self.STEP_TYPE.get(e["event"], "reasoning"),
                  "label": e["event"],
                  "input_summary": json.dumps({k: payload[k] for k in ("account", "dimension", "filter", "period")
                                               if k in payload}, default=str)[:500],
                  "output_summary": json.dumps(payload, default=str)[:1500],
                  "duration_ms": max(e["elapsed_ms"] - prev, 0),
                  "status": "error" if e["event"] in ("claim_rejected", "tool_error") else "success"}
            if e["event"] == "tool_called":
                st["tool_name"] = payload.get("tool", "tool")
            steps.append(st); prev = e["elapsed_ms"]
        return steps

    def submit(self, agent_name="ledger-lens-reference", final_status=None):
        """Send the run to PRISM as one trajectory. Returns the response or None."""
        if not self._prism or not self.events:
            return None
        if final_status is None:
            final_status = "error" if any(e["event"] == "tool_error" for e in self.events) else "success"
        try:
            resp = self._prism.submit_trajectory(self._steps(), agent_name=agent_name,
                                                 conversation_id=self.run_id, final_status=final_status)
            self._prism.flush()
            return resp
        except Exception:                                 # noqa: BLE001
            return None

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
