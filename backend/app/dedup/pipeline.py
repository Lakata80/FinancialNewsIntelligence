from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.dedup.exact import assign_solo_clusters, find_exact_clusters
from app.dedup.minhash_dedup import DedupConfig, find_minhash_clusters
from app.models.news import Article


@dataclass
class DedupStats:
    articles_processed: int
    exact_clusters: int
    minhash_clusters: int
    solo_clusters: int
    quarantined_count: int


def run_dedup(session: Session, config: DedupConfig | None = None) -> DedupStats:
    """Run the full deduplication pipeline and return summary statistics.

    1. Exact-hash clustering (cross-publisher identical articles)
    2. MinHash near-duplicate clustering (same event, similar text)
    3. Solo cluster assignment (one article per unmatched article — ADR-028)
    """
    cfg = config or DedupConfig()

    total = session.query(Article).count()
    quarantined = session.query(Article).filter(Article.status == "quarantined").count()

    exact = find_exact_clusters(session)
    minhash = find_minhash_clusters(session, cfg)
    solo = assign_solo_clusters(session, window_hours=cfg.window_hours)

    session.commit()

    return DedupStats(
        articles_processed=total,
        exact_clusters=exact,
        minhash_clusters=minhash,
        solo_clusters=solo,
        quarantined_count=quarantined,
    )
