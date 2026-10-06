from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timezone
from pathlib import Path

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.llm.budget import BudgetExceeded
from app.llm.client import AnthropicLlmClient
from app.llm.models import AttributedOpinion, EvidenceItem, KeyFact, SummarizationOutput
from app.llm.spotlighting import wrap_article_full
from app.models.news import Article, ClusterMember, FactEvidence, Story, StoryCluster, StoryFact

logger = logging.getLogger(__name__)

_PROMPT_PATH = Path(__file__).parent / "prompts" / "summarize_v1.md"
_PROMPT_TEXT = _PROMPT_PATH.read_text(encoding="utf-8")
SUMMARIZE_PROMPT_VERSION = (
    "summarize_v1:" + hashlib.sha256(_PROMPT_TEXT.encode()).hexdigest()[:8]
)


def _collect_evidence(
    facts: list[KeyFact], opinions: list[AttributedOpinion]
) -> list[EvidenceItem]:
    """Flatten all evidence items from facts and opinions into a single list."""
    items: list[EvidenceItem] = []
    for fact in facts:
        items.extend(fact.evidence)
    for opinion in opinions:
        items.extend(opinion.evidence)
    return items


def _verify_quotes(
    evidence_items: list[EvidenceItem],
    article_by_id: dict[int, Article],
    cluster_id: int,
) -> bool:
    """Return False if any quote is not found verbatim in the article's text (Rule c)."""
    for ev in evidence_items:
        article = article_by_id[ev.article_id]
        haystack = article.clean_text or article.summary_raw or article.title or ""
        if haystack.find(ev.quote_en) == -1:
            logger.warning(
                "cluster %d: quote not found in article %d: %r",
                cluster_id,
                ev.article_id,
                ev.quote_en[:60],
            )
            return False
    return True


def summarize_cluster(
    cluster: StoryCluster,
    client: AnthropicLlmClient,
    session: Session,
    max_articles: int = 10,
) -> Story | None:
    """Summarise a cluster and persist the result as a Story with facts and evidence.

    Returns the existing Story if one already exists for the cluster.
    Returns None (non-fatal) on BudgetExceeded, JSON error, schema validation failure,
    or any structural check failure (unknown article_id, cluster_id mismatch, missing quote).
    """
    existing = session.scalar(select(Story).where(Story.cluster_id == cluster.id))
    if existing is not None:
        logger.info("cluster %d already has story %d — skipping", cluster.id, existing.id)
        return existing

    articles = session.scalars(
        select(Article)
        .join(ClusterMember, ClusterMember.article_id == Article.id)
        .where(ClusterMember.cluster_id == cluster.id)
        .where(Article.status != "quarantined")
        .order_by(Article.published_at.desc())
        .limit(max_articles)
    ).all()

    if not articles:
        logger.warning("cluster %d has no eligible articles — skipping", cluster.id)
        return None

    article_ids = {a.id for a in articles}
    article_by_id = {a.id: a for a in articles}

    article_blocks = "\n\n".join(
        wrap_article_full(
            a.id,
            a.clean_text or a.summary_raw or a.title or "",
            a.publisher,
            a.published_at,
        )
        for a in articles
    )
    user_msg = (
        f"Summarise cluster {cluster.id} "
        f"(primary ticker: {cluster.primary_ticker or 'N/A'}).\n\n"
        f"{article_blocks}"
    )

    try:
        raw = client.call(
            system=_PROMPT_TEXT,
            user=user_msg,
            purpose="summarize",
            prompt_version=SUMMARIZE_PROMPT_VERSION,
            max_tokens=4096,
        )
    except BudgetExceeded:
        logger.info("budget exceeded — skipping cluster %d summarization", cluster.id)
        session.commit()
        return None
    except ValueError as exc:
        logger.warning("summarize cluster %d: JSON error: %s", cluster.id, exc)
        session.commit()
        return None

    try:
        output = SummarizationOutput.model_validate_json(raw)
    except ValidationError as exc:
        logger.warning("summarize cluster %d: schema validation failed: %s", cluster.id, exc)
        session.commit()
        return None

    if output.cluster_id != cluster.id:
        logger.warning(
            "summarize cluster %d: response cluster_id mismatch (%d) — rejected",
            cluster.id,
            output.cluster_id,
        )
        session.commit()
        return None

    all_evidence = _collect_evidence(output.key_facts, output.attributed_opinions)

    unknown_ids = {ev.article_id for ev in all_evidence} - article_ids
    if unknown_ids:
        logger.warning(
            "summarize cluster %d: unknown article_ids in evidence: %s — rejected",
            cluster.id,
            unknown_ids,
        )
        session.commit()
        return None

    if not _verify_quotes(all_evidence, article_by_id, cluster.id):
        logger.warning(
            "summarize cluster %d: quote verification failed — rejected", cluster.id
        )
        session.commit()
        return None

    story = Story(
        cluster_id=cluster.id,
        title_bg=output.title_bg,
        summary_bg=output.summary_bg,
        tickers=[cluster.primary_ticker] if cluster.primary_ticker else [],
        event_type=cluster.event_type,
        is_opinion=cluster.is_opinion or False,
        verification_status="pending",
        model_version=client._model,
        prompt_version=SUMMARIZE_PROMPT_VERSION,
        created_at=datetime.now(timezone.utc).replace(tzinfo=None),
    )
    session.add(story)
    session.flush()

    for order, fact in enumerate(output.key_facts):
        sf = StoryFact(story_id=story.id, fact_order=order, text_bg=fact.text_bg)
        session.add(sf)
        session.flush()

        for ev in fact.evidence:
            article = article_by_id[ev.article_id]
            haystack = article.clean_text or article.summary_raw or article.title or ""
            pos = haystack.find(ev.quote_en)
            session.add(
                FactEvidence(
                    fact_id=sf.id,
                    article_id=ev.article_id,
                    quote_en=ev.quote_en,
                    quote_start=pos,
                    quote_end=pos + len(ev.quote_en),
                )
            )

    session.commit()
    return story
