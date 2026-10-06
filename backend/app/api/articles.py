from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import String, cast
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.models.news import Article

router = APIRouter()


class ArticleOut(BaseModel):
    id: int
    source_id: int
    publisher: str | None
    title: str
    summary_raw: str | None
    url: str
    canonical_url: str
    published_at: datetime
    fetched_at: datetime
    tickers_raw: Any

    model_config = {"from_attributes": True}


@router.get("/health")
async def health():
    return {"status": "ok"}


@router.get("/articles", response_model=list[ArticleOut])
def list_articles(
    ticker: str | None = Query(None, description="Филтър по тикер"),
    hours: int = Query(24, ge=1, le=168, description="Прозорец в часове назад"),
    db: Session = Depends(get_db),
) -> list[Article]:
    cutoff = datetime.now(UTC).replace(tzinfo=None) - timedelta(hours=hours)
    q = db.query(Article).filter(Article.published_at >= cutoff)
    if ticker:
        # Cast JSON column to text and LIKE-match the quoted ticker token.
        # e.g. ["NVDA","MSFT"] → LIKE '%"NVDA"%' — avoids substring false positives.
        # Proper json_each() query is Sprint 2 (see DECISIONS.md ADR-006).
        q = q.filter(cast(Article.tickers_raw, String).like(f'%"{ticker.upper()}"%'))
    return q.order_by(Article.published_at.desc()).all()
