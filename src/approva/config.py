"""Load application settings and resolve project paths."""

from __future__ import annotations

import os
from datetime import date
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / ".env")


def setting(name: str, default: str = "") -> str:
    """Return an environment setting, falling back to its default."""
    return os.getenv(name, default)


def data_path(*parts: str) -> Path:
    """Resolve a path below the repository's data directory."""
    return ROOT.joinpath("data", *parts)


def database_path() -> Path:
    """Return the configured database path, rooted at the repository."""
    path = Path(setting("APPROVA_DB", "data/approva.db"))
    return path if path.is_absolute() else ROOT / path


def today() -> date:
    """Return the pinned demo date or the current local date."""
    configured = setting("APPROVA_TODAY", "2026-10-02").strip()
    return date.fromisoformat(configured) if configured else date.today()


def llm_mode() -> str:
    """Return the configured LLM mode."""
    return setting("LLM_MODE", "live").strip().lower()
