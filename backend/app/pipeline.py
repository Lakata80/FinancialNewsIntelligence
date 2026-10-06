"""CLI entry point for post-ingestion pipeline stages.

Usage:
    python -m app.pipeline --stage dedup
    python -m app.pipeline --stage classify
"""
from __future__ import annotations

import argparse
import logging
import sys

import yaml

from app.core.config import settings
from app.core.db import SessionLocal
from app.dedup.minhash_dedup import DedupConfig
from app.dedup.pipeline import run_dedup
from app.models.news import ClusterMember, StoryCluster

_CONFIG_PATH = "config.yaml"

logger = logging.getLogger(__name__)


def _load_yaml() -> dict:
    try:
        with open(_CONFIG_PATH, encoding="utf-8") as fh:
            return yaml.safe_load(fh) or {}
    except FileNotFoundError:
        return {}


def _load_dedup_config() -> DedupConfig:
    cfg = _load_yaml()
    dedup = cfg.get("dedup", {})
    return DedupConfig(
        lower_threshold=float(dedup.get("minhash_lower_threshold", 0.5)),
        upper_threshold=float(dedup.get("minhash_upper_threshold", 0.8)),
        window_hours=int(dedup.get("window_hours", 48)),
    )


def _load_llm_config() -> dict:
    cfg = _load_yaml()
    return {
        "model": cfg.get("llm", {}).get("model", "claude-haiku-4-5"),
        "daily_budget": float(
            cfg.get("budget", {}).get("daily_llm_budget_usd", 0.5)
        ),
        "monthly_budget": float(
            cfg.get("budget", {}).get("monthly_llm_budget_usd", 10.0)
        ),
        "dedup_confidence_threshold": float(
            cfg.get("llm", {}).get("dedup_confidence_threshold", 0.8)
        ),
        "summarize_model": cfg.get("llm", {}).get("summarize_model", "claude-sonnet-4-6"),
        "verify_model": cfg.get("llm", {}).get("verify_model", "claude-sonnet-4-6"),
        "max_articles_per_cluster": int(
            cfg.get("llm", {}).get("max_articles_per_cluster", 10)
        ),
        "injection_grey_zone_min_score": float(
            cfg.get("llm", {}).get("injection_grey_zone_min_score", 0.0)
        ),
    }


def _stage_dedup() -> None:
    config = _load_dedup_config()

    with SessionLocal() as session:
        stats = run_dedup(session, config)

        print(
            f"\nArticles: {stats.articles_processed - stats.quarantined_count} active"
            f"  /  {stats.quarantined_count} quarantined"
        )
        print(
            f"Clusters: {stats.exact_clusters} exact"
            f"  /  {stats.minhash_clusters} minhash"
        )

        llm_check_count = (
            session.query(ClusterMember)
            .filter(ClusterMember.needs_llm_check.is_(True))
            .count()
        )
        if llm_check_count:
            print(f"          {llm_check_count} needs-llm-check")

        top5 = (
            session.query(StoryCluster)
            .order_by(StoryCluster.article_count.desc())
            .limit(5)
            .all()
        )

        if top5:
            print("\nTop 5 clusters:")
            for i, cluster in enumerate(top5, start=1):
                ticker = cluster.primary_ticker or "(macro)"
                publishers: list[str] = []
                for member in cluster.members:
                    pub = member.article.publisher
                    if pub and pub not in publishers:
                        publishers.append(pub)
                pub_str = ", ".join(publishers) if publishers else "—"
                print(
                    f"  #{i}  {ticker:8s}  {cluster.article_count} articles"
                    f"  {cluster.publisher_count} publishers  [{pub_str}]"
                )
        else:
            print("\n(No clusters found)")


