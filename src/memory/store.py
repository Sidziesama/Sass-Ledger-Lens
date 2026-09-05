"""Structured, local JSON memory for repeatable investigations."""

import json
import os
import tempfile
from datetime import date
from pathlib import Path

from pydantic import TypeAdapter

from src.ingestion.models import BusinessContext, InvestigationRun, ReviewerFeedback


class JsonMemoryStore:
    """Persist context and investigation history without hiding data in prompts."""

    def __init__(self, root: str | Path):
        self.root = Path(root)
        self.context_path = self.root / "business_context.json"
        self.runs_path = self.root / "investigation_runs.json"

    def get_business_context(
        self,
        *,
        subject: str | None = None,
        tags: set[str] | None = None,
        as_of: date | None = None,
    ) -> list[BusinessContext]:
        contexts = self._load_list(self.context_path, BusinessContext)
        normalized_subject = subject.casefold() if subject else None
        matches = [
            item
            for item in contexts
            if (
                normalized_subject is None
                or normalized_subject in item.subject.casefold()
                or normalized_subject in item.description.casefold()
            )
            and (not tags or bool(tags.intersection(item.tags)))
            and (as_of is None or item.effective_period is None or item.effective_period <= as_of)
        ]
        return sorted(
            matches,
            key=lambda item: (item.effective_period or date.min, item.context_id),
            reverse=True,
        )

    def save_business_context(self, context: BusinessContext) -> BusinessContext:
        contexts = self._load_list(self.context_path, BusinessContext)
        by_id = {item.context_id: item for item in contexts}
        by_id[context.context_id] = context
        self._write_models(self.context_path, sorted(by_id.values(), key=lambda item: item.context_id))
        return context

    def list_investigation_runs(self) -> list[InvestigationRun]:
        return self._load_list(self.runs_path, InvestigationRun)

    def save_investigation_run(self, run: InvestigationRun) -> InvestigationRun:
        runs = self.list_investigation_runs()
        if any(item.run_id == run.run_id for item in runs):
            raise ValueError(f"investigation run already exists: {run.run_id}")
        runs.append(run)
        self._write_models(self.runs_path, runs)
        return run

    def add_reviewer_feedback(self, run_id: str, feedback: ReviewerFeedback) -> InvestigationRun:
        runs = self.list_investigation_runs()
        for index, run in enumerate(runs):
            if run.run_id == run_id:
                updated = run.model_copy(update={"feedback": [*run.feedback, feedback]})
                runs[index] = updated
                self._write_models(self.runs_path, runs)
                return updated
        raise KeyError(f"unknown investigation run: {run_id}")

    @staticmethod
    def _load_list(path: Path, model: type):
        if not path.exists():
            return []
        with path.open(encoding="utf-8") as handle:
            return TypeAdapter(list[model]).validate_python(json.load(handle))

    def _write_models(self, path: Path, models: list) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = [item.model_dump(mode="json") for item in models]
        descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, indent=2, sort_keys=True)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary_name, path)
        except BaseException:
            try:
                os.unlink(temporary_name)
            except FileNotFoundError:
                pass
            raise
