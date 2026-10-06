"""Tests for LLM response cache (ADR-026)."""
from __future__ import annotations

import json
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import select

from app.llm.budget import BudgetGuard
from app.llm.client import AnthropicLlmClient
from app.models.news import LlmCall, LlmResponseCache

_NOW = datetime(2026, 10, 6, 12, 0, 0)
_VALID_JSON = json.dumps({"result": "ok"})


def _make_client(db_session, *, cache_ttl_days: int = -1) -> AnthropicLlmClient:
    guard = BudgetGuard(db_session, daily_usd=10.0, monthly_usd=100.0)
    client = AnthropicLlmClient.__new__(AnthropicLlmClient)
    client._guard = guard
    client._model = "claude-haiku-4-5"
    client._input_cost = 1.0 / 1_000_000
    client._output_cost = 5.0 / 1_000_000
    client._cache_ttl_days = cache_ttl_days
    # Real _sdk mock
    mock_sdk = MagicMock()
    mock_response = MagicMock()
    mock_response.usage.input_tokens = 100
    mock_response.usage.output_tokens = 50
    mock_response.content = [MagicMock(text=_VALID_JSON)]
    mock_sdk.messages.create.return_value = mock_response
    client._sdk = mock_sdk
    return client


class TestLlmCache:
    def test_cache_miss_calls_api_and_stores(self, db_session):
        client = _make_client(db_session)

        result = client.call(
            system="sys", user="user msg",
            purpose="classify", prompt_version="classify_v1:abc123",
        )

        assert result == _VALID_JSON
        client._sdk.messages.create.assert_called_once()

        cached = db_session.scalar(select(LlmResponseCache))
        assert cached is not None
        assert cached.response_text == _VALID_JSON
        assert cached.hit_count == 0
        assert cached.purpose == "classify"
        assert cached.model == "claude-haiku-4-5"

    def test_cache_hit_skips_api(self, db_session):
        client = _make_client(db_session)

        # First call — populates cache
        client.call(system="sys", user="same user msg",
                    purpose="classify", prompt_version="classify_v1:abc123")
        client._sdk.messages.create.reset_mock()

        # Second call — should hit cache
        result = client.call(system="sys", user="same user msg",
                             purpose="classify", prompt_version="classify_v1:abc123")

        assert result == _VALID_JSON
        client._sdk.messages.create.assert_not_called()

        cached = db_session.scalar(select(LlmResponseCache))
        assert cached.hit_count == 1
        assert cached.last_hit_at is not None

    def test_cache_hit_logs_zero_cost(self, db_session):
        client = _make_client(db_session)
        client.call(system="sys", user="msg", purpose="classify", prompt_version="pv:aaa")
        client.call(system="sys", user="msg", purpose="classify", prompt_version="pv:aaa")

        calls = db_session.scalars(select(LlmCall)).all()
        cache_hits = [c for c in calls if c.status == "cache_hit"]
        assert len(cache_hits) == 1
        assert cache_hits[0].cost_usd == 0.0
        assert cache_hits[0].input_tokens == 0

    def test_different_prompt_version_misses_cache(self, db_session):
        client = _make_client(db_session)
        client.call(system="sys", user="msg", purpose="classify", prompt_version="pv:v1")
        client._sdk.messages.create.reset_mock()

        client.call(system="sys", user="msg", purpose="classify", prompt_version="pv:v2")

        client._sdk.messages.create.assert_called_once()
        cached_count = db_session.query(LlmResponseCache).count()
        assert cached_count == 2

    def test_different_user_msg_misses_cache(self, db_session):
        client = _make_client(db_session)
        client.call(system="sys", user="msg A", purpose="classify", prompt_version="pv:v1")
        client._sdk.messages.create.reset_mock()

        client.call(system="sys", user="msg B", purpose="classify", prompt_version="pv:v1")

        client._sdk.messages.create.assert_called_once()

    def test_ttl_expired_entry_treated_as_miss(self, db_session):
        # Insert a cache entry with old created_at
        old_entry = LlmResponseCache(
            cache_key="a" * 32,
            purpose="classify",
            model="claude-haiku-4-5",
            prompt_version="pv:v1",
            response_text=_VALID_JSON,
            input_tokens=100,
            output_tokens=50,
            hit_count=0,
            created_at=datetime(2026, 9, 1, 0, 0, 0),  # 35 days old
        )
        db_session.add(old_entry)
        db_session.flush()

        client = _make_client(db_session, cache_ttl_days=7)
        # Patch cache_key to return the known key
        client._cache_key = lambda pv, user: "a" * 32  # type: ignore[method-assign]

        client.call(system="sys", user="msg", purpose="classify", prompt_version="pv:v1")

        # API should have been called (TTL expired)
        client._sdk.messages.create.assert_called_once()
