from __future__ import annotations

import logging
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime

import defusedxml.ElementTree as ET
import httpx2

from app.core.config import settings
from app.ingestion.base import RawArticle, SourceConnector

logger = logging.getLogger(__name__)

_RSS_URL = "https://feeds.finance.yahoo.com/rss/2.0/headline?s={ticker}&region=US&lang=en-US"


class YahooTickerRSS(SourceConnector):
    source_name = "yahoo_rss"
    source_kind = "rss"

    def __init__(self, transport: httpx2.BaseTransport | None = None) -> None:
        self._transport = transport

    def fetch(self) -> list[RawArticle]:
        articles: list[RawArticle] = []
        transport = self._transport or httpx2.HTTPTransport(retries=3)
        with httpx2.Client(
            transport=transport,
            timeout=10.0,
            headers={"User-Agent": settings.user_agent},
        ) as client:
            for ticker in settings.watchlist:
                try:
                    articles.extend(self._fetch_ticker(client, ticker))
                except Exception as exc:
                    logger.warning("Yahoo RSS fetch failed for %s: %s", ticker, exc)
        return articles

    def _fetch_ticker(self, client: httpx2.Client, ticker: str) -> list[RawArticle]:
        url = _RSS_URL.format(ticker=ticker)
        response = client.get(url)
        response.raise_for_status()
        return self._parse(response.content, ticker)

    def _parse(self, content: bytes, ticker: str) -> list[RawArticle]:
        root = ET.fromstring(content)
        results: list[RawArticle] = []
        for item in root.findall(".//item"):
            title = (item.findtext("title") or "").strip()
            link = (item.findtext("link") or "").strip()
            if not title or not link:
                continue
            pub_date_str = item.findtext("pubDate") or ""
            try:
                pub_dt = (
                    parsedate_to_datetime(pub_date_str).astimezone(UTC).replace(tzinfo=None)
                )
            except Exception:
                pub_dt = datetime.utcnow()
            results.append(RawArticle(
                source_name=self.source_name,
                title=title,
                url=link,
                published_at=pub_dt,
                summary_raw=item.findtext("description") or None,
                publisher="Yahoo Finance",
                tickers_raw=[ticker],
                raw_payload={"ticker": ticker, "pub_date_raw": pub_date_str},
            ))
        return results
