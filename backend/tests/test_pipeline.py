from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx2
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.db import Base
from app.ingestion.base import RawArticle, SourceConnector
from app.ingestion.fed import FedPressRSS
from app.ingestion.pipeline import run_all_connectors, run_connector
from app.models.news import Article, FetchRun

FIXTURES = Path(__file__).parent / "fixtures" / "sources"


@pytest.fixture
def mem_session_factory():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    yield factory
    Base.metadata.drop_all(engine)


def _utc_naive(dt: datetime) -> datetime:
    return dt.replace(tzinfo=None)


def _now() -> datetime:
    return _utc_naive(datetime.now(UTC))


class _StaticConnector(SourceConnector):
    source_name = "test_static"
    source_kind = "rss"

    def __init__(self, articles: list[RawArticle]) -> None:
        self._articles = articles

    def fetch(self) -> list[RawArticle]:
        return list(self._articles)


class _FailingConnector(SourceConnector):
    source_name = "test_failing"
    source_kind = "rss"

    def fetch(self) -> list[RawArticle]:
        raise RuntimeError("simulated failure")


def _make_articles(n: int, published_at: datetime | None = None) -> list[RawArticle]:
    ts = published_at or _now()
    return [
        RawArticle(
            source_name="test_static",
            title=f"Article {i}",
            url=f"https://example.com/article-{i}",
            published_at=ts,
        )
        for i in range(n)
    ]


class TestIdempotency:
    def test_second_run_adds_no_new_articles(self, mem_session_factory):
        articles = _make_articles(3)
        connector = _StaticConnector(articles)

        r1 = run_connector(connector, session_factory=mem_session_factory)
        assert r1.items_new == 3

        r2 = run_connector(connector, session_factory=mem_session_factory)
        assert r2.items_seen == 3
        assert r2.items_new == 0

    def test_duplicate_url_not_inserted_twice(self, mem_session_factory):
        articles = _make_articles(1)
        connector = _StaticConnector(articles)

        run_connector(connector, session_factory=mem_session_factory)
        run_connector(connector, session_factory=mem_session_factory)

        with mem_session_factory() as s:
            count = s.query(Article).count()
        assert count == 1

    def test_tracking_param_urls_are_deduplicated(self, mem_session_factory):
        ts = _now()
        url_with_tracking = "https://example.com/s?id=1&utm_source=x"
        a1 = RawArticle("test_static", "Story", url_with_tracking, ts)
        a2 = RawArticle("test_static", "Story", "https://example.com/s?id=1", ts)

        run_connector(_StaticConnector([a1]), session_factory=mem_session_factory)
        r2 = run_connector(_StaticConnector([a2]), session_factory=mem_session_factory)

        assert r2.items_new == 0


class TestStaleDetection:
    def test_fresh_source_is_ok(self, mem_session_factory):
        articles = _make_articles(1, published_at=_now() - timedelta(hours=24))
        sf = mem_session_factory
        result = run_connector(_StaticConnector(articles), session_factory=sf)
        assert result.status == "ok"

    def test_stale_source_detected(self, mem_session_factory):
        old_ts = _now() - timedelta(hours=50)
        articles = _make_articles(1, published_at=old_ts)
        sf = mem_session_factory
        result = run_connector(_StaticConnector(articles), session_factory=sf)
        assert result.status == "stale"

    def test_no_articles_is_ok_not_stale(self, mem_session_factory):
        sf = mem_session_factory
        result = run_connector(_StaticConnector([]), session_factory=sf)
        assert result.status == "ok"
        assert result.newest_at is None


class TestFailureIsolation:
    def test_failing_connector_returns_error_result(self, mem_session_factory):
        result = run_connector(_FailingConnector(), session_factory=mem_session_factory)
        assert result.status == "error"
        assert result.error is not None
        assert "simulated failure" in result.error

    def test_run_all_continues_after_one_failure(self, mem_session_factory):
        articles = _make_articles(2)
        connectors = [_FailingConnector(), _StaticConnector(articles)]
        results = run_all_connectors(connectors, session_factory=mem_session_factory)

        assert results[0].status == "error"
        assert results[1].status == "ok"
        assert results[1].items_new == 2

    def test_fetch_run_recorded_on_error(self, mem_session_factory):
        run_connector(_FailingConnector(), session_factory=mem_session_factory)
        with mem_session_factory() as s:
            run = s.query(FetchRun).filter_by(status="error").first()
        assert run is not None
        assert run.error is not None
        assert run.finished_at is not None

    def test_fetch_run_recorded_on_success(self, mem_session_factory):
        articles = _make_articles(2)
        run_connector(_StaticConnector(articles), session_factory=mem_session_factory)
        with mem_session_factory() as s:
            run = s.query(FetchRun).filter(FetchRun.status.in_(["ok", "stale"])).first()
        assert run is not None
        assert run.items_seen == 2
        assert run.items_new == 2
        assert run.finished_at is not None


class TestFedConnectorIntegration:
    def test_fed_articles_persisted(self, mem_session_factory):
        content = (FIXTURES / "fed_press_all.xml").read_bytes()

        def handler(request: httpx2.Request) -> httpx2.Response:
            return httpx2.Response(200, content=content)

        connector = FedPressRSS(transport=httpx2.MockTransport(handler))
        result = run_connector(connector, session_factory=mem_session_factory)
        assert result.items_new == 3
        assert result.status in ("ok", "stale")
