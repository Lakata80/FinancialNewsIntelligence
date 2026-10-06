from __future__ import annotations

import hashlib
import logging
from pathlib import Path

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.llm.budget import BudgetExceeded
from app.llm.client import AnthropicLlmClient
from app.llm.models import DedupCheckResult
from app.llm.spotlighting import wrap_article
from app.models.news import Article, ClusterMember, StoryCluster

logger = logging.getLogger(__name__)

_PROMPT_PATH = Path(__file__).parent / "prompts" / "dedup_check_v1.md"
_PROMPT_TEXT = _PROMPT_PATH.read_text(encoding="utf-8")
DEDUP_PROMPT_VERSION = (
    "dedup_check_v1:" + hashlib.sha256(_PROMPT_TEXT.encode()).hexdigest()[:8]
)


def _get_active_articles(
    cluster: StoryCluster, session: Session
) -> list[Article]:
    return list(
        session.scalars(
            select(Article)
            .join(ClusterMember, ClusterMember.article_id == Article.id)
            .where(ClusterMember.cluster_id == cluster.id)
            .where(Article.status == "active")
        ).all()
    )


def check_same_event(
    cluster_a: StoryCluster,
    cluster_b: StoryCluster,
    client: AnthropicLlmClient,
    threshold: float,
    session: Session,
) -> bool:
    """Ask the LLM whether two clusters represent the same real-world event.

    Returns True only when same_event=True AND confidence >= threshold.
    Returns False (non-fatal) on BudgetExceeded or validation failure.
    On a True result the caller is responsible for merging the clusters.
    """
    articles_a = _get_active_articles(cluster_a, session)
    articles_b = _get_active_articles(cluster_b, session)

    if not articles_a or not articles_b:
        return False

    block_a = "\n\n".join(
        wrap_article(a.id, a.clean_text or a.summary_raw or a.title)
        for a in articles_a
    )
    block_b = "\n\n".join(
        wrap_article(a.id, a.clean_text or a.summary_raw or a.title)
        for a in articles_b
    )

    user_msg = (
        f"Cluster A (id={cluster_a.id}, ticker={cluster_a.primary_ticker or 'N/A'}):\n\n"
        f"{block_a}\n\n"
        f"---\n\n"
        f"Cluster B (id={cluster_b.id}, ticker={cluster_b.primary_ticker or 'N/A'}):\n\n"
        f"{block_b}"
    )

    try:
        raw = client.call(
            system=_PROMPT_TEXT,
            user=user_msg,
            purpose="dedup_check",
            prompt_version=DEDUP_PROMPT_VERSION,
        )
    except BudgetExceeded:
        logger.info(
            "budget exceeded — skipping dedup check for clusters %d/%d",
            cluster_a.id,
            cluster_b.id,
        )
        session.commit()
        return False
    except ValueError as exc:
        logger.warning(
            "dedup check clusters %d/%d: JSON error: %s",
            cluster_a.id,
            cluster_b.id,
            exc,
        )
        session.commit()
        return False

    try:
        result = DedupCheckResult.model_validate_json(raw)
    except ValidationError as exc:
        logger.warning(
            "dedup check clusters %d/%d: schema validation failed: %s",
            cluster_a.id,
            cluster_b.id,
            exc,
        )
        session.commit()
        return False

    session.commit()
    return result.same_event and result.confidence >= threshold
