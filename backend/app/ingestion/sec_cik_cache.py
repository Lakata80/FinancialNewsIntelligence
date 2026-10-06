from __future__ import annotations

import json
import logging
import time
from pathlib import Path

import httpx2

logger = logging.getLogger(__name__)

_CIK_URL = "https://www.sec.gov/files/company_tickers.json"
_DEFAULT_CACHE = Path(__file__).parent.parent.parent / ".sec_cik_cache.json"


class CikCache:
    """Ticker → zero-padded 10-digit CIK, backed by a local JSON file with TTL."""

    def __init__(
        self,
        cache_path: Path = _DEFAULT_CACHE,
        ttl_hours: int = 24,
        transport: httpx2.BaseTransport | None = None,
    ) -> None:
        self._cache_path = cache_path
        self._ttl_seconds = ttl_hours * 3600
        self._transport = transport
        self._data: dict[str, str] | None = None

    def get_cik(self, ticker: str) -> str | None:
        data = self._ensure_loaded()
        return data.get(ticker.upper())

    def _ensure_loaded(self) -> dict[str, str]:
        if self._data is not None:
            return self._data
        if self._cache_path.exists():
            age = time.time() - self._cache_path.stat().st_mtime
            if age < self._ttl_seconds:
                try:
                    self._data = json.loads(self._cache_path.read_text(encoding="utf-8"))
                    return self._data
                except (json.JSONDecodeError, OSError):
                    logger.warning("CIK cache corrupt; re-fetching")
        self._data = self._fetch_and_save()
        return self._data

    def _fetch_and_save(self) -> dict[str, str]:
        from app.core.config import settings

        headers = {"User-Agent": settings.sec_user_agent or "FinancialNewsIntelligence/1.0"}
        transport = self._transport or httpx2.HTTPTransport(retries=2)
        try:
            with httpx2.Client(transport=transport, headers=headers, timeout=30) as client:
                resp = client.get(_CIK_URL)
                resp.raise_for_status()
                raw: dict = resp.json()
        except Exception:
            logger.exception("Failed to fetch company_tickers.json from SEC")
            return {}

        # SEC format: {"0": {"cik_str": 320193, "ticker": "AAPL", "title": "Apple Inc."}, ...}
        mapping: dict[str, str] = {}
        for entry in raw.values():
            ticker = str(entry.get("ticker", "")).upper()
            cik = str(entry.get("cik_str", "")).zfill(10)
            if ticker:
                mapping[ticker] = cik

        try:
            self._cache_path.write_text(
                json.dumps(mapping, ensure_ascii=False), encoding="utf-8"
            )
        except OSError:
            logger.warning("Could not write CIK cache to %s", self._cache_path)

        return mapping
