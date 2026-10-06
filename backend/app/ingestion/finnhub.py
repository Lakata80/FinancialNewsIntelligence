from __future__ import annotations

import logging
import time
from datetime import UTC, datetime, timedelta

import httpx2

from app.core.config import settings
from app.ingestion.base import RawArticle, SourceConnector

logger = logging.getLogger(__name__)

_BASE = "https://finnhub.io/api/v1"
_LOOKBACK_DAYS = 3
_MIN_INTERVAL_SEC = 1.3  # 60/50 req/min + safety margin


class FinnhubCompanyNews(SourceConnector):
    source_name = "finnhub"
    source_kind = "api"

    def __init__(self, transport: httpx2.BaseTransport | None = None) -> None:
        self._transport = transport

    def fetch(self) -> list[RawArticle]:
        if not settings.finnhub_api_key:
            logger.warning("Finnhub API key not set; skipping connector")
            return []
        transport = self._transport or httpx2.HTTPTransport(retries=2)
        with httpx2.Client(
            transport=transport,
            timeout=15.0,
            headers={"User-Agent": settings.user_agent},
        ) as client:
            return self._fetch_all(client)

    def _fetch_all(self, client: httpx2.Client) -> list[RawArticle]:
        articles: list[RawArticle] = []
        now = datetime.now(UTC)
        from_date = (now - timedelta(days=_LOOKBACK_DAYS)).strftime("%Y-%m-%d")
        to_date = now.strftime("%Y-%m-%d")

        for ticker in settings.watchlist:
            try:
                articles.extend(self._company_news(client, ticker, from_date, to_date))
            except Exception as exc:
                logger.warning("Finnhub company news failed for %s: %s", ticker, exc)
            if self._transport is None:
                time.sleep(_MIN_INTERVAL_SEC)

        try:
            articles.extend(self._general_news(client))
        except Exception as exc:
            logger.warning("Finnhub general news failed: %s", exc)

        return articles

    def _company_news(
        self, client: httpx2.Client, ticker: str, from_date: str, to_date: str
    ) -> list[RawArticle]:
        r = client.get(
            f"{_BASE}/company-news",
            params={
                "symbol": ticker,
                "from": from_date,
                "to": to_date,
                "token": settings.finnhub_api_key,
            },
        )
        r.raise_for_status()
        return [self._item_to_raw(item, tickers=[ticker]) for item in r.json()]

    def _general_news(self, client: httpx2.Client) -> list[RawArticle]:
        r = client.get(
            f"{_BASE}/news",
            params={"category": "general", "token": settings.finnhub_api_key},
        )
        r.raise_for_status()
        return [self._item_to_raw(item, tickers=[]) for item in r.json()]

    def _item_to_raw(self, item: dict, tickers: list[str]) -> RawArticle:
        ts = item.get("datetime", 0) or 0
        if ts:
            pub_dt = datetime.fromtimestamp(ts, tz=UTC).replace(tzinfo=None)
        else:
            pub_dt = datetime.utcnow()
        related = item.get("related") or ""
        extra_tickers = (
            [t.strip() for t in related.split(",") if t.strip()] if related else []
        )
        return RawArticle(
            source_name=self.source_name,
            title=str(item.get("headline") or "").strip(),
            url=str(item.get("url") or "").strip(),
            published_at=pub_dt,
            summary_raw=str(item.get("summary") or "").strip() or None,
            publisher=str(item.get("source") or "").strip() or None,
            tickers_raw=list(dict.fromkeys(tickers + extra_tickers)),
            raw_payload=item,
        )
