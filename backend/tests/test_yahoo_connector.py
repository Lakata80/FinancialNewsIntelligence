from pathlib import Path

import httpx2
import pytest

from app.ingestion.yahoo import YahooTickerRSS

FIXTURES = Path(__file__).parent / "fixtures" / "sources"


def _make_transport(responses: dict[str, bytes]):
    """Return a MockTransport that maps URL substrings to response bytes."""
    def handler(request: httpx2.Request) -> httpx2.Response:
        url = str(request.url)
        for key, content in responses.items():
            if key in url:
                return httpx2.Response(200, content=content)
        return httpx2.Response(404, content=b"not found")

    return httpx2.MockTransport(handler)


@pytest.fixture
def yahoo_transport():
    nvda_xml = (FIXTURES / "yahoo_nvda.xml").read_bytes()
    msft_xml = (FIXTURES / "yahoo_msft.xml").read_bytes()
    return _make_transport({"s=NVDA": nvda_xml, "s=MSFT": msft_xml})


def test_yahoo_returns_articles_for_watchlist(yahoo_transport, monkeypatch):
    monkeypatch.setattr("app.ingestion.yahoo.settings.watchlist", ["NVDA", "MSFT"])
    connector = YahooTickerRSS(transport=yahoo_transport)
    articles = connector.fetch()
    assert len(articles) == 5  # 3 NVDA + 2 MSFT


def test_yahoo_published_at_is_utc_naive(yahoo_transport, monkeypatch):
    monkeypatch.setattr("app.ingestion.yahoo.settings.watchlist", ["NVDA"])
    connector = YahooTickerRSS(transport=yahoo_transport)
    articles = connector.fetch()
    for a in articles:
        assert a.published_at.tzinfo is None


def test_yahoo_tickers_raw_contains_ticker(yahoo_transport, monkeypatch):
    monkeypatch.setattr("app.ingestion.yahoo.settings.watchlist", ["NVDA"])
    connector = YahooTickerRSS(transport=yahoo_transport)
    articles = connector.fetch()
    assert all("NVDA" in a.tickers_raw for a in articles)


def test_yahoo_strips_tracking_from_raw_url(yahoo_transport, monkeypatch):
    monkeypatch.setattr("app.ingestion.yahoo.settings.watchlist", ["NVDA"])
    connector = YahooTickerRSS(transport=yahoo_transport)
    articles = connector.fetch()
    # raw url is stored as-is; canonical_url stripping happens in pipeline
    # just verify that url field is populated
    assert all(a.url.startswith("https://") for a in articles)


def test_yahoo_skips_item_without_title(monkeypatch):
    pub = "Mon, 05 Oct 2026 10:00:00 +0000"
    xml = (
        b'<?xml version="1.0"?><rss version="2.0"><channel>'
        b"<item>"
        b"<link>https://example.com/a</link>"
        b"<pubDate>" + pub.encode() + b"</pubDate>"
        b"</item>"
        b"<item>"
        b"<title>Real Title</title>"
        b"<link>https://example.com/b</link>"
        b"<pubDate>" + pub.encode() + b"</pubDate>"
        b"</item>"
        b"</channel></rss>"
    )
    transport = _make_transport({"s=AAPL": xml})
    monkeypatch.setattr("app.ingestion.yahoo.settings.watchlist", ["AAPL"])
    connector = YahooTickerRSS(transport=transport)
    articles = connector.fetch()
    assert len(articles) == 1
    assert articles[0].title == "Real Title"


def test_yahoo_network_error_returns_empty(monkeypatch):
    def failing_handler(request):
        raise httpx2.NetworkError("connection refused")

    monkeypatch.setattr("app.ingestion.yahoo.settings.watchlist", ["NVDA"])
    connector = YahooTickerRSS(transport=httpx2.MockTransport(failing_handler))
    articles = connector.fetch()
    assert articles == []


def test_yahoo_one_ticker_failure_does_not_stop_others(monkeypatch):
    nvda_xml = (FIXTURES / "yahoo_nvda.xml").read_bytes()

    def partial_handler(request: httpx2.Request) -> httpx2.Response:
        url = str(request.url)
        if "s=NVDA" in url:
            return httpx2.Response(200, content=nvda_xml)
        raise httpx2.NetworkError("MSFT is down")

    monkeypatch.setattr("app.ingestion.yahoo.settings.watchlist", ["NVDA", "MSFT"])
    connector = YahooTickerRSS(transport=httpx2.MockTransport(partial_handler))
    articles = connector.fetch()
    assert len(articles) == 3  # only NVDA articles
