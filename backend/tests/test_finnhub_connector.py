from datetime import UTC, datetime
from pathlib import Path

import httpx2
import pytest

from app.ingestion.finnhub import FinnhubCompanyNews

FIXTURES = Path(__file__).parent / "fixtures" / "sources"


def _finnhub_transport():
    company_news = (FIXTURES / "finnhub_company_news.json").read_bytes()
    general_news = (FIXTURES / "finnhub_general_news.json").read_bytes()

    def handler(request: httpx2.Request) -> httpx2.Response:
        url = str(request.url)
        if "company-news" in url:
            return httpx2.Response(200, content=company_news)
        if "/news" in url:
            return httpx2.Response(200, content=general_news)
        return httpx2.Response(404)

    return httpx2.MockTransport(handler)


@pytest.fixture(autouse=True)
def set_api_key(monkeypatch):
    monkeypatch.setattr("app.ingestion.finnhub.settings.finnhub_api_key", "test-key")
    monkeypatch.setattr("app.ingestion.finnhub.settings.watchlist", ["NVDA"])


def test_finnhub_parses_company_news():
    connector = FinnhubCompanyNews(transport=_finnhub_transport())
    articles = connector.fetch()
    titles = [a.title for a in articles]
    assert "Nvidia Q3 Results Beat Expectations" in titles


def test_finnhub_published_at_from_unix_timestamp():
    connector = FinnhubCompanyNews(transport=_finnhub_transport())
    articles = connector.fetch()
    title = "Nvidia Q3 Results Beat Expectations"
    company = [a for a in articles if a.title == title][0]
    expected = datetime.fromtimestamp(1759737000, tz=UTC).replace(tzinfo=None)
    assert company.published_at == expected


def test_finnhub_tickers_raw_populated():
    connector = FinnhubCompanyNews(transport=_finnhub_transport())
    articles = connector.fetch()
    company = [a for a in articles if "NVDA" in (a.tickers_raw or [])][0]
    assert "NVDA" in company.tickers_raw


def test_finnhub_raw_payload_stores_full_dict():
    connector = FinnhubCompanyNews(transport=_finnhub_transport())
    articles = connector.fetch()
    title = "Nvidia Q3 Results Beat Expectations"
    company = [a for a in articles if a.title == title][0]
    assert company.raw_payload.get("id") == 10001
    assert company.raw_payload.get("source") == "Reuters"


def test_finnhub_general_news_has_empty_tickers():
    connector = FinnhubCompanyNews(transport=_finnhub_transport())
    articles = connector.fetch()
    fed = [a for a in articles if "Federal Reserve" in a.title][0]
    assert fed.tickers_raw == []


def test_finnhub_missing_api_key_returns_empty(monkeypatch):
    monkeypatch.setattr("app.ingestion.finnhub.settings.finnhub_api_key", "")
    connector = FinnhubCompanyNews(transport=_finnhub_transport())
    articles = connector.fetch()
    assert articles == []
