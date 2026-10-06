from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.llm.budget import BudgetExceeded
from app.llm.models import SecCorroborationResult
from app.llm.spotlighting import wrap_article
from app.models.news import Article, ClusterMember, Source, StoryCluster

logger = logging.getLogger(__name__)

_PROMPT_PATH = Path(__file__).parent.parent / "llm" / "prompts" / "sec_corroborate_v1.md"
_PROMPT_TEXT = _PROMPT_PATH.read_text(encoding="utf-8")
SEC_CORR_PROMPT_VERSION = (
    "sec_corroborate_v1:" + hashlib.sha256(_PROMPT_TEXT.encode()).hexdigest()[:8]
)

# Event types that are compatible for corroboration: SEC hint → media event_types
_COMPAT_EVENT_TYPES: dict[str, set[str]] = {
    "earnings": {"earnings"},
    "executive_change": {"executive_change"},
    "merger_acquisition": {"merger_acquisition"},
    "regulatory": {"regulatory", "legal"},
    "other": set(),  # "other" requires LLM check; no deterministic match
}


@dataclass
class CorroborationResult:
    new_corroborations: int = 0
    standalone_sec: int = 0
    llm_checks: int = 0
    llm_matches: int = 0
    budget_skips: int = 0
    errors: list[str] = field(default_factory=list)


def run_sec_corroboration(
    session: Session,
    window_hours: int = 48,
    confidence_threshold: float = 0.7,
    llm_client=None,
) -> CorroborationResult:
    """Match new SEC filings against existing media clusters or create standalone clusters.

    Idempotent: re-running will not create duplicate ClusterMember rows.
    """
    result = CorroborationResult()

    sec_articles = _get_unmatched_sec_articles(session)
    if not sec_articles:
        return result

    for sec_article in sec_articles:
        try:
            _process_sec_article(
                session, sec_article, window_hours, confidence_threshold, llm_client, result
            )
            session.commit()
        except Exception as exc:
            logger.exception("Error processing SEC article id=%d", sec_article.id)
            result.errors.append(str(exc))
            session.rollback()

    return result


def _get_unmatched_sec_articles(session: Session) -> list[Article]:
    """Active SEC articles not yet attached to any cluster via sec_corroboration."""
    sec_source_ids = session.scalars(
        select(Source.id).where(Source.kind == "primary")
    ).all()
    if not sec_source_ids:
        return []

    already_matched = select(ClusterMember.article_id).where(
        ClusterMember.match_method == "sec_corroboration"
    )
    return list(
        session.scalars(
            select(Article)
            .where(Article.source_id.in_(sec_source_ids))
            .where(Article.status == "active")
            .where(Article.id.not_in(already_matched))
            .order_by(Article.published_at)
        ).all()
    )


def _process_sec_article(
    session: Session,
    sec_article: Article,
    window_hours: int,
    confidence_threshold: float,
    llm_client,
    result: CorroborationResult,
) -> None:
    ticker = (
        sec_article.tickers_raw[0]
        if isinstance(sec_article.tickers_raw, list) and sec_article.tickers_raw
        else None
    )
    event_hint: str = (sec_article.raw_payload or {}).get("event_type_hint", "other")
    form_type: str = sec_article.sec_form_type or ""

    candidate_clusters = _find_candidate_clusters(session, ticker, sec_article.published_at, window_hours)

    matched_cluster: StoryCluster | None = None
    for cluster in candidate_clusters:
        cluster_event = cluster.event_type or "other"
        compatible_types = _COMPAT_EVENT_TYPES.get(event_hint, set())

        if event_hint != "other" and cluster_event in compatible_types:
            # Deterministic match
            matched_cluster = cluster
            break
        elif llm_client is not None:
            # LLM check for uncertain cases
            result.llm_checks += 1
            try:
                if _llm_matches(session, llm_client, sec_article, cluster, confidence_threshold):
                    matched_cluster = cluster
                    result.llm_matches += 1
                    break
            except BudgetExceeded:
                result.budget_skips += 1

    if matched_cluster is not None:
        _attach_to_cluster(session, sec_article, matched_cluster)
        result.new_corroborations += 1
    else:
        _create_standalone_cluster(session, sec_article, event_hint)
        result.standalone_sec += 1


