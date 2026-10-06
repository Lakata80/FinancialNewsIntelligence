from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import httpx2
import pytest

FIXTURES = Path(__file__).parent / "fixtures" / "sources"


def _make_transport(responses: dict[str, bytes]):
    def handler(request: httpx2.Request) -> httpx2.Response:
        url = str(request.url)
        for key, content in responses.items():
            if key in url:
                return httpx2.Response(200, content=content)
        return httpx2.Response(404, content=b'{"error": "not found"}')
    return httpx2.MockTransport(handler)


@pytest.fixture
def sec_transport():
    nvda_data = (FIXTURES / "sec_submissions_nvda.json").read_bytes()
    tickers_data = (FIXTURES / "sec_company_tickers.json").read_bytes()
    return _make_transport({
        "CIK0001045810.json": nvda_data,
        "company_tickers.json": tickers_data,
    })


def test_missing_user_agent_raises(monkeypatch):
    monkeypatch.setattr("app.ingestion.sec_edgar.settings.sec_user_agent", "")
    from app.ingestion.sec_edgar import SecEdgarConnector
    with pytest.raises(RuntimeError, match="SEC_USER_AGENT"):
        SecEdgarConnector()


def test_fetch_returns_articles(sec_transport, monkeypatch):
    monkeypatch.setattr("app.ingestion.sec_edgar.settings.sec_user_agent", "TestApp test@test.com")
    monkeypatch.setattr("app.ingestion.sec_edgar.settings.watchlist", ["NVDA"])
    from app.ingestion.sec_edgar import SecEdgarConnector
    connector = SecEdgarConnector(transport=sec_transport)
    articles = connector.fetch()
    assert len(articles) > 0


def test_fetch_sets_publisher(sec_transport, monkeypatch):
    monkeypatch.setattr("app.ingestion.sec_edgar.settings.sec_user_agent", "TestApp test@test.com")
    monkeypatch.setattr("app.ingestion.sec_edgar.settings.watchlist", ["NVDA"])
    from app.ingestion.sec_edgar import SecEdgarConnector
    connector = SecEdgarConnector(transport=sec_transport)
    articles = connector.fetch()
    assert all(a.publisher == "SEC EDGAR" for a in articles)


def test_fetch_sets_ticker(sec_transport, monkeypatch):
    monkeypatch.setattr("app.ingestion.sec_edgar.settings.sec_user_agent", "TestApp test@test.com")
    monkeypatch.setattr("app.ingestion.sec_edgar.settings.watchlist", ["NVDA"])
    from app.ingestion.sec_edgar import SecEdgarConnector
    connector = SecEdgarConnector(transport=sec_transport)
    articles = connector.fetch()
    assert all("NVDA" in a.tickers_raw for a in articles)


def test_8k_item_2_02_maps_to_earnings(sec_transport, monkeypatch):
    monkeypatch.setattr("app.ingestion.sec_edgar.settings.sec_user_agent", "TestApp test@test.com")
    monkeypatch.setattr("app.ingestion.sec_edgar.settings.watchlist", ["NVDA"])
    from app.ingestion.sec_edgar import SecEdgarConnector
    connector = SecEdgarConnector(transport=sec_transport)
    articles = connector.fetch()
    # First filing in fixture is 8-K with items "2.02,9.01"
    earnings_articles = [a for a in articles if a.raw_payload.get("items") == "2.02,9.01"]
    assert len(earnings_articles) > 0
    assert earnings_articles[0].raw_payload["event_type_hint"] == "earnings"


def test_10q_maps_to_earnings(sec_transport, monkeypatch):
    monkeypatch.setattr("app.ingestion.sec_edgar.settings.sec_user_agent", "TestApp test@test.com")
    monkeypatch.setattr("app.ingestion.sec_edgar.settings.watchlist", ["NVDA"])
    from app.ingestion.sec_edgar import SecEdgarConnector
    connector = SecEdgarConnector(transport=sec_transport)
    articles = connector.fetch()
    ten_q = [a for a in articles if a.raw_payload.get("form") == "10-Q"]
    assert len(ten_q) > 0
    assert all(a.raw_payload["event_type_hint"] == "earnings" for a in ten_q)


def test_8k_item_5_02_maps_to_executive_change(sec_transport, monkeypatch):
    monkeypatch.setattr("app.ingestion.sec_edgar.settings.sec_user_agent", "TestApp test@test.com")
    monkeypatch.setattr("app.ingestion.sec_edgar.settings.watchlist", ["NVDA"])
    from app.ingestion.sec_edgar import SecEdgarConnector
    connector = SecEdgarConnector(transport=sec_transport)
    articles = connector.fetch()
    exec_change = [a for a in articles if a.raw_payload.get("items") == "5.02,9.01"]
    assert len(exec_change) > 0
    assert exec_change[0].raw_payload["event_type_hint"] == "executive_change"


def test_8k_item_1_01_maps_to_merger_acquisition(sec_transport, monkeypatch):
    monkeypatch.setattr("app.ingestion.sec_edgar.settings.sec_user_agent", "TestApp test@test.com")
    monkeypatch.setattr("app.ingestion.sec_edgar.settings.watchlist", ["NVDA"])
    from app.ingestion.sec_edgar import SecEdgarConnector
    connector = SecEdgarConnector(transport=sec_transport)
    articles = connector.fetch()
    ma = [a for a in articles if a.raw_payload.get("items") == "1.01,9.01"]
    assert len(ma) > 0
    assert ma[0].raw_payload["event_type_hint"] == "merger_acquisition"


