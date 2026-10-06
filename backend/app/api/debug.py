from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import yaml
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import case, func
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.models.news import Article, FetchRun, LlmCall, Source, Story, StoryFact, VerificationLog

router = APIRouter()

_CONFIG_PATH = Path(__file__).parent.parent.parent.parent / "config.yaml"


class FetchRunOut(BaseModel):
    source_name: str
    source_kind: str
    run_id: int | None
    started_at: datetime | None
    finished_at: datetime | None
    status: str
    items_seen: int
    items_new: int
    newest_item_at: datetime | None
    error: str | None


class QuarantineOut(BaseModel):
    id: int
    title: str
    url: str
    publisher: str | None
    published_at: datetime
    injection_score: float
    matched_rules: list[str]
    source_name: str


class VerifLogOut(BaseModel):
    id: int
    story_id: int
    fact_id: int | None
    story_title: str
    fact_text: str | None
    check: str
    passed: bool
    details: str | None
    created_at: datetime


class PurposeCost(BaseModel):
    purpose: str
    cost_usd: float


class CostsOut(BaseModel):
    today_usd: float
    today_budget_usd: float
    month_usd: float
    month_budget_usd: float
    by_purpose: list[PurposeCost]


def _load_observability_config() -> dict:
    try:
        with open(_CONFIG_PATH, encoding="utf-8") as fh:
            cfg = yaml.safe_load(fh) or {}
    except FileNotFoundError:
        cfg = {}
    return cfg.get("observability", {})


def _load_budgets() -> tuple[float, float]:
    try:
        with open(_CONFIG_PATH, encoding="utf-8") as fh:
            cfg = yaml.safe_load(fh) or {}
    except FileNotFoundError:
        cfg = {}
    budget = cfg.get("budget", {})
    return (
        float(budget.get("daily_llm_budget_usd", 0.5)),
        float(budget.get("monthly_llm_budget_usd", 10.0)),
    )


@router.get("/debug/fetch-runs", response_model=list[FetchRunOut])
def list_fetch_runs(db: Session = Depends(get_db)) -> list[FetchRunOut]:
    sources = db.query(Source).filter(Source.enabled.is_(True)).all()
    results: list[FetchRunOut] = []
    for source in sources:
        last_run = (
            db.query(FetchRun)
            .filter(FetchRun.source_id == source.id)
            .order_by(FetchRun.started_at.desc())
            .first()
        )
        if last_run:
            results.append(
                FetchRunOut(
                    source_name=source.name,
                    source_kind=source.kind,
                    run_id=last_run.id,
                    started_at=last_run.started_at,
                    finished_at=last_run.finished_at,
                    status=last_run.status,
                    items_seen=last_run.items_seen,
                    items_new=last_run.items_new,
                    newest_item_at=last_run.newest_item_at,
                    error=last_run.error,
                )
            )
        else:
            results.append(
                FetchRunOut(
                    source_name=source.name,
                    source_kind=source.kind,
                    run_id=None,
                    started_at=None,
                    finished_at=None,
                    status="never_run",
                    items_seen=0,
                    items_new=0,
                    newest_item_at=None,
                    error=None,
                )
            )
    return results


@router.get("/debug/quarantine", response_model=list[QuarantineOut])
def list_quarantine(db: Session = Depends(get_db)) -> list[QuarantineOut]:
    rows = (
        db.query(Article)
        .join(Source, Article.source_id == Source.id)
        .filter(Article.status == "quarantined")
        .order_by(Article.published_at.desc())
        .all()
    )
    return [
        QuarantineOut(
            id=a.id,
            title=a.title,
            url=a.url,
            publisher=a.publisher,
            published_at=a.published_at,
            injection_score=a.injection_score or 0.0,
            matched_rules=a.matched_rules or [],
            source_name=a.source.name,
        )
        for a in rows
    ]


@router.post("/debug/quarantine/{article_id}/release")
def release_quarantine(
    article_id: int,
    db: Session = Depends(get_db),
) -> dict:
    article = db.query(Article).filter(Article.id == article_id).first()
    if article is None:
        raise HTTPException(status_code=404, detail="Article not found")
    if article.status != "quarantined":
        raise HTTPException(status_code=400, detail="Article is not quarantined")
    article.status = "active"
    db.commit()
    return {"ok": True}


@router.post("/debug/quarantine/{article_id}/confirm")
def confirm_quarantine(
    article_id: int,
    db: Session = Depends(get_db),
) -> dict:
    article = db.query(Article).filter(Article.id == article_id).first()
    if article is None:
        raise HTTPException(status_code=404, detail="Article not found")
    return {"ok": True}


