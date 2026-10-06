"""Evaluation harness runner.

Usage:
    cd backend
    uv run python -m tests.evals.runner [--mode live|replay] [--cases PATTERN] [--yes]
"""
from __future__ import annotations

import argparse
import fnmatch
import logging
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.core.db import Base
from app.llm.budget import BudgetGuard
from app.llm.classify import CLASSIFY_PROMPT_VERSION, classify_cluster
from app.llm.client import HAIKU_INPUT_COST, HAIKU_OUTPUT_COST, SONNET_INPUT_COST, SONNET_OUTPUT_COST, AnthropicLlmClient
from app.llm.summarize import SUMMARIZE_PROMPT_VERSION, summarize_cluster
from app.models.news import Article, ClusterMember, LlmCall, Source, StoryCluster
from app.sanitization.injection_scan import quarantine_threshold, scan_article
from app.verification.pipeline import verify_story
from tests.evals.runner.case import GoldenCase, load_all_cases
from tests.evals.runner.metrics import CaseResult, compute_metrics, hard_targets_met
from tests.evals.runner.replay import (
    REPLAY_CACHE_DIR,
    RecordingClient,
    ReplayCache,
    ReplayClient,
)
from tests.evals.runner.reporter import (
    build_report_md,
    load_previous_report,
    save_report,
)

logger = logging.getLogger(__name__)

_EVAL_MODELS = {
    "haiku": "claude-haiku-4-5",
    "sonnet": "claude-sonnet-4-6",
}

# Estimated tokens per case (conservative upper bound)
_EST_CLASSIFY_INPUT = 600
_EST_CLASSIFY_OUTPUT = 180
_EST_SUMMARIZE_INPUT = 1_200
_EST_SUMMARIZE_OUTPUT = 500
_EST_VERIFY_INPUT = 400
_EST_VERIFY_OUTPUT = 120


def _estimate_cost(n_cases: int) -> float:
    classify_cost = (
        _EST_CLASSIFY_INPUT * HAIKU_INPUT_COST
        + _EST_CLASSIFY_OUTPUT * HAIKU_OUTPUT_COST
    )
    summarize_cost = (
        _EST_SUMMARIZE_INPUT * SONNET_INPUT_COST
        + _EST_SUMMARIZE_OUTPUT * SONNET_OUTPUT_COST
    )
    verify_cost = (
        _EST_VERIFY_INPUT * SONNET_INPUT_COST
        + _EST_VERIFY_OUTPUT * SONNET_OUTPUT_COST
    )
    per_case = classify_cost + summarize_cost + verify_cost
    return per_case * n_cases


def _make_engine():
    return create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})


def _build_db(
    case: GoldenCase,
    session,
) -> tuple[StoryCluster, list[Article]]:
    """Persist GoldenCase articles as ORM objects; return (cluster, articles)."""
    now = datetime(2026, 10, 6, 12, 0, 0)
    threshold = quarantine_threshold()

    source = Source(name=f"eval_{case.id}", kind="api", is_official=False)
    session.add(source)
    session.flush()

    articles: list[Article] = []
    for ga in case.articles:
        scan_result = scan_article(ga.clean_text)
        status = "quarantined" if scan_result.injection_score >= threshold else "active"
        article = Article(
            source_id=source.id,
            publisher=ga.publisher,
            title=ga.title or f"{ga.ticker} news",
            url=f"https://eval.test/{case.id}/{ga.id}",
            canonical_url=f"https://eval.test/{case.id}/{ga.id}",
            published_at=now,
            fetched_at=now,
            tickers_raw=[ga.ticker],
            content_hash=None,
            raw_payload={},
            clean_text=ga.clean_text,
            injection_score=scan_result.injection_score,
            matched_rules=scan_result.matched_rules,
            status=status,
        )
        session.add(article)
        articles.append(article)
    session.flush()

    tickers = list({a.tickers_raw[0] for a in articles if a.tickers_raw})
    cluster = StoryCluster(
        primary_ticker=tickers[0] if tickers else None,
        first_seen_at=now,
        last_seen_at=now,
        article_count=len(articles),
        publisher_count=len({ga.publisher for ga in case.articles}),
    )
    session.add(cluster)
    session.flush()

    for article in articles:
        session.add(
            ClusterMember(
                cluster_id=cluster.id,
                article_id=article.id,
                match_method="eval",
                similarity=1.0,
                needs_llm_check=False,
            )
        )
    session.flush()
    return cluster, articles


def _run_case(
    case: GoldenCase,
    haiku_client,
    sonnet_client,
) -> CaseResult:
    """Run a single golden case end-to-end in an isolated in-memory DB."""
    engine = _make_engine()
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)

    with Session() as session:
        t0 = time.perf_counter()
        try:
            cluster, articles = _build_db(case, session)
            art_map = {a.id: a for a in articles}

            layer1_quarantined = any(a.status == "quarantined" for a in articles)

            classification = classify_cluster(cluster, haiku_client, session)
            story = summarize_cluster(cluster, sonnet_client, session)

            if story is not None:
                story = verify_story(story, session, client=sonnet_client)
                # Eagerly load facts + evidence
                session.refresh(story)
                for fact in story.facts:
                    _ = fact.evidence

            wall_ms = (time.perf_counter() - t0) * 1000
            llm_calls = list(session.scalars(select(LlmCall)).all())

            return CaseResult(
                case=case,
                story=story,
                classification=classification,
                layer1_quarantined=layer1_quarantined,
                wall_time_ms=wall_ms,
                llm_calls=llm_calls,
                articles=art_map,
            )
        except Exception as exc:  # noqa: BLE001
            wall_ms = (time.perf_counter() - t0) * 1000
            logger.error("case %s failed: %s", case.id, exc, exc_info=True)
            return CaseResult(
                case=case,
                wall_time_ms=wall_ms,
                error=str(exc),
            )