def test_published_at_is_utc_naive(sec_transport, monkeypatch):
    monkeypatch.setattr("app.ingestion.sec_edgar.settings.sec_user_agent", "TestApp test@test.com")
    monkeypatch.setattr("app.ingestion.sec_edgar.settings.watchlist", ["NVDA"])
    from app.ingestion.sec_edgar import SecEdgarConnector
    connector = SecEdgarConnector(transport=sec_transport)
    articles = connector.fetch()
    for a in articles:
        assert a.published_at.tzinfo is None


def test_user_agent_header_sent(monkeypatch):
    monkeypatch.setattr("app.ingestion.sec_edgar.settings.sec_user_agent", "TestApp test@test.com")
    monkeypatch.setattr("app.ingestion.sec_edgar.settings.watchlist", ["NVDA"])

    seen_headers: list[dict] = []
    nvda_data = (FIXTURES / "sec_submissions_nvda.json").read_bytes()
    tickers_data = (FIXTURES / "sec_company_tickers.json").read_bytes()

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen_headers.append(dict(request.headers))
        url = str(request.url)
        if "CIK0001045810.json" in url:
            return httpx2.Response(200, content=nvda_data)
        if "company_tickers.json" in url:
            return httpx2.Response(200, content=tickers_data)
        return httpx2.Response(404, content=b"{}")

    from app.ingestion.sec_edgar import SecEdgarConnector
    connector = SecEdgarConnector(transport=httpx2.MockTransport(handler))
    connector.fetch()
    assert any("user-agent" in h for h in seen_headers)
    assert any("TestApp" in h.get("user-agent", "") for h in seen_headers)


def test_404_returns_empty_not_raises(monkeypatch):
    monkeypatch.setattr("app.ingestion.sec_edgar.settings.sec_user_agent", "TestApp test@test.com")
    monkeypatch.setattr("app.ingestion.sec_edgar.settings.watchlist", ["NVDA"])

    tickers_data = (FIXTURES / "sec_company_tickers.json").read_bytes()

    def handler(request: httpx2.Request) -> httpx2.Response:
        if "company_tickers.json" in str(request.url):
            return httpx2.Response(200, content=tickers_data)
        return httpx2.Response(404, content=b'{"error": "not found"}')

    from app.ingestion.sec_edgar import SecEdgarConnector
    connector = SecEdgarConnector(transport=httpx2.MockTransport(handler))
    articles = connector.fetch()
    assert articles == []


def test_unknown_ticker_skipped(monkeypatch):
    monkeypatch.setattr("app.ingestion.sec_edgar.settings.sec_user_agent", "TestApp test@test.com")
    monkeypatch.setattr("app.ingestion.sec_edgar.settings.watchlist", ["ZZZUNKNOWN"])

    tickers_data = (FIXTURES / "sec_company_tickers.json").read_bytes()

    def handler(request: httpx2.Request) -> httpx2.Response:
        if "company_tickers.json" in str(request.url):
            return httpx2.Response(200, content=tickers_data)
        return httpx2.Response(200, content=b'{"filings": {"recent": {}}}')

    from app.ingestion.sec_edgar import SecEdgarConnector
    connector = SecEdgarConnector(transport=httpx2.MockTransport(handler))
    articles = connector.fetch()
    assert articles == []


def test_rate_limiter_called_per_ticker(monkeypatch):
    monkeypatch.setattr("app.ingestion.sec_edgar.settings.sec_user_agent", "TestApp test@test.com")
    monkeypatch.setattr("app.ingestion.sec_edgar.settings.watchlist", ["NVDA", "AAPL"])

    nvda_data = (FIXTURES / "sec_submissions_nvda.json").read_bytes()
    tickers_data = (FIXTURES / "sec_company_tickers.json").read_bytes()

    def handler(request: httpx2.Request) -> httpx2.Response:
        url = str(request.url)
        if "company_tickers.json" in url:
            return httpx2.Response(200, content=tickers_data)
        if "CIK" in url:
            return httpx2.Response(200, content=nvda_data)
        return httpx2.Response(404, content=b"{}")

    from app.ingestion.sec_edgar import SecEdgarConnector
    from app.ingestion.sec_rate_limiter import RateLimiter

    mock_limiter = MagicMock(spec=RateLimiter)
    connector = SecEdgarConnector(transport=httpx2.MockTransport(handler))
    connector._limiter = mock_limiter
    connector.fetch()

    # Rate limiter should be called once per ticker that has a valid CIK
    assert mock_limiter.wait.call_count >= 1


def test_raw_payload_contains_sec_fields(sec_transport, monkeypatch):
    monkeypatch.setattr("app.ingestion.sec_edgar.settings.sec_user_agent", "TestApp test@test.com")
    monkeypatch.setattr("app.ingestion.sec_edgar.settings.watchlist", ["NVDA"])
    from app.ingestion.sec_edgar import SecEdgarConnector
    connector = SecEdgarConnector(transport=sec_transport)
    articles = connector.fetch()
    for a in articles:
        assert "sec_form_type" in a.raw_payload
        assert "sec_items" in a.raw_payload
        assert isinstance(a.raw_payload["sec_items"], list)
        assert "event_type_hint" in a.raw_payload
