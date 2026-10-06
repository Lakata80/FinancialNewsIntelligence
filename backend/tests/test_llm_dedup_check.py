"""Tests for check_same_event — no real API calls."""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from app.llm.budget import BudgetExceeded, BudgetGuard
from app.llm.client import AnthropicLlmClient
from app.llm.dedup_check import check_same_event
from app.models.news import Article, ClusterMember, Source, StoryCluster

_FIXTURES = Path(__file__).parent / "fixtures" / "llm"
_NOW = datetime(2026, 10, 5, 12, 0, 0)


def _fake_client(db_session, fixture_name: str) -> AnthropicLlmClient:
    guard = BudgetGuard(db_session, daily_usd=10.0, monthly_usd=100.0)
    client = AnthropicLlmClient.__new__(AnthropicLlmClient)
    client._guard = guard
    client._model = "claude-haiku-4-5"
    payload = (_FIXTURES / fixture_name).read_text(encoding="utf-8")
    client.call = MagicMock(return_value=payload)
    return client


def _seed_pair(db_session) -> tuple[StoryCluster, StoryCluster]:
    source = Source(name="src-dedup", kind="rss", is_official=False)
    db_session.add(source)
    db_session.flush()

    articles = []
    for i in range(2):
        a = Article(
            source_id=source.id,
            title=f"NVDA earnings story {i}",
            url=f"https://example.com/nvda-{i}",
            canonical_url=f"https://example.com/nvda-{i}",
            published_at=_NOW,
            fetched_at=_NOW,
            tickers_raw=["NVDA"],
            raw_payload={},
            clean_text=f"NVIDIA Q3 earnings article {i}.",
            status="active",
        )
        db_session.add(a)
        articles.append(a)
    db_session.flush()

    clusters = []
    for i, article in enumerate(articles):
        c = StoryCluster(
            primary_ticker="NVDA",
            first_seen_at=_NOW,
            last_seen_at=_NOW,
            article_count=1,
            publisher_count=1,
        )
        db_session.add(c)
        db_session.flush()
        db_session.add(
            ClusterMember(
                cluster_id=c.id,
                article_id=article.id,
                match_method="minhash",
                similarity=0.65,
                needs_llm_check=True,
            )
        )
        clusters.append(c)
    db_session.flush()
    return clusters[0], clusters[1]


class TestCheckSameEvent:
    def test_same_event_above_threshold(self, db_session):
        ca, cb = _seed_pair(db_session)
        client = _fake_client(db_session, "dedup_same_event.json")

        result = check_same_event(ca, cb, client, threshold=0.8, session=db_session)

        assert result is True

    def test_same_event_below_threshold(self, db_session):
        ca, cb = _seed_pair(db_session)
        client = _fake_client(db_session, "dedup_same_event.json")

        # confidence=0.95 but threshold=0.99
        result = check_same_event(ca, cb, client, threshold=0.99, session=db_session)

        assert result is False

    def test_different_event(self, db_session):
        ca, cb = _seed_pair(db_session)
        client = _fake_client(db_session, "dedup_different_event.json")

        result = check_same_event(ca, cb, client, threshold=0.8, session=db_session)

        assert result is False

    def test_budget_exceeded_returns_false(self, db_session):
        ca, cb = _seed_pair(db_session)
        guard = BudgetGuard(db_session, daily_usd=10.0, monthly_usd=100.0)
        client = AnthropicLlmClient.__new__(AnthropicLlmClient)
        client._guard = guard
        client._model = "claude-haiku-4-5"
        client.call = MagicMock(side_effect=BudgetExceeded("monthly cap"))

        result = check_same_event(ca, cb, client, threshold=0.8, session=db_session)

        assert result is False

    def test_empty_cluster_returns_false(self, db_session):
        ca, cb = _seed_pair(db_session)
        # Quarantine all articles in ca
        for member in ca.members:
            member.article.status = "quarantined"
        db_session.flush()

        client = _fake_client(db_session, "dedup_same_event.json")
        result = check_same_event(ca, cb, client, threshold=0.8, session=db_session)

        assert result is False
        client.call.assert_not_called()

    def test_threshold_boundary_exclusive(self, db_session):
        ca, cb = _seed_pair(db_session)
        payload = json.loads((_FIXTURES / "dedup_same_event.json").read_text())
        payload["confidence"] = 0.8  # exactly at threshold

        guard = BudgetGuard(db_session, daily_usd=10.0, monthly_usd=100.0)
        client = AnthropicLlmClient.__new__(AnthropicLlmClient)
        client._guard = guard
        client._model = "claude-haiku-4-5"
        client.call = MagicMock(return_value=json.dumps(payload))

        result = check_same_event(ca, cb, client, threshold=0.8, session=db_session)

        assert result is True  # 0.8 >= 0.8