def _make_live_clients(api_key: str, session) -> tuple:
    guard = BudgetGuard(session, daily_usd=50.0, monthly_usd=500.0)
    haiku = AnthropicLlmClient(
        api_key=api_key,
        model=_EVAL_MODELS["haiku"],
        guard=guard,
        input_cost_per_token=HAIKU_INPUT_COST,
        output_cost_per_token=HAIKU_OUTPUT_COST,
    )
    sonnet = AnthropicLlmClient(
        api_key=api_key,
        model=_EVAL_MODELS["sonnet"],
        guard=guard,
        input_cost_per_token=SONNET_INPUT_COST,
        output_cost_per_token=SONNET_OUTPUT_COST,
    )
    return haiku, sonnet


def run_live(
    cases: list[GoldenCase],
    api_key: str,
    yes: bool = False,
) -> list[CaseResult]:
    """Run cases against the real API, recording responses to replay cache."""
    n = len(cases)
    est = _estimate_cost(n)
    print(f"\n  Cases to run: {n}")
    print(f"  Estimated cost: ${est:.3f} USD (upper bound)")
    if not yes:
        print("\n  Type 'yes' to proceed: ", end="", flush=True)
        answer = input().strip().lower()
        if answer != "yes":
            print("Aborted.")
            sys.exit(0)

    cache = ReplayCache(REPLAY_CACHE_DIR)
    results: list[CaseResult] = []

    # Shared session for budget guard only (cost tracking across cases)
    shared_engine = _make_engine()
    Base.metadata.create_all(shared_engine)
    SharedSession = sessionmaker(bind=shared_engine)

    with SharedSession() as shared_session:
        haiku_real, sonnet_real = _make_live_clients(api_key, shared_session)

        for i, case in enumerate(cases, 1):
            print(f"  [{i:02d}/{n}] {case.id} ... ", end="", flush=True)
            haiku = RecordingClient(haiku_real, cache, case.id)
            sonnet = RecordingClient(sonnet_real, cache, case.id)
            result = _run_case(case, haiku, sonnet)
            status = "ERROR" if result.error else (
                result.story.verification_status if result.story else "no-story"
            )
            cost = sum(c.cost_usd for c in result.llm_calls)
            print(f"{status}  ${cost:.4f}  {result.wall_time_ms:.0f}ms")
            results.append(result)

    return results


def run_replay(cases: list[GoldenCase]) -> list[CaseResult]:
    """Run cases using recorded responses; no API calls."""
    cache = ReplayCache(REPLAY_CACHE_DIR)
    results: list[CaseResult] = []
    n = len(cases)

    for i, case in enumerate(cases, 1):
        print(f"  [{i:02d}/{n}] {case.id} (replay) ... ", end="", flush=True)

        engine = _make_engine()
        Base.metadata.create_all(engine)
        Session = sessionmaker(bind=engine)

        with Session() as session:
            haiku = ReplayClient(cache, case.id, session, _EVAL_MODELS["haiku"])
            sonnet = ReplayClient(cache, case.id, session, _EVAL_MODELS["sonnet"])
            result = _run_case(case, haiku, sonnet)

        status = "ERROR" if result.error else (
            result.story.verification_status if result.story else "no-story"
        )
        print(status)
        results.append(result)

    return results


def main() -> None:
    logging.basicConfig(level=logging.WARNING)

    parser = argparse.ArgumentParser(description="Financial News eval harness")
    parser.add_argument("--mode", choices=["live", "replay"], default="replay")
    parser.add_argument("--cases", default="*", help="Glob pattern on case id")
    parser.add_argument("--yes", action="store_true", help="Skip cost confirmation")
    parser.add_argument("--out", default=str(Path(__file__).parent.parent / "reports"))
    args = parser.parse_args()

    all_cases = load_all_cases()
    cases = [c for c in all_cases if fnmatch.fnmatch(c.id, args.cases)]
    if not cases:
        print(f"No cases matched pattern {args.cases!r}.")
        sys.exit(1)

    print(f"\n=== Financial News Eval Harness ({args.mode.upper()} mode) ===")
    print(f"  Loaded {len(cases)} cases from {len(all_cases)} total")

    if args.mode == "live":
        import os
        api_key = os.environ.get("ANTHROPIC_API_KEY", "")
        if not api_key:
            print("ERROR: ANTHROPIC_API_KEY not set.")
            sys.exit(1)
        results = run_live(cases, api_key, yes=args.yes)
    else:
        results = run_replay(cases)

    print("\nComputing metrics...")
    metrics = compute_metrics(results)

    prompt_version = SUMMARIZE_PROMPT_VERSION
    run_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    previous = load_previous_report(prompt_version)
    case_errors = [(r.case.id, r.error) for r in results if r.error]

    md = build_report_md(
        metrics=metrics,
        prompt_version=prompt_version,
        run_date=run_date,
        previous=previous,
        case_errors=case_errors or None,
    )
    md_path, json_path = save_report(md, metrics, run_date, prompt_version)

    print(md)
    print(f"\nReport saved: {md_path}")
    print(f"JSON saved:   {json_path}")

    failures = hard_targets_met(metrics)
    if failures:
        print("\n⚠  Hard targets FAILED:")
        for f in failures:
            print(f"   {f}")
        sys.exit(1)
    else:
        print("\n✓ All hard targets met.")
        sys.exit(0)