@router.get("/debug/verification-log", response_model=list[VerifLogOut])
def list_verification_log(db: Session = Depends(get_db)) -> list[VerifLogOut]:
    rows = (
        db.query(VerificationLog)
        .join(Story, VerificationLog.story_id == Story.id)
        .filter(VerificationLog.passed.is_(False))
        .order_by(VerificationLog.created_at.desc())
        .limit(200)
        .all()
    )
    story_titles: dict[int, str] = {}
    fact_texts: dict[int, str] = {}

    story_ids = {r.story_id for r in rows}
    if story_ids:
        for s in db.query(Story).filter(Story.id.in_(story_ids)).all():
            story_titles[s.id] = s.title_bg

    fact_ids = {r.fact_id for r in rows if r.fact_id is not None}
    if fact_ids:
        for f in db.query(StoryFact).filter(StoryFact.id.in_(fact_ids)).all():
            fact_texts[f.id] = f.text_bg

    return [
        VerifLogOut(
            id=r.id,
            story_id=r.story_id,
            fact_id=r.fact_id,
            story_title=story_titles.get(r.story_id, ""),
            fact_text=fact_texts.get(r.fact_id) if r.fact_id else None,
            check=r.check,
            passed=r.passed,
            details=r.details,
            created_at=r.created_at,
        )
        for r in rows
    ]


class SourceHealth(BaseModel):
    name: str
    kind: str
    last_fetch_at: datetime | None
    stale_hours: float | None
    status: str  # "ok" | "stale" | "never_fetched"


class BudgetHealth(BaseModel):
    daily_pct: float
    monthly_pct: float


class Alarm(BaseModel):
    type: str
    message: str
    source: str | None = None
    stale_hours: float | None = None


class HealthOut(BaseModel):
    sources: list[SourceHealth]
    rejected_facts_today_pct: float
    quarantined_count: int
    budget: BudgetHealth
    alarms: list[Alarm]


class CostByDayRow(BaseModel):
    date: str
    calls: int
    cache_hits: int
    cost_usd: float


@router.get("/debug/health", response_model=HealthOut)
def get_health(db: Session = Depends(get_db)) -> HealthOut:
    daily_budget, monthly_budget = _load_budgets()
    now = datetime.now(UTC).replace(tzinfo=None)
    today_str = now.strftime("%Y-%m-%d")
    month_str = now.strftime("%Y-%m")

    cfg = _load_observability_config()
    stale_threshold_hours: float = cfg.get("stale_source_hours", 48)
    rejected_alarm_pct: float = cfg.get("rejected_facts_alarm_pct", 30)

    # Source health from most recent successful fetch_runs
    sources = db.query(Source).filter(Source.enabled.is_(True)).all()
    source_health: list[SourceHealth] = []
    alarms: list[Alarm] = []

    for src in sources:
        last_ok = (
            db.query(FetchRun)
            .filter(FetchRun.source_id == src.id, FetchRun.status == "ok")
            .order_by(FetchRun.finished_at.desc())
            .first()
        )
        if last_ok is None:
            source_health.append(SourceHealth(
                name=src.name, kind=src.kind, last_fetch_at=None,
                stale_hours=None, status="never_fetched",
            ))
            alarms.append(Alarm(
                type="stale_source",
                message=f"Няма успешен fetch за {src.name}",
                source=src.name,
                stale_hours=None,
            ))
        else:
            fetch_at = last_ok.finished_at or last_ok.started_at
            stale_hrs = (now - fetch_at).total_seconds() / 3600
            status = "stale" if stale_hrs > stale_threshold_hours else "ok"
            source_health.append(SourceHealth(
                name=src.name, kind=src.kind, last_fetch_at=fetch_at,
                stale_hours=round(stale_hrs, 1), status=status,
            ))
            if status == "stale":
                alarms.append(Alarm(
                    type="stale_source",
                    message=f"{src.name} не е обновен от {round(stale_hrs, 1)} ч.",
                    source=src.name,
                    stale_hours=round(stale_hrs, 1),
                ))

    # Rejected facts percentage today
    total_facts_today: int = db.query(func.count(VerificationLog.id)).filter(
        func.strftime("%Y-%m-%d", VerificationLog.created_at) == today_str
    ).scalar() or 0
    rejected_today: int = db.query(func.count(VerificationLog.id)).filter(
        func.strftime("%Y-%m-%d", VerificationLog.created_at) == today_str,
        VerificationLog.passed.is_(False),
    ).scalar() or 0
    rejected_pct = (rejected_today / total_facts_today * 100) if total_facts_today > 0 else 0.0

    if rejected_pct > rejected_alarm_pct:
        alarms.append(Alarm(
            type="high_rejection",
            message=f"Отхвърлени факти: {rejected_pct:.0f}% (прагът е {rejected_alarm_pct:.0f}%)",
        ))

    # Quarantine count
    quarantined: int = db.query(func.count(Article.id)).filter(
        Article.status == "quarantined"
    ).scalar() or 0

    # Budget
    today_spent: float = db.query(func.coalesce(func.sum(LlmCall.cost_usd), 0.0)).filter(
        func.strftime("%Y-%m-%d", LlmCall.created_at) == today_str
    ).scalar() or 0.0
    month_spent: float = db.query(func.coalesce(func.sum(LlmCall.cost_usd), 0.0)).filter(
        func.strftime("%Y-%m", LlmCall.created_at) == month_str
    ).scalar() or 0.0

    daily_pct = (today_spent / daily_budget * 100) if daily_budget > 0 else 0.0
    monthly_pct = (month_spent / monthly_budget * 100) if monthly_budget > 0 else 0.0

    if monthly_pct >= 100:
        alarms.append(Alarm(type="budget_exhausted", message="Месечният LLM бюджет е изчерпан"))
    elif monthly_pct >= 80:
        alarms.append(Alarm(
            type="budget_warning",
            message=f"Месечният LLM бюджет е на {monthly_pct:.0f}%",
        ))

    return HealthOut(
        sources=source_health,
        rejected_facts_today_pct=round(rejected_pct, 1),
        quarantined_count=quarantined,
        budget=BudgetHealth(daily_pct=round(daily_pct, 1), monthly_pct=round(monthly_pct, 1)),
        alarms=alarms,
    )


