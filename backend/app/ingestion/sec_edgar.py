from __future__ import annotations

import logging
from datetime import UTC, datetime
from pathlib import Path

import httpx2

from app.core.config import settings
from app.ingestion.base import RawArticle, SourceConnector
from app.ingestion.sec_cik_cache import CikCache
from app.ingestion.sec_rate_limiter import RateLimiter

logger = logging.getLogger(__name__)

_SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik}.json"
_FILING_URL = "https://www.sec.gov/Archives/edgar/data/{cik}/{accession}/{doc}"

_ITEM_EVENT_MAP: list[tuple[str, str]] = [
    ("2.02", "earnings"),
    ("5.02", "executive_change"),
    ("1.01", "merger_acquisition"),
    ("2.01", "merger_acquisition"),
    ("1.03", "regulatory"),
]

_ITEM_DESCRIPTIONS: dict[str, str] = {
    "2.02": "Results of Operations",
    "5.02": "Changes in Directors or Officers",
    "1.01": "Entry into a Material Definitive Agreement",
    "2.01": "Completion of Acquisition or Disposition",
    "1.03": "Bankruptcy or Receivership",
    "7.01": "Regulation FD Disclosure",
    "8.01": "Other Events",
    "9.01": "Financial Statements and Exhibits",
}


class SecEdgarConnector(SourceConnector):
    source_name = "sec_edgar"
    source_kind = "primary"

    def __init__(self, transport: httpx2.BaseTransport | None = None) -> None:
        if not settings.sec_user_agent:
            raise RuntimeError(
                "SEC_USER_AGENT is not configured. "
                "Set SEC_USER_AGENT in .env (e.g. 'CompanyName your@email.com')."
            )
        self._transport = transport
        self._limiter = RateLimiter(max_per_second=5.0)
        self._cik_cache = CikCache(transport=transport)

    def fetch(self) -> list[RawArticle]:
        from app.core.config import settings as cfg

        form_types: list[str] = _load_config_form_types()
        max_filings: int = _load_config_max_filings()

        headers = {"User-Agent": settings.sec_user_agent}
        transport = self._transport or httpx2.HTTPTransport(retries=2)

        articles: list[RawArticle] = []
        with httpx2.Client(transport=transport, headers=headers, timeout=30) as client:
            for ticker in cfg.watchlist:
                try:
                    results = self._fetch_ticker(client, ticker, form_types, max_filings)
                    articles.extend(results)
                except Exception:
                    logger.exception("SEC EDGAR fetch failed for ticker %s", ticker)
        return articles

    def _fetch_ticker(
        self,
        client: httpx2.Client,
        ticker: str,
        form_types: list[str],
        max_filings: int,
    ) -> list[RawArticle]:
        cik = self._cik_cache.get_cik(ticker)
        if cik is None:
            logger.warning("No CIK found for ticker %s; skipping", ticker)
            return []

        self._limiter.wait()
        url = _SUBMISSIONS_URL.format(cik=cik)
        try:
            resp = client.get(url)
            resp.raise_for_status()
        except httpx2.HTTPStatusError as exc:
            logger.warning("SEC submissions API returned %s for %s", exc.response.status_code, ticker)
            return []

        data = resp.json()
        recent = data.get("filings", {}).get("recent", {})

        forms: list[str] = recent.get("form", [])
        dates: list[str] = recent.get("filingDate", [])
        accessions: list[str] = recent.get("accessionNumber", [])
        docs: list[str] = recent.get("primaryDocument", [])
        items_list: list[str] = recent.get("items", [])

        articles: list[RawArticle] = []
        seen = 0
        for i, form in enumerate(forms):
            if form not in form_types:
                continue
            if seen >= max_filings:
                break
            seen += 1

            filing_date_str = dates[i] if i < len(dates) else ""
            accession = accessions[i] if i < len(accessions) else ""
            primary_doc = docs[i] if i < len(docs) else ""
            items_str = items_list[i] if i < len(items_list) else ""

            published_at = _parse_date(filing_date_str)
            if published_at is None:
                continue

            event_type = self._items_to_event_type(form, items_str)
            title = _build_title(ticker, form, items_str)
            accession_nodash = accession.replace("-", "")
            filing_url = _FILING_URL.format(cik=cik.lstrip("0"), accession=accession_nodash, doc=primary_doc)

            articles.append(
                RawArticle(
                    source_name=self.source_name,
                    title=title,
                    url=filing_url,
                    published_at=published_at,
                    summary_raw=None,
                    publisher="SEC EDGAR",
                    tickers_raw=[ticker],
                    raw_payload={
                        "cik": cik,
                        "accession_number": accession,
                        "form": form,
                        "filing_date": filing_date_str,
                        "items": items_str,
                        "primary_document": primary_doc,
                        "sec_form_type": form,
                        "sec_items": [s.strip() for s in items_str.split(",") if s.strip()],
                        "event_type_hint": event_type,
                    },
                )
            )
        return articles

    def _items_to_event_type(self, form: str, items_str: str) -> str:
        if form in ("10-Q", "10-K"):
            return "earnings"
        if form == "6-K":
            return "other"
        # 8-K: check item numbers
        for item_code, event_type in _ITEM_EVENT_MAP:
            if item_code in items_str:
                return event_type
        return "other"


def _parse_date(date_str: str) -> datetime | None:
    try:
        return datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=None)
    except (ValueError, TypeError):
        return None


def _build_title(ticker: str, form: str, items_str: str) -> str:
    if form == "10-Q":
        return f"10-Q {ticker} — Quarterly Report"
    if form == "10-K":
        return f"10-K {ticker} — Annual Report"
    if form == "6-K":
        return f"6-K {ticker} — Report of Foreign Private Issuer"
    # 8-K: use first known item description
    for item_code in [s.strip() for s in items_str.split(",") if s.strip()]:
        if item_code in _ITEM_DESCRIPTIONS:
            return f"8-K {ticker} — {_ITEM_DESCRIPTIONS[item_code]}"
    return f"8-K {ticker} — Current Report"


def _load_config_form_types() -> list[str]:
    try:
        import yaml
        cfg_path = Path(__file__).parent.parent.parent.parent / "config.yaml"
        with open(cfg_path, encoding="utf-8") as f:
            cfg = yaml.safe_load(f)
        return cfg.get("sec_edgar", {}).get("form_types", ["8-K", "10-Q", "10-K", "6-K"])
    except Exception:
        return ["8-K", "10-Q", "10-K", "6-K"]


def _load_config_max_filings() -> int:
    try:
        import yaml
        cfg_path = Path(__file__).parent.parent.parent.parent / "config.yaml"
        with open(cfg_path, encoding="utf-8") as f:
            cfg = yaml.safe_load(f)
        return int(cfg.get("sec_edgar", {}).get("max_filings_per_ticker", 10))
    except Exception:
        return 10
