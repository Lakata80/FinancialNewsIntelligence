"""Tests for maintenance commands: cleanup, backup, export-digest."""
from __future__ import annotations

import json
import sqlite3
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.core.db import Base
from app.models.news import Article, FactEvidence, Source, Story, StoryCluster, StoryFact, ClusterMember

_NOW = datetime(2026, 10, 6, 12, 0, 0)


@pytest.fixture
def db_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    with Session() as session:
        yield session
    Base.metadata.drop_all(engine)


def _source(db_session) -> Source:
    src = Source(name="src", kind="rss", is_official=False)
    db_session.add(src)
    db_session.flush()
    return src


def _article(db_session, src: Source, fetched_at: datetime, status: str = "active") -> Article:
    url = f"https://x.com/{fetched_at.timestamp()}"
    art = Article(
        source_id=src.id, title="T", url=url, canonical_url=url,
        published_at=fetched_at, fetched_at=fetched_at,
        tickers_raw=[], raw_payload={}, status=status,
    )
    db_session.add(art)
    db_session.flush()
    return art


def _story_with_cluster(db_session, src: Source, created_at: datetime) -> tuple[StoryCluster, Story]:
    cluster = StoryCluster(
        primary_ticker="AAPL", first_seen_at=created_at, last_seen_at=created_at,
        article_count=1, publisher_count=1, visible=True,
    )
    db_session.add(cluster)
    db_session.flush()

    art = _article(db_session, src, created_at)
    db_session.add(ClusterMember(
        cluster_id=cluster.id, article_id=art.id,
        match_method="exact_hash", similarity=1.0, needs_llm_check=False,
    ))

    story = Story(
        cluster_id=cluster.id, title_bg="Title", summary_bg="Summary",
        tickers=["AAPL"], event_type="earnings", is_opinion=False,
        verification_status="verified",
        model_version="claude-sonnet-4-6", prompt_version="sv1:abc",
        created_at=created_at,
    )
    db_session.add(story)
    db_session.flush()
    return cluster, story


class TestCleanup:
    def test_old_uncited_articles_deleted(self, db_session):
        from app.maintenance import cmd_cleanup

        src = _source(db_session)
        old_art = _article(db_session, src, fetched_at=_NOW - timedelta(days=100))
        new_art = _article(db_session, src, fetched_at=_NOW)
        db_session.commit()

        retention = {"raw_articles_days": 90, "stories_days": 365}
        with patch("app.maintenance._load_retention", return_value=retention), \
             patch("app.maintenance.SessionLocal") as mock_sl:
            mock_sl.return_value.__enter__ = lambda s: db_session
            mock_sl.return_value.__exit__ = lambda s, *a: None
            cmd_cleanup(dry_run=False)

        remaining = db_session.scalars(select(Article)).all()
        assert new_art in remaining
        assert old_art not in remaining

    def test_cited_articles_not_deleted(self, db_session):
        from app.maintenance import cmd_cleanup

        src = _source(db_session)
        old_art = _article(db_session, src, fetched_at=_NOW - timedelta(days=100))

        # Add a cluster + story + fact_evidence referencing this article
        cluster = StoryCluster(
            primary_ticker="AAPL", first_seen_at=_NOW, last_seen_at=_NOW,
            article_count=1, publisher_count=1, visible=True,
        )
        db_session.add(cluster)
        db_session.flush()
        db_session.add(ClusterMember(
            cluster_id=cluster.id, article_id=old_art.id,
            match_method="exact_hash", similarity=1.0, needs_llm_check=False,
        ))
        story = Story(
            cluster_id=cluster.id, title_bg="T", summary_bg="S",
            tickers=[], event_type=None, is_opinion=False,
            verification_status="verified",
            model_version="m", prompt_version="pv",
            created_at=_NOW,
        )
        db_session.add(story)
        db_session.flush()
        sf = StoryFact(story_id=story.id, fact_order=0, text_bg="F", verification_status="verified")
        db_session.add(sf)
        db_session.flush()
        db_session.add(FactEvidence(
            fact_id=sf.id, article_id=old_art.id,
            quote_en="old quote", quote_start=0, quote_end=9,
        ))
        db_session.commit()

        retention = {"raw_articles_days": 90, "stories_days": 365}
        with patch("app.maintenance._load_retention", return_value=retention), \
             patch("app.maintenance.SessionLocal") as mock_sl:
            mock_sl.return_value.__enter__ = lambda s: db_session
            mock_sl.return_value.__exit__ = lambda s, *a: None
            cmd_cleanup(dry_run=False)

        # old_art should still be there (it has fact_evidence)
        remaining = db_session.scalars(select(Article)).all()
        assert old_art in remaining

    def test_dry_run_makes_no_changes(self, db_session):
        from app.maintenance import cmd_cleanup

        src = _source(db_session)
        _article(db_session, src, fetched_at=_NOW - timedelta(days=100))
        db_session.commit()

        before_count = db_session.query(Article).count()

        retention = {"raw_articles_days": 90, "stories_days": 365}
        with patch("app.maintenance._load_retention", return_value=retention), \
             patch("app.maintenance.SessionLocal") as mock_sl:
            mock_sl.return_value.__enter__ = lambda s: db_session
            mock_sl.return_value.__exit__ = lambda s, *a: None
            cmd_cleanup(dry_run=True)

        after_count = db_session.query(Article).count()
        assert before_count == after_count


class TestBackup:
    def test_creates_backup_file(self, tmp_path):
        from app.maintenance import cmd_backup

        # Create a minimal SQLite DB to back up
        db_file = tmp_path / "news.db"
        conn = sqlite3.connect(str(db_file))
        conn.execute("CREATE TABLE t (id INTEGER PRIMARY KEY)")
        conn.commit()
        conn.close()

        out_dir = tmp_path / "backups"
        with patch("app.maintenance._DB_PATH", db_file):
            cmd_backup(out_dir=out_dir)

        backups = list(out_dir.glob("news_*.db"))
        assert len(backups) == 1
        assert backups[0].stat().st_size > 0


class TestExportDigest:
    def test_writes_markdown_file(self, db_session, tmp_path):
        from app.maintenance import cmd_export_digest

        src = _source(db_session)
        cluster, story = _story_with_cluster(db_session, src, created_at=_NOW)
        sf = StoryFact(story_id=story.id, fact_order=0, text_bg="Факт 1.", verification_status="verified")
        db_session.add(sf)
        db_session.commit()

        out_file = tmp_path / "digest.md"
        with patch("app.maintenance.SessionLocal") as mock_sl:
            mock_sl.return_value.__enter__ = lambda s: db_session
            mock_sl.return_value.__exit__ = lambda s, *a: None
            cmd_export_digest(date_str="2026-10-06", output=out_file)

        assert out_file.exists()
        content = out_file.read_text(encoding="utf-8")
        assert "Финансов дайджест" in content
        assert "Title" in content
        assert "Факт 1." in content
