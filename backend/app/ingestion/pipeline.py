from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from app.core.db import SessionLocal
from app.ingestion.base import RawArticle, SourceConnector
from app.ingestion.canonical import canonicalize_url
from app.models.news import Article, FetchRun, Source
from app.sanitization.injection_scan import quarantine_threshold, scan_article
from app.sanitization.sanitizer import sanitize_html

_STALE_HOURS = 48
logger = logging.getLogger(__name__)


@dataclass
class RunResult:
    source_name: str
    items_seen: int
    items_new: int
    newest_article_title: str | None
    newest_at: datetime | None
    status: str  # "ok" | "error" | "stale"
    error: str | None = None


def _get_or_create_source(session: Session, connector: SourceConnector) -> Source:
    source = session.query(Source).filter_by(name=connector.source_name).first()
    if source is None:
        source = Source(
            name=connector.source_name,
            kind=connector.source_kind,
            enabled=True,
        )
        session.add(source)
        session.flush()
    return source


def _content_hash(title: str, summary: str | None) -> str:
    raw = f"{title}|{summary or ''}"
    return hashlib.sha256(raw.encode()).hexdigest()


def _persist_articles(
    session: Session,
    source: Source,
    articles: list[RawArticle],
    fetched_at: datetime,
) -> tuple[int, int, datetime | None]:
    """Returns (items_seen, items_new, newest_published_at)."""
    seen = len(articles)
    new_count = 0
    newest: datetime | None = None

    _threshold = quarantine_threshold()

    for raw in articles:
        if not raw.title or not raw.url:
            continue
        canonical = canonicalize_url(raw.url)
        clean = sanitize_html(raw.summary_raw or "")
        # Scan RAW text (including HTML) so hidden elements and alt attributes
        # are visible to the injection detector.
        scan_text = raw.title + " " + (raw.summary_raw or "")
        result = scan_article(scan_text)
        article_status = (
            "quarantined" if result.injection_score >= _threshold else "active"
        )
        stmt = (
            sqlite_insert(Article)
            .values(
                source_id=source.id,
                publisher=raw.publisher,
                title=raw.title,
                summary_raw=raw.summary_raw,
                url=raw.url,
                canonical_url=canonical,
                published_at=raw.published_at,
                fetched_at=fetched_at,
                tickers_raw=raw.tickers_raw,
                content_hash=_content_hash(raw.title, raw.summary_raw),
                raw_payload=raw.raw_payload,
                clean_text=clean,
                injection_score=result.injection_score,
                matched_rules=result.matched_rules,
                status=article_status,
                sec_form_type=raw.raw_payload.get("sec_form_type"),
                sec_items=raw.raw_payload.get("sec_items"),
            )
            .on_conflict_do_nothing(index_elements=["canonical_url"])
        )
        result = session.execute(stmt)
        if result.rowcount == 1:
            new_count += 1
        if newest is None or raw.published_at > newest:
            newest = raw.published_at

    return seen, new_count, newest


def run_connector(
    connector: SourceConnector,
    session_factory=None,
) -> RunResult:
    """Run one connector, persist results, record FetchRun. Never raises."""
    sf = session_factory or SessionLocal
    started_at = datetime.now(UTC).replace(tzinfo=None)

    with sf() as session:
        source = _get_or_create_source(session, connector)
        fetch_run = FetchRun(
            source_id=source.id,
            started_at=started_at,
            status="running",
        )
        session.add(fetch_run)
        session.commit()

        try:
            articles = connector.fetch()
            seen, new_count, newest_at = _persist_articles(
                session, source, articles, started_at
            )
            session.commit()

            status = "ok"
            if newest_at is not None:
                age = started_at - newest_at
                if age > timedelta(hours=_STALE_HOURS):
                    status = "stale"

            finished_at = datetime.now(UTC).replace(tzinfo=None)
            fetch_run.finished_at = finished_at
            fetch_run.status = status
            fetch_run.items_seen = seen
            fetch_run.items_new = new_count
            fetch_run.newest_item_at = newest_at
            session.commit()

            newest_title: str | None = None
            if newest_at and articles:
                candidates = [a for a in articles if a.published_at == newest_at]
                newest_title = candidates[0].title if candidates else None

            return RunResult(
                source_name=connector.source_name,
                items_seen=seen,
                items_new=new_count,
                newest_article_title=newest_title,
                newest_at=newest_at,
                status=status,
            )

        except Exception as exc:
            logger.exception("Connector %s failed", connector.source_name)
            finished_at = datetime.now(UTC).replace(tzinfo=None)
            fetch_run.finished_at = finished_at
            fetch_run.status = "error"
            fetch_run.error = str(exc)[:1000]
            session.commit()
            return RunResult(
                source_name=connector.source_name,
                items_seen=0,
                items_new=0,
                newest_article_title=None,
                newest_at=None,
                status="error",
                error=str(exc),
            )


def run_all_connectors(
    connectors: list[SourceConnector],
    session_factory=None,
) -> list[RunResult]:
    """Run all connectors sequentially. One failure never stops the others."""
    return [run_connector(c, session_factory=session_factory) for c in connectors]
