from __future__ import annotations

import logging
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime

import defusedxml.ElementTree as ET
import httpx2

from app.core.config import settings
from app.ingestion.base import RawArticle, SourceConnector

logger = logging.getLogger(__name__)

_FED_RSS_URL = "https://www.federalreserve.gov/feeds/press_all.xml"


class FedPressRSS(SourceConnector):
    source_name = "fed_rss"
    source_kind = "rss"

    def __init__(self, transport: httpx2.BaseTransport | None = None) -> None:
        self._transport = transport

    def fetch(self) -> list[RawArticle]:
        try:
            transport = self._transport or httpx2.HTTPTransport(retries=3)
            with httpx2.Client(
                transport=transport,
                timeout=15.0,
                headers={"User-Agent": settings.user_agent},
            ) as client:
                r = client.get(_FED_RSS_URL)
                r.raise_for_status()
                return self._parse(r.content)
        except Exception as exc:
            logger.warning("Fed RSS fetch failed: %s", exc)
            return []

    def _parse(self, content: bytes) -> list[RawArticle]:
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
                publisher="Federal Reserve",
                tickers_raw=[],
                raw_payload={"pub_date_raw": pub_date_str},
            ))
        return results
