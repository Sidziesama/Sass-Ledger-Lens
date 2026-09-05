"""PRISM trajectory integration with an offline-safe tracing boundary."""

import os
from dataclasses import asdict, dataclass
from decimal import Decimal
from typing import Any, Protocol


@dataclass(frozen=True)
class TraceEvent:
    step_type: str
    label: str
    input_summary: str = ""
    output_summary: str = ""
    tool_name: str | None = None
    duration_ms: int = 0
    status: str = "success"

    def as_prism_step(self) -> dict[str, Any]:
        payload = asdict(self)
        if self.tool_name is None:
            payload.pop("tool_name")
        return payload


class TraceObserver(Protocol):
    def start_run(self, run_id: str) -> None: ...

    def record(self, event: TraceEvent) -> None: ...

    def finish_run(self, status: str = "success") -> dict | None: ...


class NullTraceObserver:
    def start_run(self, run_id: str) -> None:
        pass

    def record(self, event: TraceEvent) -> None:
        pass

    def finish_run(self, status: str = "success") -> None:
        return None


class InMemoryTraceObserver:
    """Inspectable observer used for tests and local demos."""

    def __init__(self):
        self.run_id: str | None = None
        self.events: list[TraceEvent] = []
        self.final_status: str | None = None

    def start_run(self, run_id: str) -> None:
        self.run_id = run_id
        self.events = []
        self.final_status = None

    def record(self, event: TraceEvent) -> None:
        self.events.append(event)

    def finish_run(self, status: str = "success") -> None:
        self.final_status = status
        return None


class PrismTraceObserver(InMemoryTraceObserver):
    """Submit an ordered Ledger Lens trajectory to PRISMtrace."""

    def __init__(self, client: Any, *, agent_id: str = "ledger-lens", agent_name: str = "Ledger Lens"):
        super().__init__()
        self.client = client
        self.agent_id = agent_id
        self.agent_name = agent_name

    @classmethod
    def from_env(cls) -> "PrismTraceObserver | NullTraceObserver":
        api_key = os.getenv("PRISMTRACE_API_KEY")
        host = os.getenv("PRISMTRACE_HOST")
        project_id = os.getenv("PRISMTRACE_PROJECT_ID")
        if not all((api_key, host, project_id)):
            return NullTraceObserver()
        from prismtrace import PRISMtrace

        return cls(PRISMtrace(api_key=api_key, host=host, project_id=project_id))

    def finish_run(self, status: str = "success") -> dict | None:
        self.final_status = status
        return self.client.submit_trajectory(
            steps=[event.as_prism_step() for event in self.events],
            agent_id=self.agent_id,
            agent_name=self.agent_name,
            request_id=self.run_id,
            conversation_id=self.run_id,
            model="deterministic-python-engine",
            final_status=status,
        )


def summarize(value: Any) -> str:
    """Create compact, deterministic summaries safe for trace metadata."""
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (list, tuple, set)):
        return f"{type(value).__name__}[{len(value)}]"
    return str(value)