def _stage_classify() -> None:
    from datetime import UTC, datetime, timedelta

    from sqlalchemy import select, update

    from app.llm.budget import BudgetExceeded, BudgetGuard
    from app.llm.classify import classify_cluster
    from app.llm.client import AnthropicLlmClient
    from app.llm.dedup_check import check_same_event

    llm_cfg = _load_llm_config()
    api_key = settings.anthropic_api_key

    if not api_key:
        print("ANTHROPIC_API_KEY not set — aborting classify stage.")
        sys.exit(1)

    with SessionLocal() as session:
        guard = BudgetGuard(
            session=session,
            daily_usd=llm_cfg["daily_budget"],
            monthly_usd=llm_cfg["monthly_budget"],
        )
        client = AnthropicLlmClient(
            api_key=api_key,
            model=llm_cfg["model"],
            guard=guard,
        )

        unclassified = session.scalars(
            select(StoryCluster).where(StoryCluster.classification_model.is_(None))
        ).all()

        classified = 0
        hidden = 0
        budget_skip = 0
        rejected = 0
        budget_hit = False

        for cluster in unclassified:
            if budget_hit:
                budget_skip += 1
                continue
            try:
                result = classify_cluster(cluster, client, session)
            except BudgetExceeded:
                budget_hit = True
                budget_skip += 1
                continue

            if result is None:
                rejected += 1
            else:
                classified += 1
                if not cluster.visible:
                    hidden += 1

        print(
            f"\nClusters processed: {len(unclassified)}"
            f"\n  Classified: {classified}"
            f"  |  Budget skip: {budget_skip}"
            f"  |  Rejected: {rejected}"
            f"\n  Visible: {classified - hidden}"
            f"  |  Hidden (promotional/off-topic): {hidden}"
        )

        if budget_hit:
            return

        # Dedup LLM checks for border pairs
        threshold = llm_cfg["dedup_confidence_threshold"]
        window_hours = int(_load_yaml().get("dedup", {}).get("window_hours", 48))
        cutoff = datetime.now(UTC).replace(tzinfo=None) - timedelta(hours=window_hours)

        border_clusters = list(
            session.scalars(
                select(StoryCluster)
                .join(ClusterMember, ClusterMember.cluster_id == StoryCluster.id)
                .where(ClusterMember.needs_llm_check.is_(True))
                .where(StoryCluster.first_seen_at >= cutoff)
                .distinct()
            ).all()
        )

        checked = 0
        merged = 0
        kept_separate = 0
        seen_pairs: set[frozenset[int]] = set()
        merged_ids: set[int] = set()

        for i, ca in enumerate(border_clusters):
            if ca.id in merged_ids:
                continue
            for cb in border_clusters[i + 1 :]:
                if cb.id in merged_ids:
                    continue
                if ca.primary_ticker != cb.primary_ticker:
                    continue
                pair = frozenset([ca.id, cb.id])
                if pair in seen_pairs:
                    continue
                seen_pairs.add(pair)
                checked += 1

                try:
                    same = check_same_event(ca, cb, client, threshold, session)
                except BudgetExceeded:
                    break

                if same:
                    _merge_clusters(session, keep=ca, discard=cb, update=update)
                    merged_ids.add(cb.id)
                    merged += 1
                else:
                    kept_separate += 1

        if checked:
            print(
                f"\nBorder-pair checks: {checked}"
                f"\n  Merged: {merged}  |  Kept separate: {kept_separate}"
            )


def _merge_clusters(session, *, keep: StoryCluster, discard: StoryCluster, update) -> None:  # type: ignore[no-untyped-def]
    """Move all members from discard into keep, then delete discard."""
    session.execute(
        update(ClusterMember)
        .where(ClusterMember.cluster_id == discard.id)
        .values(cluster_id=keep.id)
    )
    session.flush()
    session.refresh(keep)

    keep.article_count = len(keep.members)
    publishers = {m.article.publisher for m in keep.members if m.article.publisher}
    keep.publisher_count = len(publishers)
    keep.last_seen_at = max(m.article.published_at for m in keep.members)

    session.delete(discard)
    session.commit()


