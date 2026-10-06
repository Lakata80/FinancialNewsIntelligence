"""Live tests against the real Anthropic API.

These tests make real API calls and incur costs.
Run with: pytest -m live

Requires ANTHROPIC_API_KEY to be set in the environment.
"""
from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path

import pytest

from app.llm.budget import BudgetGuard
from app.llm.classify import classify_cluster
from app.llm.client import AnthropicLlmClient
from app.models.news import Article, ClusterMember, Source, StoryCluster

pytestmark = pytest.mark.live

_NOW = datetime(2026, 10, 5, 12, 0, 0)

_EARNINGS_TEXT = (
    "NVIDIA Corporation (NVDA) reported third-quarter fiscal 2025 results on Wednesday. "
    "Revenue was $35.1 billion, up 94% year over year. Data Center revenue reached $30.8 billion. "
    "CEO Jensen Huang said 'demand for Blackwell is incredible'. Earnings per share were $0.81."
)


@pytest.fixture
def live_client(db_session):
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        pytest.skip("ANTHROPIC_API_KEY not set")
    guard = BudgetGuard(db_session, daily_usd=1.0, monthly_usd=5.0)
    return AnthropicLlmClient(api_key=api_key, model="claude-haiku-4-5", guard=guard)


def _seed_earnings_cluster(db_session) -> StoryCluster:
    source = Source(name="live-test-source", kind="rss", is_official=False)
    db_session.add(source)
    db_session.flush()

    article = Article(
        source_id=source.id,
        title="NVIDIA Reports Record Q3 Earnings",
        url="https://example.com/nvda-live-test",
        canonical_url="https://example.com/nvda-live-test",
        published_at=_NOW,
        fetched_at=_NOW,
        tickers_raw=["NVDA"],
        raw_payload={},
        clean_text=_EARNINGS_TEXT,
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


def test_live_classify_earnings(db_session, live_client):
    cluster = _seed_earnings_cluster(db_session)

    result = classify_cluster(cluster, live_client, db_session)

    assert result is not None, "Classification should succeed on a clear earnings article"
    assert result.cluster_id == cluster.id
    assert result.event_type.value in ("earnings", "other")
    assert result.relevance_score >= 0.0
    assert cluster.classification_model == "claude-haiku-4-5"
    assert cluster.classification_prompt_version is not None
    print(
        f"\nLive classification result:"
        f"\n  event_type:      {result.event_type}"
        f"\n  is_main_subject: {result.is_main_subject}"
        f"\n  is_opinion:      {result.is_opinion}"
        f"\n  relevance_score: {result.relevance_score}"
        f"\n  rationale:       {result.rationale_en}"
    )
