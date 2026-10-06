"""Tests for /api/stories, /api/funnel, /api/watchlist endpoints."""
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.deps import get_db
from app.core.db import Base
from app.main import app
from app.models.news import (
    Article,
    ClusterMember,
    FactEvidence,
    Source,
    Story,
    StoryCluster,
    StoryFact,
)


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


def _make_article(
    session,
    source: Source,
    ticker: str = "NVDA",
    hours_ago: int = 1,
    status: str = "active",
) -> Article:
    a = Article(
        source_id=source.id,
        publisher="Test Publisher",
        title=f"Article about {ticker}",
        url=f"https://example.com/{ticker.lower()}-{hours_ago}",
        canonical_url=f"https://example.com/{ticker.lower()}-{hours_ago}",
        published_at=_utc(hours_ago),
        fetched_at=_utc(0),
        tickers_raw=[ticker],
        raw_payload={},
        status=status,
    )
    session.add(a)
    session.flush()
    return a


def _make_cluster(
    session,
    ticker: str = "NVDA",
    hours_ago: int = 1,
    visible: bool = True,
    is_main_subject: bool | None = True,
    is_opinion: bool = False,
) -> StoryCluster:
    c = StoryCluster(
        primary_ticker=ticker,
        first_seen_at=_utc(hours_ago + 1),
        last_seen_at=_utc(hours_ago),
        article_count=1,
        publisher_count=1,
        visible=visible,
        is_main_subject=is_main_subject,
        is_opinion=is_opinion,
        classification_model="claude-haiku-4-5",
    )
    session.add(c)
    session.flush()
    return c


def _make_story(
    session,
    cluster: StoryCluster,
    verification_status: str = "verified",
    is_opinion: bool = False,
) -> Story:
    s = Story(
        cluster_id=cluster.id,
        title_bg="Тестова история",
        summary_bg="Тестово обобщение",
        tickers=[cluster.primary_ticker] if cluster.primary_ticker else [],
        verification_status=verification_status,
        is_opinion=is_opinion,
        model_version="claude-sonnet-4-6",
        prompt_version="test:abc12345",
        created_at=_utc(1),
    )
    session.add(s)
    session.flush()
    return s


def _link(session, cluster: StoryCluster, article: Article) -> None:
    session.add(
        ClusterMember(
            cluster_id=cluster.id,
            article_id=article.id,
            match_method="exact_hash",
            similarity=1.0,
        )
    )
    session.flush()


class TestListStories:
    def test_empty_returns_empty_list(self, client):
        r = client.get("/api/stories")
        assert r.status_code == 200
        assert r.json() == []

    def test_returns_story_within_window(self, client, db_session):
        src = _make_source(db_session)
        art = _make_article(db_session, src, "NVDA", hours_ago=2)
        cluster = _make_cluster(db_session, "NVDA", hours_ago=2)
        _link(db_session, cluster, art)
        story = _make_story(db_session, cluster)
        db_session.commit()

        r = client.get("/api/stories?hours=24")
        assert r.status_code == 200
        data = r.json()
        assert len(data) == 1
        assert data[0]["id"] == story.id
        assert data[0]["tickers"] == ["NVDA"]

    def test_excludes_story_outside_window(self, client, db_session):
        src = _make_source(db_session)
        art = _make_article(db_session, src, "NVDA", hours_ago=30)
        cluster = _make_cluster(db_session, "NVDA", hours_ago=30)
        _link(db_session, cluster, art)
        _make_story(db_session, cluster)
        db_session.commit()

        r = client.get("/api/stories?hours=6")
        assert r.status_code == 200
        assert r.json() == []

    def test_ticker_filter(self, client, db_session):
        src = _make_source(db_session)
        for ticker in ("NVDA", "AAPL"):
            art = _make_article(db_session, src, ticker, hours_ago=1)
            cluster = _make_cluster(db_session, ticker, hours_ago=1)
            _link(db_session, cluster, art)
            _make_story(db_session, cluster)
        db_session.commit()

        r = client.get("/api/stories?ticker=NVDA")
        assert r.status_code == 200
        data = r.json()
        assert len(data) == 1
        assert data[0]["tickers"] == ["NVDA"]

    def test_show_opinions_false_hides_opinion_story(self, client, db_session):
        src = _make_source(db_session)
        art = _make_article(db_session, src, "NVDA", hours_ago=1)
        cluster = _make_cluster(db_session, "NVDA", hours_ago=1)
        _link(db_session, cluster, art)
        _make_story(db_session, cluster, is_opinion=True)
        db_session.commit()

        r = client.get("/api/stories?show_opinions=false")
        assert r.status_code == 200
        assert r.json() == []

    def test_show_opinions_true_includes_opinion_story(self, client, db_session):
        src = _make_source(db_session)
        art = _make_article(db_session, src, "NVDA", hours_ago=1)
        cluster = _make_cluster(db_session, "NVDA", hours_ago=1, is_opinion=True)
        _link(db_session, cluster, art)
        _make_story(db_session, cluster, is_opinion=True)
        db_session.commit()

        r = client.get("/api/stories?show_opinions=true")
        assert r.status_code == 200
        assert len(r.json()) == 1

    def test_show_hidden_false_hides_invisible_story(self, client, db_session):
        src = _make_source(db_session)
        art = _make_article(db_session, src, "NVDA", hours_ago=1)
        cluster = _make_cluster(db_session, "NVDA", hours_ago=1, visible=False)
        _link(db_session, cluster, art)
        _make_story(db_session, cluster)
        db_session.commit()

        r = client.get("/api/stories?show_hidden=false")
        assert r.status_code == 200
        assert r.json() == []

    def test_source_articles_included(self, client, db_session):
        src = _make_source(db_session)
        art = _make_article(db_session, src, "NVDA", hours_ago=1)
        cluster = _make_cluster(db_session, "NVDA", hours_ago=1)
        _link(db_session, cluster, art)
        _make_story(db_session, cluster)
        db_session.commit()

        r = client.get("/api/stories")
        assert r.status_code == 200
        data = r.json()
        assert len(data[0]["source_articles"]) == 1
        assert data[0]["source_articles"][0]["url"] == art.url


