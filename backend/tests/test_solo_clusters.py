"""Tests for assign_solo_clusters (ADR-028)."""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from sqlalchemy import select

from app.dedup.exact import assign_solo_clusters
from app.models.news import Article, ClusterMember, Source, StoryCluster

_BASE = datetime(2026, 10, 6, 12, 0, 0)


def _source(db_session) -> Source:
    src = Source(name="test", kind="rss", is_official=False)
    db_session.add(src)
    db_session.flush()
    return src


def _article(db_session, source_id: int, title: str = "T", hours_ago: int = 1, tickers=None) -> Article:
    a = Article(
        source_id=source_id,
        title=title,
        url=f"https://example.com/{title}",
        canonical_url=f"https://example.com/{title}",
        published_at=_BASE - timedelta(hours=hours_ago),
        fetched_at=_BASE,
        tickers_raw=tickers or [],
        raw_payload={},
        clean_text=title,
        status="active",
    )
    db_session.add(a)
    db_session.flush()
    return a


class TestAssignSoloClusters:
    def test_creates_cluster_per_unassigned_article(self, db_session):
        src = _source(db_session)
        _article(db_session, src.id, "Article A", tickers=["NVDA"])
        _article(db_session, src.id, "Article B", tickers=["AAPL"])
        db_session.flush()

        count = assign_solo_clusters(db_session, window_hours=48)
        db_session.flush()

        assert count == 2
        clusters = db_session.scalars(select(StoryCluster)).all()
        assert len(clusters) == 2

    def test_sets_primary_ticker_from_article(self, db_session):
        src = _source(db_session)
        _article(db_session, src.id, "NVDA news", tickers=["NVDA"])
        db_session.flush()

        assign_solo_clusters(db_session, window_hours=48)
        db_session.flush()

        cluster = db_session.scalars(select(StoryCluster)).first()
        assert cluster is not None
        assert cluster.primary_ticker == "NVDA"
        assert cluster.article_count == 1

    def test_skips_already_assigned_articles(self, db_session):
        src = _source(db_session)
        a = _article(db_session, src.id, "Already clustered")

        cluster = StoryCluster(
            primary_ticker=None, first_seen_at=_BASE, last_seen_at=_BASE,
            article_count=1, publisher_count=1,
        )
        db_session.add(cluster)
        db_session.flush()
        db_session.add(ClusterMember(
            cluster_id=cluster.id, article_id=a.id,
            match_method="exact_hash", similarity=1.0, needs_llm_check=False,
        ))
        db_session.flush()

        count = assign_solo_clusters(db_session, window_hours=48)
        assert count == 0

    def test_skips_articles_outside_window(self, db_session):
        src = _source(db_session)
        _article(db_session, src.id, "Old article", hours_ago=72)
        db_session.flush()

        count = assign_solo_clusters(db_session, window_hours=48)
        assert count == 0

    def test_skips_quarantined_articles(self, db_session):
        src = _source(db_session)
        a = _article(db_session, src.id, "Suspicious")
        a.status = "quarantined"
        db_session.flush()

        count = assign_solo_clusters(db_session, window_hours=48)
        assert count == 0
