"""Pipeline trigger API — runs the full pipeline in a background thread."""
from __future__ import annotations

import logging
import threading
import uuid
from typing import Any

import yaml
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.core.log_config import run_id_var

router = APIRouter()
logger = logging.getLogger(__name__)

_CONFIG_PATH = "config.yaml"

# in-memory run tracker: {run_id: {"stage", "done", "error"}}
_runs: dict[str, dict[str, Any]] = {}
_lock = threading.Lock()


class PipelineRunOut(BaseModel):
    run_id: str


class PipelineStatusOut(BaseModel):
    run_id: str
    stage: str  # "pending" | "fetch" | "dedup" | "classify" | "summarize" | "verify" | "done"
    done: bool
    error: str | None


def _load_cfg() -> dict:
    try:
        with open(_CONFIG_PATH, encoding="utf-8") as fh:
            return yaml.safe_load(fh) or {}
    except FileNotFoundError:
        return {}


def _update(run_id: str, stage: str, *, done: bool = False, error: str | None = None) -> None:
    with _lock:
        _runs[run_id] = {"stage": stage, "done": done, "error": error}


def _running_id() -> str | None:
    with _lock:
        for rid, state in _runs.items():
            if not state["done"] and state["error"] is None:
                return rid
    return None


def _run(run_id: str) -> None:
    run_id_var.set(run_id)
    try:
        _do_fetch(run_id)
        _do_dedup(run_id)
        _do_classify(run_id)
        _do_summarize(run_id)
        _do_verify(run_id)
        _update(run_id, "done", done=True)
    except Exception as exc:
        logger.exception("Pipeline run %s failed at stage %s", run_id, _runs.get(run_id, {}).get("stage"))
        _update(run_id, _runs.get(run_id, {}).get("stage", "unknown"), error=str(exc))


def _do_fetch(run_id: str) -> None:
    _update(run_id, "fetch")
    from app.ingestion.ecb import ECBPressRSS
    from app.ingestion.fed import FedPressRSS
    from app.ingestion.finnhub import FinnhubCompanyNews
    from app.ingestion.pipeline import run_all_connectors
    from app.ingestion.yahoo import YahooTickerRSS

    connectors = [YahooTickerRSS(), FinnhubCompanyNews(), FedPressRSS(), ECBPressRSS()]
    run_all_connectors(connectors)


def _do_dedup(run_id: str) -> None:
    _update(run_id, "dedup")
    from app.core.db import SessionLocal
    from app.dedup.pipeline import run_dedup

    with SessionLocal() as session:
        run_dedup(session)
        session.commit()


def _do_classify(run_id: str) -> None:
    _update(run_id, "classify")
    from sqlalchemy import select

    from app.core.config import settings
    from app.core.db import SessionLocal
    from app.llm.budget import BudgetExceeded, BudgetGuard
    from app.llm.classify import classify_cluster
    from app.llm.client import AnthropicLlmClient
    from app.models.news import StoryCluster

    if not settings.anthropic_api_key:
        logger.warning("ANTHROPIC_API_KEY not set — skipping classify stage")
        return

    cfg = _load_cfg()
    model = cfg.get("llm", {}).get("model", "claude-haiku-4-5")
    daily = float(cfg.get("budget", {}).get("daily_llm_budget_usd", 0.5))
    monthly = float(cfg.get("budget", {}).get("monthly_llm_budget_usd", 10.0))

    with SessionLocal() as session:
        guard = BudgetGuard(session=session, daily_usd=daily, monthly_usd=monthly)
        client = AnthropicLlmClient(api_key=settings.anthropic_api_key, model=model, guard=guard)
        unclassified = session.scalars(
            select(StoryCluster).where(StoryCluster.classification_model.is_(None))
        ).all()
        for cluster in unclassified:
            try:
                classify_cluster(cluster, client, session)
            except BudgetExceeded:
                break
        session.commit()


def _do_summarize(run_id: str) -> None:
    _update(run_id, "summarize")
    from sqlalchemy import or_, select

    from app.core.config import settings
    from app.core.db import SessionLocal
    from app.llm.budget import BudgetExceeded, BudgetGuard
    from app.llm.client import SONNET_INPUT_COST, SONNET_OUTPUT_COST, AnthropicLlmClient
    from app.llm.summarize import summarize_cluster
    from app.models.news import Story, StoryCluster

    if not settings.anthropic_api_key:
        logger.warning("ANTHROPIC_API_KEY not set — skipping summarize stage")
        return

    cfg = _load_cfg()
    model = cfg.get("llm", {}).get("summarize_model", "claude-sonnet-4-6")
    daily = float(cfg.get("budget", {}).get("daily_llm_budget_usd", 0.5))
    monthly = float(cfg.get("budget", {}).get("monthly_llm_budget_usd", 10.0))
    max_articles = int(cfg.get("llm", {}).get("max_articles_per_cluster", 10))

    with SessionLocal() as session:
        guard = BudgetGuard(session=session, daily_usd=daily, monthly_usd=monthly)
        client = AnthropicLlmClient(
            api_key=settings.anthropic_api_key,
            model=model,
            guard=guard,
            input_cost_per_token=SONNET_INPUT_COST,
            output_cost_per_token=SONNET_OUTPUT_COST,
        )
        # Include clusters with no story AND clusters whose story is stale (new article joined)
        stale_subq = (
            select(StoryCluster.id)
            .join(Story, Story.cluster_id == StoryCluster.id)
            .where(Story.created_at < StoryCluster.last_seen_at)
            .scalar_subquery()
        )
        no_story_subq = select(Story.cluster_id).scalar_subquery()
        candidates = session.scalars(
            select(StoryCluster)
            .where(StoryCluster.visible.is_(True))
            .where(
                or_(
                    StoryCluster.id.not_in(no_story_subq),
                    StoryCluster.id.in_(stale_subq),
                )
            )
        ).all()
        for cluster in candidates:
            try:
                summarize_cluster(cluster, client, session, max_articles=max_articles)
            except BudgetExceeded:
                break
        session.commit()


