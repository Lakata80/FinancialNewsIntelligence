"""Tests for classify_cluster — no real API calls."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from app.llm.budget import BudgetExceeded, BudgetGuard
from app.llm.classify import classify_cluster
from app.llm.client import AnthropicLlmClient
from app.llm.models import EventType
from app.models.news import Article, ClusterMember, Source, StoryCluster

_FIXTURES = Path(__file__).parent / "fixtures" / "llm"

_NOW = datetime(2026, 10, 5, 12, 0, 0)


def _fake_client(db_session, fixture_name: str) -> AnthropicLlmClient:
    """Build a client whose call() returns a fixture file, with no real API."""
    guard = BudgetGuard(db_session, daily_usd=10.0, monthly_usd=100.0)
    client = AnthropicLlmClient.__new__(AnthropicLlmClient)
    client._guard = guard
    client._model = "claude-haiku-4-5"
    payload = (_FIXTURES / fixture_name).read_text(encoding="utf-8")
    client.call = MagicMock(return_value=payload)
    return client


def _seed_cluster(db_session, cluster_id_hint: int = 1) -> StoryCluster:
    """Insert a source, article, cluster, and member into the DB."""
    source = Source(name=f"src-{cluster_id_hint}", kind="rss", is_official=False)
    db_session.add(source)
    db_session.flush()

    article = Article(
        source_id=source.id,
        title="NVDA posts record Q3 earnings",
        url=f"https://example.com/nvda-q3-{cluster_id_hint}",
        canonical_url=f"https://example.com/nvda-q3-{cluster_id_hint}",
        published_at=_NOW,
        fetched_at=_NOW,
        tickers_raw=["NVDA"],
        raw_payload={},
        clean_text="NVIDIA reported record Q3 earnings of $18.1B revenue.",
        status="active",
    )
    db_session.add(article)
    db_session.flush()

    cluster = StoryCluster(
        primary_ticker="NVDA",
        first_seen_at=_NOW,
        last_seen_at=_NOW,
        article_count=1,
        publisher_count=1,
    )
    db_session.add(cluster)
    db_session.flush()

    db_session.add(
        ClusterMember(
            cluster_id=cluster.id,
            article_id=article.id,
            match_method="exact_hash",
            similarity=1.0,
            needs_llm_check=False,
        )
    )
    db_session.flush()
    return cluster


class TestClassifyCluster:
    def test_valid_classification_persisted(self, db_session):
        cluster = _seed_cluster(db_session)
        cluster_id = cluster.id
        client = _fake_client(db_session, "classify_valid.json")

        result = classify_cluster(cluster, client, db_session)

        assert result is not None
        assert result.event_type == EventType.earnings
        assert cluster.event_type == "earnings"
        assert cluster.classification_model == "claude-haiku-4-5"
        assert cluster.classification_prompt_version is not None
        assert cluster.visible is True

    def test_wrong_cluster_id_rejected(self, db_session):
        cluster = _seed_cluster(db_session)
        client = _fake_client(db_session, "classify_wrong_cluster_id.json")

        result = classify_cluster(cluster, client, db_session)

        assert result is None
        assert cluster.classification_model is None

    def test_promotional_sets_visible_false(self, db_session):
        cluster = _seed_cluster(db_session)
        # Override fixture cluster_id to match
        import json
        payload = json.loads((_FIXTURES / "classify_promotional.json").read_text())
        payload["cluster_id"] = cluster.id
        guard = BudgetGuard(db_session, daily_usd=10.0, monthly_usd=100.0)
        client = AnthropicLlmClient.__new__(AnthropicLlmClient)
        client._guard = guard
        client._model = "claude-haiku-4-5"
        client.call = MagicMock(return_value=json.dumps(payload))

        result = classify_cluster(cluster, client, db_session)

        assert result is not None
        assert cluster.visible is False

    def test_injection_suspected_still_classifies(self, db_session):
        cluster = _seed_cluster(db_session)
        import json
        payload = json.loads((_FIXTURES / "classify_injection.json").read_text())
        payload["cluster_id"] = cluster.id
        guard = BudgetGuard(db_session, daily_usd=10.0, monthly_usd=100.0)
        client = AnthropicLlmClient.__new__(AnthropicLlmClient)
        client._guard = guard
        client._model = "claude-haiku-4-5"
        client.call = MagicMock(return_value=json.dumps(payload))

        result = classify_cluster(cluster, client, db_session)

        assert result is not None
        assert result.injection_suspected is True

    def test_budget_exceeded_returns_none(self, db_session):
        cluster = _seed_cluster(db_session)
        guard = BudgetGuard(db_session, daily_usd=10.0, monthly_usd=100.0)
        client = AnthropicLlmClient.__new__(AnthropicLlmClient)
        client._guard = guard
        client._model = "claude-haiku-4-5"
        client.call = MagicMock(side_effect=BudgetExceeded("daily cap"))

        result = classify_cluster(cluster, client, db_session)

        assert result is None
        assert cluster.classification_model is None

    def test_no_active_articles_returns_none(self, db_session):
        cluster = _seed_cluster(db_session)
        # Quarantine the article
        for member in cluster.members:
            member.article.status = "quarantined"
        db_session.flush()

        client = _fake_client(db_session, "classify_valid.json")
        result = classify_cluster(cluster, client, db_session)

        assert result is None
        client.call.assert_not_called()