@router.get("/debug/cost-by-day", response_model=list[CostByDayRow])
def get_cost_by_day(days: int = 30, db: Session = Depends(get_db)) -> list[CostByDayRow]:
    now = datetime.now(UTC).replace(tzinfo=None)
    cutoff = now - timedelta(days=days)

    rows = (
        db.query(
            func.strftime("%Y-%m-%d", LlmCall.created_at).label("date"),
            func.count(LlmCall.id).label("calls"),
            func.sum(
                case((LlmCall.status == "cache_hit", 1), else_=0)
            ).label("cache_hits"),
            func.sum(LlmCall.cost_usd).label("cost_usd"),
        )
        .filter(LlmCall.created_at >= cutoff)
        .group_by(func.strftime("%Y-%m-%d", LlmCall.created_at))
        .order_by(func.strftime("%Y-%m-%d", LlmCall.created_at).desc())
        .all()
    )

    return [
        CostByDayRow(
            date=r.date,
            calls=r.calls,
            cache_hits=r.cache_hits or 0,
            cost_usd=round(r.cost_usd or 0.0, 6),
        )
        for r in rows
    ]


@router.get("/debug/costs", response_model=CostsOut)
def get_costs(db: Session = Depends(get_db)) -> CostsOut:
    now = datetime.now(UTC).replace(tzinfo=None)
    today_str = now.strftime("%Y-%m-%d")
    month_str = now.strftime("%Y-%m")

    today_usd: float = db.query(func.coalesce(func.sum(LlmCall.cost_usd), 0.0)).filter(
        func.strftime("%Y-%m-%d", LlmCall.created_at) == today_str
    ).scalar() or 0.0

    month_usd: float = db.query(func.coalesce(func.sum(LlmCall.cost_usd), 0.0)).filter(
        func.strftime("%Y-%m", LlmCall.created_at) == month_str
    ).scalar() or 0.0

    by_purpose_rows = (
        db.query(LlmCall.purpose, func.sum(LlmCall.cost_usd))
        .filter(func.strftime("%Y-%m", LlmCall.created_at) == month_str)
        .group_by(LlmCall.purpose)
        .all()
    )

    daily_budget, monthly_budget = _load_budgets()

    return CostsOut(
        today_usd=round(today_usd, 6),
        today_budget_usd=daily_budget,
        month_usd=round(month_usd, 6),
        month_budget_usd=monthly_budget,
        by_purpose=[
            PurposeCost(purpose=p, cost_usd=round(c or 0.0, 6))
            for p, c in by_purpose_rows
        ],
    )
