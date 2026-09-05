"""Load and validate Ledger Lens JSON files."""

import json
from io import BufferedIOBase, TextIOBase
from pathlib import Path
from typing import TypeVar

from pydantic import TypeAdapter

from .models import AccountSummary, BusinessContext, InvestigationRun, Transaction

T = TypeVar("T")
JsonSource = str | Path | bytes | bytearray | TextIOBase | BufferedIOBase


def _read_json(source: JsonSource):
    if isinstance(source, (str, Path)):
        with Path(source).open(encoding="utf-8") as handle:
            return json.load(handle)
    if isinstance(source, (bytes, bytearray)):
        return json.loads(source.decode("utf-8"))
    source.seek(0)
    payload = json.load(source)
    source.seek(0)
    return payload


def _load_list(source: JsonSource, model: type[T]) -> list[T]:
    payload = _read_json(source)
    return TypeAdapter(list[model]).validate_python(payload)


def load_account_summaries(source: JsonSource) -> list[AccountSummary]:
    return _load_list(source, AccountSummary)


def load_transactions(source: JsonSource) -> list[Transaction]:
    return _load_list(source, Transaction)


def load_business_context(source: JsonSource) -> list[BusinessContext]:
    return _load_list(source, BusinessContext)


def load_investigation_run(source: JsonSource) -> InvestigationRun:
    return InvestigationRun.model_validate(_read_json(source))
