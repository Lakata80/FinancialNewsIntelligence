from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.deps import get_db
from app.core.db import Base
from app.main import app
from app.models.news import Article, Source


@pytest.fixture
def db_engine():
    # StaticPool forces SQLite in-memory to use a single connection across
    # threads — required because FastAPI runs sync endpoints in a thread pool.
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


def _utc_naive(hours_ago: int = 0) -> datetime:
    return (datetime.now(UTC) - timedelta(hours=hours_ago)).replace(tzinfo=None)


def _add_source(session, name="test_source") -> Source:
    source = Source(name=name, kind="rss", enabled=True)
    session.add(source)
    session.flush()
    return source


def _add_article(session, source: Source, ticker: str, hours_ago: int = 1) -> Article:
    article = Article(
        source_id=source.id,
        title=f"Article about {ticker}",
        url=f"https://example.com/{ticker.lower()}-{hours_ago}",
        canonical_url=f"https://example.com/{ticker.lower()}-{hours_ago}",
        published_at=_utc_naive(hours_ago),
        fetched_at=_utc_naive(0),
        tickers_raw=[ticker],
        raw_payload={},
    )
    session.add(article)
    session.commit()
    return article


class TestHealthEndpoint:
    def test_api_health_returns_ok(self, client):
        r = client.get("/api/health")
        assert r.status_code == 200
        assert r.json() == {"status": "ok"}

    def test_legacy_health_still_works(self, client):
        r = client.get("/health")
        assert r.status_code == 200


class TestListArticles:
    def test_returns_empty_when_no_articles(self, client):
        r = client.get("/api/articles")
        assert r.status_code == 200
        assert r.json() == []

    def test_returns_articles_within_window(self, client, db_session):
        source = _add_source(db_session)
        _add_article(db_session, source, "NVDA", hours_ago=2)
        r = client.get("/api/articles?hours=6")
        assert r.status_code == 200
        assert len(r.json()) == 1

    def test_excludes_articles_outside_window(self, client, db_session):
        source = _add_source(db_session)
        _add_article(db_session, source, "NVDA", hours_ago=30)
        r = client.get("/api/articles?hours=6")
        assert r.status_code == 200
        assert r.json() == []

    def test_ticker_filter_returns_matching(self, client, db_session):
        source = _add_source(db_session)
        _add_article(db_session, source, "NVDA", hours_ago=1)
        _add_article(db_session, source, "MSFT", hours_ago=1)
        r = client.get("/api/articles?ticker=NVDA&hours=6")
        assert r.status_code == 200
        data = r.json()
        assert len(data) == 1
        assert "NVDA" in data[0]["tickers_raw"]

    def test_response_schema_fields_present(self, client, db_session):
        source = _add_source(db_session)
        _add_article(db_session, source, "AAPL", hours_ago=1)
        r = client.get("/api/articles")
        assert r.status_code == 200
        item = r.json()[0]
        expected_fields = (
            "id", "source_id", "title", "url", "canonical_url",
            "published_at", "fetched_at", "tickers_raw",
        )
        for field in expected_fields:
            assert field in item, f"Missing field: {field}"

    def test_hours_param_validation(self, client):
        r = client.get("/api/articles?hours=0")
        assert r.status_code == 422

        r = client.get("/api/articles?hours=200")
        assert r.status_code == 422

    def test_results_ordered_newest_first(self, client, db_session):
        source = _add_source(db_session)
        _add_article(db_session, source, "NVDA", hours_ago=3)
        _add_article(db_session, source, "NVDA", hours_ago=1)
        r = client.get("/api/articles?hours=6")
        assert r.status_code == 200
        data = r.json()
        assert data[0]["published_at"] > data[1]["published_at"]
