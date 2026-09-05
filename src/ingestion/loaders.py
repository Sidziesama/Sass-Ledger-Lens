"""Load and validate Ledger Lens JSON files."""

import json
from pathlib import Path
from typing import TypeVar

from pydantic import TypeAdapter

from .models import AccountSummary, BusinessContext, InvestigationRun, Transaction

T = TypeVar("T")


def _load_list(path: str | Path, model: type[T]) -> list[T]:
    with Path(path).open(encoding="utf-8") as handle:
        payload = json.load(handle)
    return TypeAdapter(list[model]).validate_python(payload)


def load_account_summaries(path: str | Path) -> list[AccountSummary]:
    return _load_list(path, AccountSummary)


def load_transactions(path: str | Path) -> list[Transaction]:
    return _load_list(path, Transaction)


def load_business_context(path: str | Path) -> list[BusinessContext]:
    return _load_list(path, BusinessContext)


def load_investigation_run(path: str | Path) -> InvestigationRun:
    with Path(path).open(encoding="utf-8") as handle:
        return InvestigationRun.model_validate(json.load(handle))
