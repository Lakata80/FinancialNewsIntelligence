from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.news import Article, ClusterMember, StoryCluster


def find_exact_clusters(session: Session) -> int:
    """Group unassigned articles that share a content_hash into clusters.

    Returns the number of new clusters created.
    """
    # Articles that already belong to a cluster
    assigned_ids_q = select(ClusterMember.article_id)

    # Active articles with a content_hash not yet in any cluster
    stmt = (
        select(Article)
        .where(Article.content_hash.is_not(None))
        .where(Article.status == "active")
        .where(Article.id.not_in(assigned_ids_q))
        .order_by(Article.published_at)
    )
    articles = session.execute(stmt).scalars().all()

    # Group by content_hash
    groups: dict[str, list[Article]] = {}
    for article in articles:
        h = article.content_hash
        if h:
            groups.setdefault(h, []).append(article)

    new_clusters = 0
    for _, members in groups.items():
        if len(members) < 2:
            continue

        publishers = {a.publisher for a in members if a.publisher}
        tickers: list[str] = []
        for a in members:
            if isinstance(a.tickers_raw, list) and a.tickers_raw:
                tickers = a.tickers_raw
                break

        now = datetime.now(UTC).replace(tzinfo=None)
        cluster = StoryCluster(
            primary_ticker=tickers[0] if tickers else None,
            first_seen_at=min(a.published_at for a in members),
            last_seen_at=max(a.published_at for a in members),
            article_count=len(members),
            publisher_count=len(publishers),
        )
        session.add(cluster)
        session.flush()

        for article in members:
            session.add(
                ClusterMember(
                    cluster_id=cluster.id,
                    article_id=article.id,
                    match_method="exact_hash",
                    similarity=1.0,
                    needs_llm_check=False,
                )
            )

        new_clusters += 1

    return new_clusters
