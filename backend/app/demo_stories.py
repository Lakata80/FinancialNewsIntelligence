"""Demo CLI: print summarized stories for a given ticker.

Usage:
    python -m app.demo_stories --ticker NVDA
"""
from __future__ import annotations

import argparse

from sqlalchemy import select

from app.core.db import SessionLocal
from app.models.news import Article, FactEvidence, Story, StoryCluster, StoryFact


_STATUS_ICON = {
    "verified": "✓",
    "partially_supported": "~",
    "removed": "✗",
    "pending": "?",
}


def _print_verification(story_id: int, facts: list, session) -> None:  # type: ignore[no-untyped-def]
    from sqlalchemy import select

    from app.models.news import VerificationLog

    logs_by_fact: dict[int, list[VerificationLog]] = {}
    all_logs = session.scalars(
        select(VerificationLog).where(VerificationLog.story_id == story_id)
    ).all()
    for log in all_logs:
        if log.fact_id is not None:
            logs_by_fact.setdefault(log.fact_id, []).append(log)

    for fact in facts:
        icon = _STATUS_ICON.get(fact.verification_status, "?")
        print(f"  [{fact.fact_order + 1}] {icon}  {fact.text_bg}")
        fact_logs = logs_by_fact.get(fact.id, [])
        for log in fact_logs:
            if not log.passed:
                print(f"        ↳ [{log.check}] {log.details or ''}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Display summarized stories by ticker")
    parser.add_argument("--ticker", required=True, help="Ticker symbol (e.g. NVDA)")
    parser.add_argument(
        "--verify",
        action="store_true",
        help="Show per-fact verification status (✓/~/✗) with reasons",
    )
    args = parser.parse_args()
    ticker = args.ticker.upper()

    with SessionLocal() as session:
        stories = session.scalars(
            select(Story)
            .join(StoryCluster, Story.cluster_id == StoryCluster.id)
            .where(StoryCluster.primary_ticker == ticker)
            .order_by(Story.created_at.desc())
        ).all()

        if not stories:
            print(f"No stories found for {ticker}")
            return

        for story in stories:
            print(f"\n{'=' * 60}")
            print(f"TITLE:   {story.title_bg}")
            print(f"SUMMARY: {story.summary_bg}")
            print(f"Model:   {story.model_version}  |  Prompt: {story.prompt_version}")
            print(f"Status:  {story.verification_status}")

            facts = session.scalars(
                select(StoryFact)
                .where(StoryFact.story_id == story.id)
                .order_by(StoryFact.fact_order)
            ).all()

            if facts:
                print("\nFACTS:")
                if args.verify:
                    _print_verification(story.id, facts, session)
                else:
                    for fact in facts:
                        print(f"  [{fact.fact_order + 1}] {fact.text_bg}")
                        evidence_items = session.scalars(
                            select(FactEvidence).where(FactEvidence.fact_id == fact.id)
                        ).all()
                        for ev in evidence_items:
                            article = session.get(Article, ev.article_id)
                            publisher = article.publisher if article else "unknown"
                            print(f'       → "{ev.quote_en}" ({publisher})')
            else:
                print("\n(No facts recorded)")


if __name__ == "__main__":
    main()
