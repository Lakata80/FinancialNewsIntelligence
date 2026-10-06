from __future__ import annotations

import hashlib
import logging
from pathlib import Path

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.llm.budget import BudgetExceeded
from app.llm.client import AnthropicLlmClient
from app.llm.models import ClusterClassification, EventType
from app.llm.spotlighting import wrap_article
from app.models.news import Article, ClusterMember, StoryCluster

logger = logging.getLogger(__name__)

_PROMPT_PATH = Path(__file__).parent / "prompts" / "classify_v1.md"
_PROMPT_TEXT = _PROMPT_PATH.read_text(encoding="utf-8")
CLASSIFY_PROMPT_VERSION = (
    "classify_v1:" + hashlib.sha256(_PROMPT_TEXT.encode()).hexdigest()[:8]
)


def classify_cluster(
    cluster: StoryCluster,
    client: AnthropicLlmClient,
    session: Session,
) -> ClusterClassification | None:
    """Classify a cluster using the LLM.

    Returns None (non-fatal) on BudgetExceeded or pydantic validation failure.
    On success, writes classification columns to cluster and commits the session.
    Only active articles are passed to the LLM (CLAUDE.md Rule e / ADR-009).
    """
    active_articles = session.scalars(
        select(Article)
        .join(ClusterMember, ClusterMember.article_id == Article.id)
        .where(ClusterMember.cluster_id == cluster.id)
        .where(Article.status == "active")
    ).all()

    if not active_articles:
        logger.warning("cluster %d has no active articles — skipping", cluster.id)
        return None

    article_blocks = "\n\n".join(
        wrap_article(a.id, a.clean_text or a.summary_raw or a.title)
        for a in active_articles
    )
    user_msg = (
        f"Classify cluster {cluster.id} (primary ticker: {cluster.primary_ticker or 'N/A'}).\n\n"
        f"{article_blocks}"
    )

    try:
        raw = client.call(
            system=_PROMPT_TEXT,
            user=user_msg,
            purpose="classify",
            prompt_version=CLASSIFY_PROMPT_VERSION,
        )
    except BudgetExceeded:
        logger.info("budget exceeded — skipping cluster %d", cluster.id)
        session.commit()
        return None
    except ValueError as exc:
        logger.warning("classify cluster %d: JSON validation failed: %s", cluster.id, exc)
        session.commit()
        return None

    try:
        result = ClusterClassification.model_validate_json(raw)
    except ValidationError as exc:
        logger.warning("classify cluster %d: schema validation failed: %s", cluster.id, exc)
        session.commit()
        return None

    if result.cluster_id != cluster.id:
        logger.warning(
            "classify cluster %d: response cluster_id mismatch (%d) — rejected",
            cluster.id,
            result.cluster_id,
        )
        session.commit()
        return None

    cluster.event_type = result.event_type.value
    cluster.is_main_subject = result.is_main_subject
    cluster.is_opinion = result.is_opinion
    cluster.relevance_score = result.relevance_score
    cluster.classification_model = client._model
    cluster.classification_prompt_version = CLASSIFY_PROMPT_VERSION

    cluster.visible = not (
        result.event_type == EventType.promotional
        or not result.is_main_subject
    )

    session.commit()
    return result
