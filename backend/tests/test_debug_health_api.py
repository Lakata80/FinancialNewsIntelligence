"""Tests for GET /debug/health and GET /debug/cost-by-day (Sprint 9)."""
from __future__ import annotations

from datetime import datetime, timedelta
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.deps import get_db
from app.core.db import Base
from app.main import app
from app.models.news import Article, FetchRun, LlmCall, Source, StoryFact, VerificationLog

_NOW = datetime(2026, 10, 6, 12, 0, 0)


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


def _seed_source(db_session, name: str = "Yahoo RSS", last_ok_hours_ago: float | None = 1.0) -> Source:
    src = Source(name=name, kind="rss", enabled=True, is_official=False)
    db_session.add(src)
    db_session.flush()
    if last_ok_hours_ago is not None:
        finished = _NOW - timedelta(hours=last_ok_hours_ago)
        run = FetchRun(
            source_id=src.id,
            started_at=finished - timedelta(minutes=1),
            finished_at=finished,
            status="ok",
            items_seen=5,
            items_new=2,
        )
        db_session.add(run)
        db_session.flush()
    return src


class TestHealthEndpoint:
    def test_healthy_source_status_ok(self, client, db_session):
        _seed_source(db_session, last_ok_hours_ago=1.0)
        db_session.commit()

        with patch("app.api.debug._load_observability_config", return_value={"stale_source_hours": 48, "rejected_facts_alarm_pct": 30}), \
             patch("app.api.debug._load_budgets", return_value=(0.5, 10.0)):
            resp = client.get("/api/debug/health")

        assert resp.status_code == 200
        data = resp.json()
        assert data["sources"][0]["status"] == "ok"
        assert data["alarms"] == []

    def test_stale_source_triggers_alarm(self, client, db_session):
        _seed_source(db_session, last_ok_hours_ago=72.0)
        db_session.commit()

        with patch("app.api.debug._load_observability_config", return_value={"stale_source_hours": 48, "rejected_facts_alarm_pct": 30}), \
             patch("app.api.debug._load_budgets", return_value=(0.5, 10.0)):
            resp = client.get("/api/debug/health")

        assert resp.status_code == 200
        data = resp.json()
        assert data["sources"][0]["status"] == "stale"
        alarm_types = [a["type"] for a in data["alarms"]]
        assert "stale_source" in alarm_types

    def test_never_fetched_source_triggers_alarm(self, client, db_session):
        _seed_source(db_session, last_ok_hours_ago=None)
        db_session.commit()

        with patch("app.api.debug._load_observability_config", return_value={"stale_source_hours": 48, "rejected_facts_alarm_pct": 30}), \
             patch("app.api.debug._load_budgets", return_value=(0.5, 10.0)):
            resp = client.get("/api/debug/health")

        data = resp.json()
        assert data["sources"][0]["status"] == "never_fetched"
        alarm_types = [a["type"] for a in data["alarms"]]
        assert "stale_source" in alarm_types

    def test_budget_warning_at_80_percent(self, client, db_session):
        # Spend 82% of $10 monthly budget = $8.20
        db_session.add(LlmCall(
            purpose="classify", model="claude-haiku-4-5", prompt_version="pv:v1",
            input_tokens=1000, output_tokens=500, cost_usd=8.20,
            latency_ms=100, status="ok", created_at=_NOW,
        ))
        db_session.commit()

        with patch("app.api.debug._load_observability_config", return_value={"stale_source_hours": 48, "rejected_facts_alarm_pct": 30}), \
             patch("app.api.debug._load_budgets", return_value=(0.5, 10.0)):
            resp = client.get("/api/debug/health")

        data = resp.json()
        alarm_types = [a["type"] for a in data["alarms"]]
        assert "budget_warning" in alarm_types
        assert data["budget"]["monthly_pct"] == pytest.approx(82.0, abs=0.1)

    def test_quarantine_count(self, client, db_session):
        src = _seed_source(db_session)
        for i in range(3):
            db_session.add(Article(
                source_id=src.id, title=f"art{i}",
                url=f"https://x.com/{i}", canonical_url=f"https://x.com/{i}",
                published_at=_NOW, fetched_at=_NOW,
                tickers_raw=[], raw_payload={},
                status="quarantined", injection_score=0.9,
            ))
        db_session.commit()

        with patch("app.api.debug._load_observability_config", return_value={"stale_source_hours": 48, "rejected_facts_alarm_pct": 30}), \
             patch("app.api.debug._load_budgets", return_value=(0.5, 10.0)):
            resp = client.get("/api/debug/health")

        assert resp.json()["quarantined_count"] == 3


class TestCostByDay:
    def test_returns_aggregated_rows(self, client, db_session):
        for i in range(3):
            db_session.add(LlmCall(
                purpose="classify", model="claude-haiku-4-5", prompt_version="pv:v1",
                input_tokens=100, output_tokens=50, cost_usd=0.01,
                latency_ms=50, status="ok",
                created_at=datetime(2026, 10, 6, 10 + i, 0, 0),
            ))
        db_session.add(LlmCall(
            purpose="classify", model="claude-haiku-4-5", prompt_version="pv:v1",
            input_tokens=0, output_tokens=0, cost_usd=0.0,
            latency_ms=0, status="cache_hit",
            created_at=datetime(2026, 10, 6, 13, 0, 0),
        ))
        db_session.commit()

        resp = client.get("/api/debug/cost-by-day?days=30")

        assert resp.status_code == 200
        rows = resp.json()
        assert len(rows) == 1
        assert rows[0]["date"] == "2026-10-06"
        assert rows[0]["calls"] == 4
        assert rows[0]["cache_hits"] == 1
        assert rows[0]["cost_usd"] == pytest.approx(0.03, abs=1e-6)
