"""Tests for GET /pipeline/estimate (Sprint 9)."""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.deps import get_db
from app.core.db import Base
from app.main import app
from app.models.news import Story, StoryCluster

_BASE = datetime(2026, 10, 6, 10, 0, 0)
_LATER = _BASE + timedelta(hours=3)


@pytest.fixture
def db_engine():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    yield engine
    Base.metadata.drop_all(engine)


@pytest.fixture
def db_session(db_engine):
    Session = sessionmaker(bind=db_engine, autoflush=False, autocommit=False)
    with Session() as session:
        yield session


@pytest.fixture
def client(db_session):
    def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def _cluster(db_session, visible: bool = True, last_seen_at: datetime = _BASE) -> StoryCluster:
    c = StoryCluster(
        primary_ticker="AAPL",
        first_seen_at=_BASE,
        last_seen_at=last_seen_at,
        article_count=1,
        publisher_count=1,
        visible=visible,
    )
    db_session.add(c)
    db_session.flush()
    return c


def _story(db_session, cluster: StoryCluster, created_at: datetime = _BASE) -> Story:
    s = Story(
        cluster_id=cluster.id,
        title_bg="Title",
        summary_bg="Summary",
        tickers=["AAPL"],
        event_type="earnings",
        is_opinion=False,
        verification_status="verified",
        model_version="claude-sonnet-4-6",
        prompt_version="summarize_v1:abc12345",
        created_at=created_at,
    )
    db_session.add(s)
    db_session.flush()
    return s


class TestPipelineEstimate:
    def test_no_clusters(self, client, db_session):
        db_session.commit()
        resp = client.get("/api/pipeline/estimate")
        assert resp.status_code == 200
        data = resp.json()
        assert data["new_clusters"] == 0
        assert data["changed_clusters"] == 0
        assert data["total_clusters_to_process"] == 0
        assert data["estimated_cost_usd"] == 0.0
        assert data["show_warning"] is False

    def test_counts_new_cluster(self, client, db_session):
        _cluster(db_session)
        db_session.commit()

        resp = client.get("/api/pipeline/estimate")
        data = resp.json()
        assert data["new_clusters"] == 1
        assert data["changed_clusters"] == 0

    def test_counts_stale_cluster(self, client, db_session):
        c = _cluster(db_session, last_seen_at=_LATER)
        _story(db_session, c, created_at=_BASE)  # story created before last_seen_at
        db_session.commit()

        resp = client.get("/api/pipeline/estimate")
        data = resp.json()
        assert data["new_clusters"] == 0
        assert data["changed_clusters"] == 1

    def test_ignores_hidden_cluster(self, client, db_session):
        _cluster(db_session, visible=False)
        db_session.commit()

        resp = client.get("/api/pipeline/estimate")
        data = resp.json()
        assert data["total_clusters_to_process"] == 0

    def test_show_warning_when_above_threshold(self, client, db_session):
        for _ in range(6):
            _cluster(db_session)
        db_session.commit()

        with __import__("unittest.mock", fromlist=["patch"]).patch(
            "app.api.pipeline_api._load_cfg",
            return_value={"pipeline": {"cost_estimate_threshold": 5}},
        ):
            resp = client.get("/api/pipeline/estimate")
        data = resp.json()
        assert data["show_warning"] is True