class TestGetStory:
    def test_404_for_unknown_id(self, client):
        r = client.get("/api/stories/9999")
        assert r.status_code == 404

    def test_returns_story_with_facts_and_evidence(self, client, db_session):
        src = _make_source(db_session)
        art = _make_article(db_session, src, "NVDA", hours_ago=1)
        cluster = _make_cluster(db_session, "NVDA", hours_ago=1)
        _link(db_session, cluster, art)
        story = _make_story(db_session, cluster)

        fact = StoryFact(
            story_id=story.id,
            fact_order=0,
            text_bg="Тестов факт",
            verification_status="verified",
        )
        db_session.add(fact)
        db_session.flush()

        evidence = FactEvidence(
            fact_id=fact.id,
            article_id=art.id,
            quote_en="Test verbatim quote from article",
        )
        db_session.add(evidence)
        db_session.commit()

        r = client.get(f"/api/stories/{story.id}")
        assert r.status_code == 200
        data = r.json()
        assert data["id"] == story.id
        assert len(data["facts"]) == 1
        assert data["facts"][0]["text_bg"] == "Тестов факт"
        assert len(data["facts"][0]["evidence"]) == 1
        assert data["facts"][0]["evidence"][0]["quote_en"] == "Test verbatim quote from article"


class TestFunnel:
    def test_returns_zero_counts_when_empty(self, client):
        r = client.get("/api/funnel")
        assert r.status_code == 200
        data = r.json()
        assert data == {"articles": 0, "clusters": 0, "relevant": 0}

    def test_counts_articles_and_clusters(self, client, db_session):
        src = _make_source(db_session)
        _make_article(db_session, src, "NVDA", hours_ago=1)
        _make_cluster(db_session, "NVDA", hours_ago=1)
        db_session.commit()

        r = client.get("/api/funnel?hours=24")
        assert r.status_code == 200
        data = r.json()
        assert data["articles"] == 1
        assert data["clusters"] == 1

    def test_relevant_counts_visible_main_subject(self, client, db_session):
        src = _make_source(db_session)
        _make_article(db_session, src, "NVDA", hours_ago=1)
        _make_cluster(db_session, "NVDA", hours_ago=1, visible=True, is_main_subject=True)
        _make_cluster(db_session, "NVDA", hours_ago=1, visible=False, is_main_subject=False)
        db_session.commit()

        r = client.get("/api/funnel?hours=24")
        assert r.status_code == 200
        data = r.json()
        assert data["relevant"] == 1


class TestWatchlist:
    def test_returns_watchlist(self, client):
        r = client.get("/api/watchlist")
        assert r.status_code == 200
        data = r.json()
        assert "items" in data
        items = data["items"]
        tickers = [i["id"] for i in items if i["kind"] == "ticker"]
        assert "NVDA" in tickers
