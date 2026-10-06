from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import yaml
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func
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
