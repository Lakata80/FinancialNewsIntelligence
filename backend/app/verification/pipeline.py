"""Verification pipeline orchestrator.

Runs Level 1 (deterministic) and optionally Level 2 (LLM judge) checks
on every fact of a Story, then updates verification_status on both facts
and the story itself.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.llm.budget import BudgetExceeded
from app.llm.client import AnthropicLlmClient
from app.models.news import (
    Article,
    ClusterMember,
    FactEvidence,
    Story,
    StoryFact,
    VerificationLog,
)
from app.verification.checks import (
    CheckResult,
    check_entities_grounded,
    check_no_advice,
    check_numbers_grounded,
    check_opinion_placement,
    check_quote_exists,
)
from app.verification.injection_recheck import recheck_injection
from app.verification.llm_judge import FactSupport, judge_fact

logger = logging.getLogger(__name__)


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _log(
    session: Session,
    story_id: int,
    fact_id: int | None,
    check: str,
    passed: bool,
    details: str,
) -> None:
    session.add(
        VerificationLog(
            story_id=story_id,
            fact_id=fact_id,
            check=check,
            passed=passed,
            details=details or None,
            created_at=_now(),
        )
    )


def _load_articles(story: Story, session: Session) -> dict[int, Article]:
    article_ids: set[int] = set()
    for fact in story.facts:
        for ev in fact.evidence:
            article_ids.add(ev.article_id)
    if not article_ids:
        return {}
    return {
        a.id: a
        for a in session.scalars(
            select(Article).where(Article.id.in_(article_ids))
        ).all()
    }


def _cluster_articles(story: Story, session: Session) -> list[Article]:
    """All active articles in the story's cluster (for Level 2B check)."""
    return list(
        session.scalars(
            select(Article)
            .join(ClusterMember, ClusterMember.article_id == Article.id)
            .where(ClusterMember.cluster_id == story.cluster_id)
            .where(Article.status == "active")
        ).all()
    )


