from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import yaml
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import String, cast, func
from sqlalchemy.orm import Session, selectinload

from app.api.deps import get_db
from app.models.news import Article, ClusterMember, FactEvidence, Story, StoryCluster, StoryFact

router = APIRouter()

# config.yaml lives at the project root (one level above backend/)
_CONFIG_PATH = Path(__file__).parent.parent.parent.parent / "config.yaml"


class ArticleLinkOut(BaseModel):
    id: int
    title: str
    url: str
    publisher: str | None
    published_at: datetime


class EvidenceOut(BaseModel):
    id: int
    article_id: int
    quote_en: str
    publisher: str | None
    published_at: datetime
    url: str


class FactOut(BaseModel):
    id: int
    fact_order: int
    text_bg: str
    verification_status: str
    evidence: list[EvidenceOut]


class StoryOut(BaseModel):
    id: int
    cluster_id: int
    title_bg: str
    summary_bg: str
    tickers: list[str]
    event_type: str | None
    is_opinion: bool
    verification_status: str
    publisher_count: int
    article_count: int
    first_seen_at: datetime
    last_seen_at: datetime
    source_articles: list[ArticleLinkOut]


class StoryDetailOut(StoryOut):
    facts: list[FactOut]


class FunnelOut(BaseModel):
    articles: int
    clusters: int
    relevant: int


class WatchlistItem(BaseModel):
    id: str
    label: str
    kind: str  # "ticker" | "macro"


class WatchlistOut(BaseModel):
    items: list[WatchlistItem]


_MACRO_LABELS: dict[str, str] = {
    "federal_reserve": "Макро: ФЕД",
    "ecb_policy": "Макро: ЕЦБ",
    "inflation": "Макро: Инфлация",
    "interest_rates": "Макро: Лихви",
}


def _build_story_out(story: Story) -> StoryOut:
    cluster = story.cluster
    source_articles = [
        ArticleLinkOut(
            id=m.article.id,
            title=m.article.title,
            url=m.article.url,
            publisher=m.article.publisher,
            published_at=m.article.published_at,
        )
        for m in cluster.members
        if m.article.status == "active"
    ]
    return StoryOut(
        id=story.id,
        cluster_id=story.cluster_id,
        title_bg=story.title_bg,
        summary_bg=story.summary_bg,
        tickers=story.tickers or [],
        event_type=story.event_type,
        is_opinion=story.is_opinion,
        verification_status=story.verification_status,
        publisher_count=cluster.publisher_count,
        article_count=cluster.article_count,
        first_seen_at=cluster.first_seen_at,
        last_seen_at=cluster.last_seen_at,
        source_articles=source_articles,
    )


def _story_query(db: Session):
    return db.query(Story).join(StoryCluster, Story.cluster_id == StoryCluster.id).options(
        selectinload(Story.cluster)
        .selectinload(StoryCluster.members)
        .selectinload(ClusterMember.article),
    )


@router.get("/stories", response_model=list[StoryOut])
def list_stories(
    ticker: str | None = Query(None, description="Филтър по тикер"),
    hours: int = Query(24, ge=1, le=168, description="Прозорец в часове назад"),
    show_opinions: bool = Query(False, description="Включи мнения"),
    show_hidden: bool = Query(False, description="Включи скрити (промо / странични)"),
    db: Session = Depends(get_db),
) -> list[StoryOut]:
    cutoff = datetime.now(UTC).replace(tzinfo=None) - timedelta(hours=hours)
    q = _story_query(db).filter(StoryCluster.last_seen_at >= cutoff)

    if ticker:
        t = ticker.upper()
        q = q.filter(
            (StoryCluster.primary_ticker == t)
            | cast(Story.tickers, String).like(f'%"{t}"%')
        )

    if not show_opinions:
        q = q.filter(Story.is_opinion.is_(False))

    if not show_hidden:
        q = q.filter(
            StoryCluster.visible.is_(True),
            StoryCluster.is_main_subject.isnot(False),
        )

    stories = q.order_by(StoryCluster.last_seen_at.desc()).all()
    return [_build_story_out(s) for s in stories]


@router.get("/stories/{story_id}", response_model=StoryDetailOut)
def get_story(
    story_id: int,
    db: Session = Depends(get_db),
) -> StoryDetailOut:
    story = (
        db.query(Story)
        .filter(Story.id == story_id)
        .options(
            selectinload(Story.cluster)
            .selectinload(StoryCluster.members)
            .selectinload(ClusterMember.article),
            selectinload(Story.facts)
            .selectinload(StoryFact.evidence)
            .selectinload(FactEvidence.article),
        )
        .first()
    )
    if story is None:
        raise HTTPException(status_code=404, detail="Story not found")

    facts_out = [
        FactOut(
            id=f.id,
            fact_order=f.fact_order,
            text_bg=f.text_bg,
            verification_status=f.verification_status,
            evidence=[
                EvidenceOut(
                    id=e.id,
                    article_id=e.article_id,
                    quote_en=e.quote_en,
                    publisher=e.article.publisher,
                    published_at=e.article.published_at,
                    url=e.article.url,
                )
                for e in e_list
            ],
        )
        for f in sorted(story.facts, key=lambda x: x.fact_order)
        for e_list in [f.evidence]
    ]

    base = _build_story_out(story)
    return StoryDetailOut(**base.model_dump(), facts=facts_out)


@router.get("/funnel", response_model=FunnelOut)
def get_funnel(
    ticker: str | None = Query(None),
    hours: int = Query(24, ge=1, le=168),
    db: Session = Depends(get_db),
) -> FunnelOut:
    cutoff = datetime.now(UTC).replace(tzinfo=None) - timedelta(hours=hours)

    art_q = db.query(func.count(Article.id)).filter(Article.published_at >= cutoff)
    if ticker:
        t = ticker.upper()
        art_q = art_q.filter(cast(Article.tickers_raw, String).like(f'%"{t}"%'))
    articles = art_q.scalar() or 0

    cls_q = db.query(func.count(StoryCluster.id)).filter(
        StoryCluster.last_seen_at >= cutoff
    )
    if ticker:
        cls_q = cls_q.filter(StoryCluster.primary_ticker == ticker.upper())
    clusters = cls_q.scalar() or 0

    rel_q = db.query(func.count(StoryCluster.id)).filter(
        StoryCluster.last_seen_at >= cutoff,
        StoryCluster.visible.is_(True),
        StoryCluster.is_main_subject.is_(True),
    )
    if ticker:
        rel_q = rel_q.filter(StoryCluster.primary_ticker == ticker.upper())
    relevant = rel_q.scalar() or 0

    return FunnelOut(articles=articles, clusters=clusters, relevant=relevant)


@router.get("/watchlist", response_model=WatchlistOut)
def get_watchlist() -> WatchlistOut:
    try:
        with open(_CONFIG_PATH, encoding="utf-8") as fh:
            cfg = yaml.safe_load(fh) or {}
    except FileNotFoundError:
        cfg = {}

    items: list[WatchlistItem] = []
    for t in cfg.get("watchlist", {}).get("tickers", []):
        items.append(WatchlistItem(id=t, label=t, kind="ticker"))
    for theme in cfg.get("watchlist", {}).get("macro_themes", []):
        items.append(
            WatchlistItem(
                id=theme,
                label=_MACRO_LABELS.get(theme, f"Макро: {theme}"),
                kind="macro",
            )
        )
    return WatchlistOut(items=items)
