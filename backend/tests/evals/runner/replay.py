"""Replay cache for the evaluation harness.

Records LLM responses during live runs and replays them in CI without API calls.
Cache is stored as JSONL files under tests/evals/replay_cache/<case_id>.jsonl.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from sqlalchemy.orm import Session

from app.llm.budget import BudgetGuard
from app.llm.client import AnthropicLlmClient

REPLAY_CACHE_DIR = Path(__file__).parent.parent / "replay_cache"


class ReplayCacheMiss(Exception):
    """Raised when a replay cache entry is not found."""


class ReplayCache:
    """Read/write JSONL replay cache keyed by (case_id, purpose, input_hash)."""

    def __init__(self, cache_dir: Path = REPLAY_CACHE_DIR) -> None:
        self._dir = cache_dir
        self._dir.mkdir(parents=True, exist_ok=True)
        self._index: dict[str, dict[str, str]] = {}

    def _path(self, case_id: str) -> Path:
        return self._dir / f"{case_id}.jsonl"

    @staticmethod
    def _key(purpose: str, user_msg: str) -> str:
        h = hashlib.sha256(user_msg.encode()).hexdigest()[:16]
        return f"{purpose}:{h}"

    def _load_case(self, case_id: str) -> dict[str, str]:
        if case_id not in self._index:
            entries: dict[str, str] = {}
            path = self._path(case_id)
            if path.exists():
                for line in path.read_text(encoding="utf-8").splitlines():
                    line = line.strip()
                    if not line:
                        continue
                    rec = json.loads(line)
                    entries[rec["key"]] = rec["response"]
            self._index[case_id] = entries
        return self._index[case_id]

    def save(self, case_id: str, purpose: str, user_msg: str, response: str) -> None:
        key = self._key(purpose, user_msg)
        rec = json.dumps({"key": key, "purpose": purpose, "response": response})
        with open(self._path(case_id), "a", encoding="utf-8") as fh:
            fh.write(rec + "\n")
        self._index.setdefault(case_id, {})[key] = response

    def load(self, case_id: str, purpose: str, user_msg: str) -> str | None:
        entries = self._load_case(case_id)
        return entries.get(self._key(purpose, user_msg))

    def has_case(self, case_id: str) -> bool:
        return self._path(case_id).exists()


class RecordingClient:
    """Wraps a real AnthropicLlmClient and records every response to the replay cache."""

    def __init__(
        self,
        real: AnthropicLlmClient,
        cache: ReplayCache,
        case_id: str,
    ) -> None:
        self._real = real
        self._cache = cache
        self._case_id = case_id

    @property
    def _model(self) -> str:
        return self._real._model

    @property
    def _guard(self) -> BudgetGuard:
        return self._real._guard

    def call(
        self,
        *,
        system: str,
        user: str,
        purpose: str,
        prompt_version: str,
        max_tokens: int = 1024,
    ) -> str:
        response = self._real.call(
            system=system,
            user=user,
            purpose=purpose,
            prompt_version=prompt_version,
            max_tokens=max_tokens,
        )
        self._cache.save(self._case_id, purpose, user, response)
        return response


class ReplayClient:
    """Returns pre-recorded responses; no real API calls."""

    def __init__(
        self,
        cache: ReplayCache,
        case_id: str,
        session: Session,
        model: str,
    ) -> None:
        self._cache = cache
        self._case_id = case_id
        self._model = model
        # Generous budget so the guard never blocks during replay
        self._guard = BudgetGuard(session, daily_usd=9_999.0, monthly_usd=99_999.0)

    def call(
        self,
        *,
        system: str,
        user: str,
        purpose: str,
        prompt_version: str,
        max_tokens: int = 1024,
    ) -> str:
        response = self._cache.load(self._case_id, purpose, user)
        if response is None:
            raise ReplayCacheMiss(
                f"No replay cache entry for case={self._case_id!r} purpose={purpose!r}. "
                "Run `just eval` first to populate the cache."
            )
        return response

    def _log_call(self, **_kwargs: object) -> None:
        pass
