"""Tests for story_versions (ADR-025) and incremental re-summarization."""
from __future__ import annotations

import json
from datetime import datetime, timedelta
from unittest.mock import MagicMock

import pytest
from sqlalchemy import select

from app.llm.budget import BudgetGuard
from app.llm.client import AnthropicLlmClient
from app.llm.summarize import _archive_story, summarize_cluster
from app.models.news import (
    Article,
    ClusterMember,
    FactEvidence,
    Source,
    Story,
    StoryCluster,
    StoryFact,
    StoryVersion,
)

_BASE = datetime(2026, 10, 6, 12, 0, 0)
_LATER = _BASE + timedelta(hours=2)


def _fake_client(db_session, raw_payload: str) -> AnthropicLlmClient:
    guard = BudgetGuard(db_session, daily_usd=10.0, monthly_usd=100.0)
    client = AnthropicLlmClient.__new__(AnthropicLlmClient)
    client._guard = guard
    client._model = "claude-sonnet-4-6"
    client._input_cost = 3.00 / 1_000_000
    client._output_cost = 15.00 / 1_000_000
    client._cache_ttl_days = -1
    client.call = MagicMock(return_value=raw_payload)
    return client


def _seed(db_session, cluster_dt: datetime = _BASE) -> tuple[StoryCluster, Article]:
    source = Source(name="test-src", kind="rss", is_official=False)
    db_session.add(source)
    db_session.flush()

    article = Article(
        source_id=source.id,
        title="NVDA posts record Q3 earnings",
        url="https://example.com/nvda",
        canonical_url="https://example.com/nvda",
        published_at=_BASE,
        fetched_at=_BASE,
        tickers_raw=["NVDA"],
        raw_payload={},
        clean_text="NVIDIA reported record Q3 earnings of $18.1B revenue.",
        status="active",
    )
    db_session.add(article)
    db_session.flush()

    cluster = StoryCluster(
        primary_ticker="NVDA",
        first_seen_at=_BASE,
        last_seen_at=cluster_dt,
        article_count=1,
        publisher_count=1,
        visible=True,
    )
    db_session.add(cluster)
    db_session.flush()

    db_session.add(ClusterMember(
        cluster_id=cluster.id, article_id=article.id,
        match_method="exact_hash", similarity=1.0, needs_llm_check=False,
    ))
    db_session.flush()
    return cluster, article


def _valid_payload(cluster_id: int, article_id: int) -> str:
    return json.dumps({
        "cluster_id": cluster_id,
        "title_bg": "NVIDIA отчете рекордни приходи",
        "summary_bg": "Кратко резюме.",
        "key_facts": [{
            "text_bg": "Приходи от $18.1B.",
            "evidence": [{"article_id": article_id, "quote_en": "$18.1B revenue"}],
        }],
        "attributed_opinions": [],
        "uncertainties_bg": [],
        "injection_suspected": False,
    })


class TestArchiveStory:
    def test_creates_story_version(self, db_session):
        cluster, article = _seed(db_session)
        story = Story(
            cluster_id=cluster.id,
            title_bg="Старо заглавие",
            summary_bg="Старо резюме",
            tickers=["NVDA"],
            event_type="earnings",
            is_opinion=False,
            verification_status="verified",
            model_version="claude-sonnet-4-6",
            prompt_version="summarize_v1:abc12345",
            created_at=_BASE,
        )
        db_session.add(story)
        db_session.flush()
        sf = StoryFact(story_id=story.id, fact_order=0, text_bg="Факт.", verification_status="verified")
        db_session.add(sf)
        db_session.flush()

        _archive_story(story, db_session, reason="new_article_joined")
        db_session.flush()

        versions = db_session.scalars(
            select(StoryVersion).where(StoryVersion.cluster_id == cluster.id)
        ).all()
        assert len(versions) == 1
        v = versions[0]
        assert v.version_num == 1
        assert v.reason == "new_article_joined"
        assert v.model_version == "claude-sonnet-4-6"

        snap = json.loads(v.snapshot_json)
        assert snap["title_bg"] == "Старо заглавие"
        assert len(snap["facts"]) == 1
        assert snap["facts"][0]["text_bg"] == "Факт."

        # Original story should be deleted
        assert db_session.scalar(select(Story).where(Story.cluster_id == cluster.id)) is None

    def test_version_num_increments(self, db_session):
        cluster, _ = _seed(db_session)
        for i in range(1, 3):
            db_session.add(StoryVersion(
                cluster_id=cluster.id,
                version_num=i,
                replaced_at=_BASE,
                reason="new_article_joined",
                snapshot_json="{}",
                model_version="claude-sonnet-4-6",
                prompt_version="summarize_v1:abc12345",
            ))
        db_session.flush()

        story = Story(
            cluster_id=cluster.id, title_bg="T", summary_bg="S",
            tickers=[], event_type=None, is_opinion=False,
            verification_status="pending",
            model_version="claude-sonnet-4-6",
            prompt_version="summarize_v1:abc12345",
            created_at=_BASE,
        )
        db_session.add(story)
        db_session.flush()

        _archive_story(story, db_session, reason="manual_rerun")
        db_session.flush()

        versions = db_session.scalars(
            select(StoryVersion).where(StoryVersion.cluster_id == cluster.id)
            .order_by(StoryVersion.version_num)
        ).all()
        assert versions[-1].version_num == 3


class TestSummarizeClusterIncremental:
    def test_skips_unchanged_cluster(self, db_session):
        cluster, article = _seed(db_session, cluster_dt=_BASE)
        existing = Story(
            cluster_id=cluster.id, title_bg="Existing", summary_bg="S",
            tickers=[], event_type=None, is_opinion=False,
            verification_status="verified",
            model_version="claude-sonnet-4-6",
            prompt_version="summarize_v1:abc12345",
            created_at=_BASE,
        )
        db_session.add(existing)
        db_session.flush()

        client = _fake_client(db_session, _valid_payload(cluster.id, article.id))
        result = summarize_cluster(cluster, client, db_session)

        assert result is existing
        client.call.assert_not_called()

    def test_rearchives_and_resimmarizes_stale_cluster(self, db_session):
        cluster, article = _seed(db_session, cluster_dt=_LATER)
        old_story = Story(
            cluster_id=cluster.id, title_bg="Old", summary_bg="Old summary",
            tickers=[], event_type=None, is_opinion=False,
            verification_status="verified",
            model_version="claude-sonnet-4-6",
            prompt_version="summarize_v1:abc12345",
            created_at=_BASE,  # older than cluster.last_seen_at (_LATER)
        )
        db_session.add(old_story)
        db_session.flush()
        old_id = old_story.id

        client = _fake_client(db_session, _valid_payload(cluster.id, article.id))
        result = summarize_cluster(cluster, client, db_session)

        assert result is not None
        assert result.title_bg == "NVIDIA отчете рекордни приходи"
        assert result.cluster_id == cluster.id

        versions = db_session.scalars(
            select(StoryVersion).where(StoryVersion.cluster_id == cluster.id)
        ).all()
        assert len(versions) == 1
        assert versions[0].reason == "new_article_joined"
        snap = json.loads(versions[0].snapshot_json)
        assert snap["title_bg"] == "Old"
