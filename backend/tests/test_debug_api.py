"""Tests for /api/debug/* endpoints."""
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.deps import get_db
from app.core.db import Base
from app.main import app
from app.models.news import Article, FetchRun, LlmCall, Source, Story, StoryFact, VerificationLog


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


def _utc(hours_ago: int = 0) -> datetime:
    return (datetime.now(UTC) - timedelta(hours=hours_ago)).replace(tzinfo=None)


def _make_source(session, name: str = "test_src") -> Source:
    src = Source(name=name, kind="rss", enabled=True)
    session.add(src)
    session.flush()
    return src


def _make_article(session, source: Source, status: str = "active") -> Article:
    a = Article(
        source_id=source.id,
        publisher="Test Publisher",
        title="Suspicious article",
        url="https://example.com/suspicious",
        canonical_url="https://example.com/suspicious",
        published_at=_utc(1),
        fetched_at=_utc(0),
        tickers_raw=["NVDA"],
        raw_payload={},
        injection_score=0.92,
        matched_rules=["promo_pattern"],
        status=status,
    )
    session.add(a)
    session.flush()
    return a


class TestFetchRuns:
    def test_returns_never_run_for_source_without_runs(self, client, db_session):
        _make_source(db_session, "yahoo_rss")
        db_session.commit()

        r = client.get("/api/debug/fetch-runs")
        assert r.status_code == 200
        data = r.json()
        assert len(data) == 1
        assert data[0]["status"] == "never_run"
        assert data[0]["run_id"] is None

    def test_returns_last_run_per_source(self, client, db_session):
        src = _make_source(db_session, "yahoo_rss")
        # older run: completed
        db_session.add(FetchRun(
            source_id=src.id,
            started_at=_utc(3),
            finished_at=_utc(2),
            status="completed",
            items_seen=5,
            items_new=2,
        ))
        # newer run: failed
        db_session.add(FetchRun(
            source_id=src.id,
            started_at=_utc(1),
            finished_at=_utc(0),
            status="failed",
            items_seen=0,
            items_new=0,
        ))
        db_session.commit()

        r = client.get("/api/debug/fetch-runs")
        assert r.status_code == 200
        data = r.json()
        assert len(data) == 1
        assert data[0]["status"] == "failed"

    def test_excludes_disabled_sources(self, client, db_session):
        src = Source(name="disabled_src", kind="rss", enabled=False)
        db_session.add(src)
        db_session.commit()

        r = client.get("/api/debug/fetch-runs")
        assert r.status_code == 200
        assert r.json() == []


class TestQuarantine:
    def test_returns_empty_when_no_quarantined(self, client):
        r = client.get("/api/debug/quarantine")
        assert r.status_code == 200
        assert r.json() == []

    def test_returns_quarantined_articles(self, client, db_session):
        src = _make_source(db_session)
        _make_article(db_session, src, status="quarantined")
        db_session.commit()

        r = client.get("/api/debug/quarantine")
        assert r.status_code == 200
        data = r.json()
        assert len(data) == 1
        assert data[0]["injection_score"] == pytest.approx(0.92)
        assert "promo_pattern" in data[0]["matched_rules"]

    def test_excludes_active_articles(self, client, db_session):
        src = _make_source(db_session)
        _make_article(db_session, src, status="active")
        db_session.commit()

        r = client.get("/api/debug/quarantine")
        assert r.status_code == 200
        assert r.json() == []


class TestReleaseQuarantine:
    def test_release_sets_status_active(self, client, db_session):
        src = _make_source(db_session)
        art = _make_article(db_session, src, status="quarantined")
        db_session.commit()

        r = client.post(f"/api/debug/quarantine/{art.id}/release")
        assert r.status_code == 200
        assert r.json() == {"ok": True}

        db_session.refresh(art)
        assert art.status == "active"

    def test_release_returns_404_for_unknown(self, client):
        r = client.post("/api/debug/quarantine/9999/release")
        assert r.status_code == 404

    def test_release_returns_400_for_active_article(self, client, db_session):
        src = _make_source(db_session)
        art = _make_article(db_session, src, status="active")
        db_session.commit()

        r = client.post(f"/api/debug/quarantine/{art.id}/release")
        assert r.status_code == 400


class TestVerificationLog:
    def test_returns_empty_when_no_failures(self, client):
        r = client.get("/api/debug/verification-log")
        assert r.status_code == 200
        assert r.json() == []

    def test_returns_failed_checks_only(self, client, db_session):
        from app.models.news import StoryCluster

        cluster = StoryCluster(
            first_seen_at=_utc(2),
            last_seen_at=_utc(1),
            article_count=1,
            publisher_count=1,
        )
        db_session.add(cluster)
        db_session.flush()

        story = Story(
            cluster_id=cluster.id,
            title_bg="История",
            summary_bg="Обобщение",
            tickers=[],
            verification_status="partially_supported",
            model_version="test",
            prompt_version="test:abc",
            created_at=_utc(1),
        )
        db_session.add(story)
        db_session.flush()

        db_session.add(VerificationLog(
            story_id=story.id,
            check="quote_exists",
            passed=False,
            details="Quote not found",
            created_at=_utc(0),
        ))
        db_session.add(VerificationLog(
            story_id=story.id,
            check="quote_exists",
            passed=True,
            details=None,
            created_at=_utc(0),
        ))
        db_session.commit()

        r = client.get("/api/debug/verification-log")
        assert r.status_code == 200
        data = r.json()
        assert len(data) == 1
        assert data[0]["passed"] is False
        assert data[0]["check"] == "quote_exists"
        assert data[0]["details"] == "Quote not found"


class TestCosts:
    def test_returns_zero_costs_when_empty(self, client):
        r = client.get("/api/debug/costs")
        assert r.status_code == 200
        data = r.json()
        assert data["today_usd"] == 0.0
        assert data["month_usd"] == 0.0
        assert data["by_purpose"] == []

    def test_sums_costs_by_purpose(self, client, db_session):
        now = datetime.now(UTC).replace(tzinfo=None)
        for purpose, cost in [("classify", 0.03), ("summarize", 0.07)]:
            db_session.add(LlmCall(
                purpose=purpose,
                model="test-model",
                prompt_version="test:abc",
                input_tokens=100,
                output_tokens=50,
                cost_usd=cost,
                latency_ms=500,
                status="ok",
                created_at=now,
            ))
        db_session.commit()

        r = client.get("/api/debug/costs")
        assert r.status_code == 200
        data = r.json()
        assert data["today_usd"] == pytest.approx(0.10, abs=1e-6)
        assert data["month_usd"] == pytest.approx(0.10, abs=1e-6)
        purposes = {p["purpose"]: p["cost_usd"] for p in data["by_purpose"]}
        assert purposes["classify"] == pytest.approx(0.03)
        assert purposes["summarize"] == pytest.approx(0.07)
