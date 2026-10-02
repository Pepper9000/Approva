"""Lazy adapter for Convai's documented Laya Python package API."""

from __future__ import annotations

import importlib
from functools import lru_cache
from typing import Protocol

from approva import config


class LayaUnavailable(RuntimeError):
    """Raised when the optional Laya package or checkpoint cannot be loaded."""


class LayaClientProtocol(Protocol):
    """Small interface matching the documented structured prediction contract."""

    def ready(self) -> bool:
        """Return whether this client can currently make predictions."""
        ...

    def predict(self, state: dict, questions: dict) -> dict:
        """Return the documented `{answers: ...}` result from typed questions."""
        ...


class HFLayaClient:
    """Load the official `laya` package lazily and call its documented Agent API."""

    def __init__(self, checkpoint: str | None = None) -> None:
        self.checkpoint = checkpoint or config.setting(
            "LAYA_CHECKPOINT", "convaiinnovations/laya-typed-decisions"
        )
        self._agent = None
        self._load_attempted = False
        self._error: str | None = None

    def ready(self) -> bool:
        """Load the selected checkpoint once, returning False on optional dependency errors."""
        if self._agent is not None:
            return True
        if self._load_attempted:
            return False
        self._load_attempted = True
        try:
            laya = importlib.import_module("laya")
            self._agent = laya.load(self.checkpoint)
        except Exception as error:
            self._error = f"{type(error).__name__}: {error}"
            return False
        return True

    def predict(self, state: dict, questions: dict) -> dict:
        """Run Laya's documented `agent.predict(state, questions)` API."""
        if not self.ready() or self._agent is None:
            raise LayaUnavailable(self._error or "Laya model is not available")
        result = self._agent.predict(state, questions)
        if not isinstance(result, dict) or not isinstance(result.get("answers"), dict):
            raise LayaUnavailable("Laya returned an unexpected result shape")
        return result


@lru_cache(maxsize=2)
def get_laya_client(checkpoint: str) -> HFLayaClient:
    """Return a cached lazy client for the configured checkpoint."""
    return HFLayaClient(checkpoint)