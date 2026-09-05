"""Structured, local JSON memory for repeatable investigations."""

import json
import os
import tempfile
from datetime import date
from decimal import Decimal
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
            and item.status in {"proposed", "confirmed", "contested"}
            and (
                as_of is None
                or (
                    (item.valid_from or item.effective_period) is None
                    or (item.valid_from or item.effective_period) <= as_of
                )
            )
            and (as_of is None or item.valid_until is None or as_of <= item.valid_until)
        ]
        return sorted(
            matches,
            key=lambda item: (item.effective_period or date.min, item.context_id),
            reverse=True,
        )

    def assess_business_context(
        self, *, subject: str, as_of: date, observed_variance_pct=None
    ) -> list[str]:
        """Return auditable application/non-application statements for every relevant prior."""
        contexts = self._load_list(self.context_path, BusinessContext)
        relevant = [
            item
            for item in contexts
            if subject.casefold() in item.subject.casefold()
            or subject.casefold() in item.description.casefold()
        ]
        notes: list[str] = []
        for item in sorted(relevant, key=lambda value: value.context_id):
            if item.status in {"rejected", "contested"}:
                reason = item.reason or item.status
                notes.append(f"{item.context_id} not applied: {item.status} ({reason})")
                continue
            start = item.valid_from or item.effective_period
            if item.valid_until is not None and as_of > item.valid_until:
                notes.append(f"{item.context_id} not applied: expired after {item.valid_until}")
                continue
            if start is not None and as_of < start:
                notes.append(f"{item.context_id} not applied: not valid before {start}")
                continue
            if (
                observed_variance_pct is not None
                and item.learned_min_pct is not None
                and item.learned_max_pct is not None
                and not item.learned_min_pct <= observed_variance_pct <= item.learned_max_pct
            ):
                notes.append(f"{item.context_id} exceeds the learned range")
            else:
                notes.append(f"consistent with {item.context_id}")
        return notes

    def save_business_context(self, context: BusinessContext) -> BusinessContext:
        contexts = self._load_list(self.context_path, BusinessContext)
        by_id = {item.context_id: item for item in contexts}
        by_id[context.context_id] = context
        self._write_models(
            self.context_path, sorted(by_id.values(), key=lambda item: item.context_id)
        )
        return context

    def list_investigation_runs(self) -> list[InvestigationRun]:
        return self._load_list(self.runs_path, InvestigationRun)

    def save_investigation_run(self, run: InvestigationRun) -> InvestigationRun:
        runs = self.list_investigation_runs()
        if any(item.run_id == run.run_id for item in runs):
            raise ValueError(f"investigation run already exists: {run.run_id}")
        runs.append(run)
        self._write_models(self.runs_path, runs)
        self._learn_from_run(run)
        return run

    def _learn_from_run(self, run: InvestigationRun) -> None:
        """Persist proposed, system-inferred observations for the next run."""
        for account in run.accounts:
            if account.variance_pct is None:
                low = high = None
            else:
                margin = max(abs(account.variance_pct) * Decimal("0.20"), Decimal("1"))
                low, high = account.variance_pct - margin, account.variance_pct + margin
            self.save_business_context(
                BusinessContext(
                    context_id=f"PR-{run.run_id[:8]}-{account.account.casefold().replace(' ', '-')}",
                    subject=account.account,
                    description=f"Observed {account.account} variance in run {run.run_id}",
                    effective_period=run.current_period,
                    valid_from=run.current_period,
                    source_type="system_inferred",
                    status="proposed",
                    source=f"run:{run.run_id}",
                    learned_min_pct=low,
                    learned_max_pct=high,
                    tags=["learned-from-run"],
                )
            )

    def add_reviewer_feedback(self, run_id: str, feedback: ReviewerFeedback) -> InvestigationRun:
        runs = self.list_investigation_runs()
        for index, run in enumerate(runs):
            if run.run_id == run_id:
                updated = run.model_copy(update={"feedback": [*run.feedback, feedback]})
                runs[index] = updated
                self._write_models(self.runs_path, runs)
                for correction in feedback.corrections:
                    self.save_business_context(
                        BusinessContext(
                            context_id=f"feedback:{run_id}:{correction.correction_id}",
                            subject=correction.subject,
                            description=correction.description,
                            effective_period=correction.effective_period,
                            valid_from=correction.effective_period,
                            source_type=(
                                "user_verified" if feedback.status == "approved" else "hypothesis"
                            ),
                            status={
                                "approved": "confirmed",
                                "rejected": "rejected",
                                "needs_revision": "contested",
                            }[feedback.status],
                            reason=feedback.comment,
                            source=f"reviewer:{feedback.reviewer};run:{run_id}",
                            tags=sorted(
                                set(correction.tags) | {"reviewer-correction", feedback.status}
                            ),
                        )
                    )
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
