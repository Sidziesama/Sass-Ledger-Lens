"""Explicit application configuration; existing environment values take precedence."""

from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]


def load_settings() -> None:
    load_dotenv(ROOT / ".env", override=False)