def _stage_summarize() -> None:
    from sqlalchemy import select

    from app.llm.budget import BudgetExceeded, BudgetGuard
    from app.llm.client import SONNET_INPUT_COST, SONNET_OUTPUT_COST, AnthropicLlmClient
    from app.llm.summarize import summarize_cluster
    from app.models.news import Story

    llm_cfg = _load_llm_config()
    api_key = settings.anthropic_api_key

    if not api_key:
        print("ANTHROPIC_API_KEY not set — aborting summarize stage.")
        sys.exit(1)

    with SessionLocal() as session:
        guard = BudgetGuard(
            session=session,
            daily_usd=llm_cfg["daily_budget"],
            monthly_usd=llm_cfg["monthly_budget"],
        )
        client = AnthropicLlmClient(
            api_key=api_key,
            model=llm_cfg["summarize_model"],
            guard=guard,
            input_cost_per_token=SONNET_INPUT_COST,
            output_cost_per_token=SONNET_OUTPUT_COST,
        )

        summarized_subq = select(Story.cluster_id).scalar_subquery()
        candidates = session.scalars(
            select(StoryCluster)
            .where(StoryCluster.visible.is_(True))
            .where(StoryCluster.id.not_in(summarized_subq))
        ).all()

        summarized = 0
        budget_skip = 0
        rejected = 0
        budget_hit = False

        for cluster in candidates:
            if budget_hit:
                budget_skip += 1
                continue
            try:
                result = summarize_cluster(
                    cluster,
                    client,
                    session,
                    max_articles=llm_cfg["max_articles_per_cluster"],
                )
            except BudgetExceeded:
                budget_hit = True
                budget_skip += 1
                continue

            if result is None:
                rejected += 1
            else:
                summarized += 1

        print(
            f"\nClusters processed: {len(candidates)}"
            f"\n  Summarized: {summarized}"
            f"  |  Budget skip: {budget_skip}"
            f"  |  Rejected: {rejected}"
        )


def _stage_verify() -> None:
    from sqlalchemy import select

    from app.llm.budget import BudgetExceeded, BudgetGuard
    from app.llm.client import SONNET_INPUT_COST, SONNET_OUTPUT_COST, AnthropicLlmClient
    from app.models.news import Story
    from app.verification.pipeline import verify_story

    llm_cfg = _load_llm_config()
    api_key = settings.anthropic_api_key

    if not api_key:
        print("ANTHROPIC_API_KEY not set — aborting verify stage.")
        sys.exit(1)

    with SessionLocal() as session:
        guard = BudgetGuard(
            session=session,
            daily_usd=llm_cfg["daily_budget"],
            monthly_usd=llm_cfg["monthly_budget"],
        )
        client = AnthropicLlmClient(
            api_key=api_key,
            model=llm_cfg["verify_model"],
            guard=guard,
            input_cost_per_token=SONNET_INPUT_COST,
            output_cost_per_token=SONNET_OUTPUT_COST,
        )

        pending = session.scalars(
            select(Story).where(Story.verification_status == "pending")
        ).all()

        verified = 0
        partial = 0
        unverified_count = 0
        errors = 0
        budget_hit = False

        for story in pending:
            if budget_hit:
                errors += 1
                continue
            try:
                result = verify_story(
                    story,
                    session,
                    client=client,
                    injection_grey_zone_min_score=llm_cfg.get(
                        "injection_grey_zone_min_score", 0.0
                    ),
                )
            except BudgetExceeded:
                budget_hit = True
                errors += 1
                continue
            except Exception as exc:
                logger.warning("verify story %d error: %s", story.id, exc)
                errors += 1
                continue

            if result.verification_status == "verified":
                verified += 1
            elif result.verification_status == "partial":
                partial += 1
            else:
                unverified_count += 1

        print(
            f"\nStories processed: {len(pending)}"
            f"\n  Verified: {verified}"
            f"  |  Partial: {partial}"
            f"  |  Unverified: {unverified_count}"
            f"  |  Errors/budget: {errors}"
        )


def main() -> None:
    parser = argparse.ArgumentParser(description="Financial News Intelligence pipeline")
    parser.add_argument(
        "--stage",
        choices=["dedup", "classify", "summarize", "verify"],
        required=True,
        help="Pipeline stage to run",
    )
    args = parser.parse_args()

    if args.stage == "dedup":
        _stage_dedup()
    elif args.stage == "classify":
        _stage_classify()
    elif args.stage == "summarize":
        _stage_summarize()
    elif args.stage == "verify":
        _stage_verify()


if __name__ == "__main__":
    main()