def verify_story(
    story: Story,
    session: Session,
    client: AnthropicLlmClient | None = None,
    injection_grey_zone_min_score: float = 0.0,
) -> Story:
    """Run the full verification pipeline on a story.

    Level 2B (injection re-check) and Level 2 (LLM judge) are skipped when
    client is None — useful for unit-testing Level 1 in isolation.

    Returns the (possibly updated) Story.
    """
    # Eagerly load facts + evidence
    session.refresh(story)
    facts: list[StoryFact] = list(
        session.scalars(
            select(StoryFact).where(StoryFact.story_id == story.id)
        ).all()
    )
    evidence_by_fact: dict[int, list[FactEvidence]] = {}
    for fact in facts:
        evidence_by_fact[fact.id] = list(
            session.scalars(
                select(FactEvidence).where(FactEvidence.fact_id == fact.id)
            ).all()
        )

    articles = _load_articles(story, session)

    # ------------------------------------------------------------------
    # Level 2B — injection re-check for grey-zone articles
    # ------------------------------------------------------------------
    if client is not None:
        cluster_articles = _cluster_articles(story, session)
        quarantined_any = False
        for article in cluster_articles:
            try:
                quarantined = recheck_injection(
                    article, client, min_score=injection_grey_zone_min_score
                )
            except BudgetExceeded:
                logger.info(
                    "verify story %d: budget exceeded during injection re-check — "
                    "skipping Level 2B",
                    story.id,
                )
                break
            if quarantined:
                quarantined_any = True
                _log(
                    session,
                    story.id,
                    None,
                    "injection_recheck",
                    False,
                    f"article_id={article.id} quarantined by LLM injection re-check",
                )
                session.flush()

        if quarantined_any:
            # Re-summarise the cluster without the quarantined article(s).
            # Import here to avoid circular imports.
            from app.llm.summarize import summarize_cluster  # noqa: PLC0415

            # Delete this story so summarize_cluster can create a fresh one.
            session.delete(story)
            session.flush()
            cluster = session.get(type(story.cluster), story.cluster_id)  # type: ignore[arg-type]
            if cluster is None:
                logger.warning(
                    "verify story: cluster %d not found after quarantine — aborting",
                    story.cluster_id,
                )
                session.rollback()
                return story
            new_story = summarize_cluster(cluster, client, session)
            if new_story is None:
                logger.warning(
                    "verify story: re-summarisation of cluster %d returned None",
                    story.cluster_id,
                )
                session.rollback()
                return story
            # Recurse without Level 2B to avoid looping
            return verify_story(new_story, session, client=client, injection_grey_zone_min_score=-1.0)

    # ------------------------------------------------------------------
    # Level 1 + Level 2 per-fact loop
    # ------------------------------------------------------------------
    for fact in facts:
        evidence = evidence_by_fact.get(fact.id, [])

        # 1. no_advice (hard fail — remove immediately)
        r: CheckResult = check_no_advice(fact)
        _log(session, story.id, fact.id, "no_advice", r.passed, r.details)
        if not r.passed:
            fact.verification_status = "removed"
            session.flush()
            continue

        # 2. quote_exists (hard fail)
        r = check_quote_exists(fact, evidence, articles)
        _log(session, story.id, fact.id, "quote_exists", r.passed, r.details)
        if not r.passed:
            fact.verification_status = "removed"
            session.flush()
            continue

        # 3. numbers_grounded (hard fail)
        r = check_numbers_grounded(fact, evidence, articles)
        _log(session, story.id, fact.id, "numbers_grounded", r.passed, r.details)
        if not r.passed:
            fact.verification_status = "removed"
            session.flush()
            continue

        # 4. entities_grounded (hard fail)
        r = check_entities_grounded(fact, evidence, articles)
        _log(session, story.id, fact.id, "entities_grounded", r.passed, r.details)
        if not r.passed:
            fact.verification_status = "removed"
            session.flush()
            continue

        # 5. opinion_placement (soft flag → Level 2)
        r = check_opinion_placement(fact, evidence)
        _log(session, story.id, fact.id, "opinion_placement", r.passed, r.details)
        if not r.passed and client is not None:
            quote_texts = [ev.quote_en for ev in evidence]
            try:
                support = judge_fact(fact, quote_texts, client)
            except (BudgetExceeded, ValueError) as exc:
                logger.warning(
                    "verify story %d fact %d: Level 2 judge failed (%s) — "
                    "leaving as partially_supported",
                    story.id,
                    fact.id,
                    exc,
                )
                fact.verification_status = "partially_supported"
                session.flush()
                continue

            _log(
                session,
                story.id,
                fact.id,
                "llm_judge",
                support != FactSupport.not_supported,
                f"support={support.value}",
            )
            if support == FactSupport.not_supported:
                fact.verification_status = "removed"
            elif support == FactSupport.partially_supported:
                fact.verification_status = "partially_supported"
            else:
                fact.verification_status = "verified"
            session.flush()
            continue

        # All checks passed (or opinion_placement flagged but no client → leave pending)
        if r.passed:
            fact.verification_status = "verified"
            session.flush()

    # ------------------------------------------------------------------
    # Compute story-level verification_status
    # ------------------------------------------------------------------
    session.refresh(story)
    remaining = [
        f for f in session.scalars(
            select(StoryFact).where(StoryFact.story_id == story.id)
        ).all()
        if f.verification_status != "removed"
    ]
    verified_count = sum(
        1 for f in remaining if f.verification_status in ("verified", "partially_supported")
    )

    all_facts_count = len(facts)
    if all_facts_count == 0:
        # No facts at all — treat as verified (nothing to fail)
        story.verification_status = "verified"
    elif verified_count == 0:
        story.verification_status = "unverified"
    elif verified_count < all_facts_count:
        story.verification_status = "partial"
    else:
        story.verification_status = "verified"

    session.commit()
    logger.info(
        "verify story %d: %s (facts: %d total, %d verified/partial, %d removed)",
        story.id,
        story.verification_status,
        all_facts_count,
        verified_count,
        all_facts_count - verified_count,
    )
    return story