def _do_verify(run_id: str) -> None:
    _update(run_id, "verify")
    from sqlalchemy import select

    from app.core.config import settings
    from app.core.db import SessionLocal
    from app.llm.budget import BudgetExceeded, BudgetGuard
    from app.llm.client import SONNET_INPUT_COST, SONNET_OUTPUT_COST, AnthropicLlmClient
    from app.models.news import Story
    from app.verification.pipeline import verify_story

    if not settings.anthropic_api_key:
        logger.warning("ANTHROPIC_API_KEY not set — skipping verify stage")
        return

    cfg = _load_cfg()
    model = cfg.get("llm", {}).get("verify_model", "claude-sonnet-4-6")
    daily = float(cfg.get("budget", {}).get("daily_llm_budget_usd", 0.5))
    monthly = float(cfg.get("budget", {}).get("monthly_llm_budget_usd", 10.0))
    injection_threshold = float(cfg.get("llm", {}).get("injection_grey_zone_min_score", 0.0))

    with SessionLocal() as session:
        guard = BudgetGuard(session=session, daily_usd=daily, monthly_usd=monthly)
        client = AnthropicLlmClient(
            api_key=settings.anthropic_api_key,
            model=model,
            guard=guard,
            input_cost_per_token=SONNET_INPUT_COST,
            output_cost_per_token=SONNET_OUTPUT_COST,
        )
        pending = session.scalars(
            select(Story).where(Story.verification_status == "pending")
        ).all()
        for story in pending:
            try:
                verify_story(
                    story,
                    session,
                    client=client,
                    injection_grey_zone_min_score=injection_threshold,
                )
            except BudgetExceeded:
                break
            except Exception as exc:
                logger.warning("verify story %d error: %s", story.id, exc)
        session.commit()


class PipelineEstimateOut(BaseModel):
    new_clusters: int
    changed_clusters: int
    total_clusters_to_process: int
    estimated_cost_usd: float
    show_warning: bool


@router.get("/pipeline/estimate", response_model=PipelineEstimateOut)
def estimate_pipeline(db: Session = Depends(get_db)) -> PipelineEstimateOut:
    """Count clusters that need LLM work and estimate their cost."""
    from sqlalchemy import or_, select

    from app.models.news import Story, StoryCluster

    cfg = _load_cfg()
    threshold = int(cfg.get("pipeline", {}).get("cost_estimate_threshold", 5))

    no_story_subq = select(Story.cluster_id).scalar_subquery()
    stale_subq = (
        select(StoryCluster.id)
        .join(Story, Story.cluster_id == StoryCluster.id)
        .where(Story.created_at < StoryCluster.last_seen_at)
        .scalar_subquery()
    )

    from sqlalchemy import func

    new_count: int = db.query(func.count(StoryCluster.id)).filter(
        StoryCluster.visible.is_(True),
        StoryCluster.id.not_in(no_story_subq),
    ).scalar() or 0

    changed_count: int = db.query(func.count(StoryCluster.id)).filter(
        StoryCluster.visible.is_(True),
        StoryCluster.id.in_(stale_subq),
    ).scalar() or 0

    total = new_count + changed_count

    # Cost estimate per cluster: Haiku classify + Sonnet summarize + Sonnet verify
    # Token counts from ADR-023 defaults
    from app.llm.client import HAIKU_INPUT_COST, HAIKU_OUTPUT_COST, SONNET_INPUT_COST, SONNET_OUTPUT_COST
    cost_per_cluster = (
        600 * HAIKU_INPUT_COST + 180 * HAIKU_OUTPUT_COST      # classify
        + 1200 * SONNET_INPUT_COST + 500 * SONNET_OUTPUT_COST  # summarize
        + 400 * SONNET_INPUT_COST + 120 * SONNET_OUTPUT_COST   # verify
    )
    estimated_cost = round(total * cost_per_cluster, 4)

    return PipelineEstimateOut(
        new_clusters=new_count,
        changed_clusters=changed_count,
        total_clusters_to_process=total,
        estimated_cost_usd=estimated_cost,
        show_warning=total > threshold,
    )


@router.post("/pipeline/run", response_model=PipelineRunOut)
def run_pipeline() -> PipelineRunOut:
    existing = _running_id()
    if existing:
        return PipelineRunOut(run_id=existing)

    run_id = uuid.uuid4().hex[:8]
    _update(run_id, "pending")
    t = threading.Thread(target=_run, args=(run_id,), daemon=True)
    t.start()
    return PipelineRunOut(run_id=run_id)


@router.get("/pipeline/status/{run_id}", response_model=PipelineStatusOut)
def get_pipeline_status(run_id: str) -> PipelineStatusOut:
    state = _runs.get(run_id)
    if state is None:
        raise HTTPException(status_code=404, detail="Run not found")
    return PipelineStatusOut(
        run_id=run_id,
        stage=state["stage"],
        done=state["done"],
        error=state["error"],
    )
