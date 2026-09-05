#!/usr/bin/env bash
set -euo pipefail

project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$project_root"

if [[ -x ".venv/bin/python" ]]; then
  python_cmd=".venv/bin/python"
elif command -v python3 >/dev/null 2>&1; then
  python_cmd="python3"
else
  echo "Python 3 is required. Create .venv and install requirements-dev.txt." >&2
  exit 1
fi

"$python_cmd" -m ruff check .
"$python_cmd" -m ruff format --check .
PYTHONDONTWRITEBYTECODE=1 "$python_cmd" -m pytest -q
PYTHONDONTWRITEBYTECODE=1 "$python_cmd" -m src.evaluation.benchmark
PYTHONDONTWRITEBYTECODE=1 "$python_cmd" -m src.cli \
  --prior 2026-01-01 \
  --current 2026-02-01

echo "Ledger Lens preflight passed."
