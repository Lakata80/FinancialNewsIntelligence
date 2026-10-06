from __future__ import annotations

import json
import time
from pathlib import Path

import httpx2
import pytest

from app.ingestion.sec_cik_cache import CikCache

FIXTURES = Path(__file__).parent / "fixtures" / "sources"


def _make_transport(status: int = 200, payload: bytes | None = None):
    content = payload or (FIXTURES / "sec_company_tickers.json").read_bytes()

    def handler(request: httpx2.Request) -> httpx2.Response:
        assert "User-Agent" in request.headers
        return httpx2.Response(status, content=content)

    return httpx2.MockTransport(handler)


def test_get_cik_known_ticker(tmp_path):
    cache = CikCache(cache_path=tmp_path / "cache.json", transport=_make_transport())
    assert cache.get_cik("NVDA") == "0001045810"


def test_get_cik_unknown_ticker(tmp_path):
    cache = CikCache(cache_path=tmp_path / "cache.json", transport=_make_transport())
    assert cache.get_cik("UNKNOWN") is None


def test_get_cik_case_insensitive(tmp_path):
    cache = CikCache(cache_path=tmp_path / "cache.json", transport=_make_transport())
    assert cache.get_cik("aapl") == cache.get_cik("AAPL")


def test_cik_padded_to_10_digits(tmp_path):
    cache = CikCache(cache_path=tmp_path / "cache.json", transport=_make_transport())
    cik = cache.get_cik("AAPL")
    assert cik is not None
    assert len(cik) == 10
    assert cik == "0000320193"


def test_cache_written_to_disk(tmp_path):
    cache_file = tmp_path / "cache.json"
    cache = CikCache(cache_path=cache_file, transport=_make_transport())
    cache.get_cik("NVDA")
    assert cache_file.exists()
    data = json.loads(cache_file.read_text())
    assert data["NVDA"] == "0001045810"


def test_fresh_cache_not_refetched(tmp_path, monkeypatch):
    cache_file = tmp_path / "cache.json"
    cache_file.write_text(json.dumps({"NVDA": "0001045810"}), encoding="utf-8")

    fetch_count = 0

    def counting_transport():
        def handler(request: httpx2.Request) -> httpx2.Response:
            nonlocal fetch_count
            fetch_count += 1
            return httpx2.Response(200, content=b"{}")

        return httpx2.MockTransport(handler)

    cache = CikCache(cache_path=cache_file, ttl_hours=24, transport=counting_transport())
    assert cache.get_cik("NVDA") == "0001045810"
    assert fetch_count == 0


def test_expired_cache_refetched(tmp_path):
    cache_file = tmp_path / "cache.json"
    cache_file.write_text(json.dumps({"NVDA": "OLD"}), encoding="utf-8")
    # backdate mtime so cache appears expired
    old_mtime = time.time() - 25 * 3600
    import os
    os.utime(cache_file, (old_mtime, old_mtime))

    cache = CikCache(cache_path=cache_file, ttl_hours=24, transport=_make_transport())
    assert cache.get_cik("NVDA") == "0001045810"


def test_fetch_failure_returns_empty(tmp_path, monkeypatch):
    def bad_handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(503, content=b"Service Unavailable")

    cache = CikCache(
        cache_path=tmp_path / "cache.json",
        transport=httpx2.MockTransport(bad_handler),
    )
    assert cache.get_cik("NVDA") is None
