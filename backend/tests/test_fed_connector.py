from pathlib import Path

import httpx2
import pytest

from app.ingestion.fed import FedPressRSS

FIXTURES = Path(__file__).parent / "fixtures" / "sources"


@pytest.fixture
def fed_transport():
    content = (FIXTURES / "fed_press_all.xml").read_bytes()

    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(200, content=content)

    return httpx2.MockTransport(handler)


def test_fed_returns_articles(fed_transport):
    connector = FedPressRSS(transport=fed_transport)
    articles = connector.fetch()
    assert len(articles) == 3


def test_fed_publisher_is_federal_reserve(fed_transport):
    connector = FedPressRSS(transport=fed_transport)
    articles = connector.fetch()
    assert all(a.publisher == "Federal Reserve" for a in articles)


def test_fed_published_at_is_utc_naive(fed_transport):
    connector = FedPressRSS(transport=fed_transport)
    articles = connector.fetch()
    for a in articles:
        assert a.published_at.tzinfo is None


def test_fed_tickers_raw_is_empty(fed_transport):
    connector = FedPressRSS(transport=fed_transport)
    articles = connector.fetch()
    assert all(a.tickers_raw == [] for a in articles)


def test_fed_network_error_returns_empty():
    def failing_handler(request):
        raise httpx2.NetworkError("connection refused")

    connector = FedPressRSS(transport=httpx2.MockTransport(failing_handler))
    articles = connector.fetch()
    assert articles == []


def test_fed_http_error_returns_empty():
    def error_handler(request):
        return httpx2.Response(503)

    connector = FedPressRSS(transport=httpx2.MockTransport(error_handler))
    articles = connector.fetch()
    assert articles == []