def _find_candidate_clusters(
    session: Session,
    ticker: str | None,
    filing_date: datetime,
    window_hours: int,
) -> list[StoryCluster]:
    """Find media clusters for the same ticker within the time window."""
    if ticker is None:
        return []

    window_start = filing_date - timedelta(hours=window_hours)
    window_end = filing_date + timedelta(hours=window_hours)

    # Find clusters that have at least one non-SEC member (media articles)
    sec_source_ids = select(Source.id).where(Source.kind == "primary")
    media_member_cluster_ids = (
        select(ClusterMember.cluster_id)
        .join(Article, Article.id == ClusterMember.article_id)
        .where(Article.source_id.not_in(sec_source_ids))
    )

    return list(
        session.scalars(
            select(StoryCluster)
            .where(StoryCluster.primary_ticker == ticker)
            .where(StoryCluster.last_seen_at >= window_start)
            .where(StoryCluster.first_seen_at <= window_end)
            .where(StoryCluster.id.in_(media_member_cluster_ids))
            .order_by(StoryCluster.last_seen_at.desc())
        ).all()
    )


def _llm_matches(
    session: Session,
    llm_client,
    sec_article: Article,
    cluster: StoryCluster,
    threshold: float,
) -> bool:
    media_articles = list(
        session.scalars(
            select(Article)
            .join(ClusterMember, ClusterMember.article_id == Article.id)
            .where(ClusterMember.cluster_id == cluster.id)
            .where(Article.status == "active")
            .limit(5)
        ).all()
    )
    if not media_articles:
        return False

    media_block = "\n\n".join(
        wrap_article(a.id, a.clean_text or a.summary_raw or a.title)
        for a in media_articles
    )
    filing_text = sec_article.clean_text or sec_article.title
    filing_block = wrap_article(sec_article.id, filing_text)

    user_msg = (
        f"SEC Filing (form={sec_article.sec_form_type}, ticker={sec_article.tickers_raw}):\n\n"
        f"{filing_block}\n\n---\n\n"
        f"Media articles (cluster id={cluster.id}):\n\n{media_block}"
    )

    try:
        raw = llm_client.call(
            system=_PROMPT_TEXT,
            user=user_msg,
            purpose="sec_corroborate",
            prompt_version=SEC_CORR_PROMPT_VERSION,
        )
    except (ValueError, BudgetExceeded):
        raise

    try:
        corr_result = SecCorroborationResult.model_validate_json(raw)
    except ValidationError as exc:
        logger.warning("sec_corroborate schema validation failed: %s", exc)
        session.commit()
        return False

    session.commit()
    return corr_result.matches and corr_result.confidence >= threshold


def _attach_to_cluster(
    session: Session, sec_article: Article, cluster: StoryCluster
) -> None:
    session.add(
        ClusterMember(
            cluster_id=cluster.id,
            article_id=sec_article.id,
            match_method="sec_corroboration",
            similarity=1.0,
            needs_llm_check=False,
        )
    )
    cluster.has_primary_source = True
    cluster.sec_filing_url = sec_article.url
    cluster.article_count += 1


def _create_standalone_cluster(
    session: Session, sec_article: Article, event_hint: str
) -> None:
    ticker = (
        sec_article.tickers_raw[0]
        if isinstance(sec_article.tickers_raw, list) and sec_article.tickers_raw
        else None
    )
    now = datetime.now(UTC).replace(tzinfo=None)
    cluster = StoryCluster(
        primary_ticker=ticker,
        first_seen_at=sec_article.published_at,
        last_seen_at=sec_article.published_at,
        article_count=1,
        publisher_count=1,
        event_type=event_hint if event_hint != "other" else None,
        visible=True,
        has_primary_source=True,
        sec_filing_url=sec_article.url,
    )
    session.add(cluster)
    session.flush()
    session.add(
        ClusterMember(
            cluster_id=cluster.id,
            article_id=sec_article.id,
            match_method="sec_corroboration",
            similarity=1.0,
            needs_llm_check=False,
        )
    )
