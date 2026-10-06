from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from datasketch import MinHash, MinHashLSH
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.news import Article, ClusterMember, StoryCluster

_WORD_RE = re.compile(r"[a-z0-9]+")
_NUM_PERM = 128


@dataclass
class DedupConfig:
    lower_threshold: float = 0.5
    upper_threshold: float = 0.8
    window_hours: int = 48


def _tokenize(text: str) -> list[str]:
    return _WORD_RE.findall(text.lower())


def _make_minhash(tokens: list[str]) -> MinHash:
    mh = MinHash(num_perm=_NUM_PERM)
    for token in tokens:
        mh.update(token.encode())
    return mh


def find_minhash_clusters(session: Session, config: DedupConfig) -> int:
    """Find near-duplicate articles using MinHash within the time window.

    Only considers active, unassigned articles that share at least one ticker
    (or belong to no specific ticker for macro-theme content).

    Returns the number of new clusters created.
    """
    assigned_ids_q = select(ClusterMember.article_id)

    cutoff = datetime.now(UTC).replace(tzinfo=None) - timedelta(
        hours=config.window_hours
    )
    stmt = (
        select(Article)
        .where(Article.status == "active")
        .where(Article.published_at >= cutoff)
        .where(Article.id.not_in(assigned_ids_q))
        .order_by(Article.published_at)
    )
    articles = session.execute(stmt).scalars().all()

    if not articles:
        return 0

    # Group articles by ticker so we only compare within the same topic
    ticker_groups: dict[str, list[Article]] = {}
    for article in articles:
        tickers: list[str] = article.tickers_raw if isinstance(article.tickers_raw, list) else []
        if tickers:
            for ticker in tickers:
                ticker_groups.setdefault(ticker, []).append(article)
        else:
            ticker_groups.setdefault("__macro__", []).append(article)

    new_clusters = 0

    for ticker, group in ticker_groups.items():
        if len(group) < 2:
            continue

        # Build MinHashes
        minhashes: dict[int, MinHash] = {}
        for article in group:
            combined = article.title + " " + (article.clean_text or article.summary_raw or "")
            tokens = _tokenize(combined)
            if tokens:
                minhashes[article.id] = _make_minhash(tokens)

        if len(minhashes) < 2:
            continue

        # Use LSH for efficient near-duplicate search at lower_threshold
        lsh = MinHashLSH(threshold=config.lower_threshold, num_perm=_NUM_PERM)
        art_by_id = {a.id: a for a in group}

        for art_id, mh in minhashes.items():
            lsh.insert(str(art_id), mh)

        # Find pairs above lower_threshold; avoid double-counting
        seen_pairs: set[frozenset[int]] = set()
        pairs_above: list[tuple[int, int, float]] = []

        for art_id, mh in minhashes.items():
            candidates = lsh.query(mh)
            for cand_key in candidates:
                cand_id = int(cand_key)
                if cand_id == art_id:
                    continue
                pair = frozenset([art_id, cand_id])
                if pair in seen_pairs:
                    continue
                seen_pairs.add(pair)
                sim = minhashes[art_id].jaccard(minhashes[cand_id])
                if sim >= config.lower_threshold:
                    pairs_above.append((art_id, cand_id, sim))

        # Build clusters greedily from pairs
        # Articles already assigned to a cluster in this ticker run
        clustered: dict[int, int] = {}  # article_id -> cluster_id (local)
        local_clusters: list[tuple[list[int], bool]] = []  # (members, needs_llm_check)

        for id_a, id_b, sim in pairs_above:
            needs_check = sim < config.upper_threshold
            ca = clustered.get(id_a)
            cb = clustered.get(id_b)

            if ca is None and cb is None:
                idx = len(local_clusters)
                local_clusters.append(([id_a, id_b], needs_check))
                clustered[id_a] = idx
                clustered[id_b] = idx
            elif ca is not None and cb is None:
                local_clusters[ca][0].append(id_b)
                if needs_check:
                    local_clusters[ca] = (local_clusters[ca][0], True)
                clustered[id_b] = ca
            elif ca is None and cb is not None:
                local_clusters[cb][0].append(id_a)
                if needs_check:
                    local_clusters[cb] = (local_clusters[cb][0], True)
                clustered[id_a] = cb
            # Both already in same cluster — nothing to do

        for member_ids, needs_check in local_clusters:
            members = [art_by_id[aid] for aid in member_ids if aid in art_by_id]
            if len(members) < 2:
                continue
            publishers = {a.publisher for a in members if a.publisher}
            primary = ticker if ticker != "__macro__" else None
            cluster = StoryCluster(
                primary_ticker=primary,
                first_seen_at=min(a.published_at for a in members),
                last_seen_at=max(a.published_at for a in members),
                article_count=len(members),
                publisher_count=len(publishers),
            )
            session.add(cluster)
            session.flush()

            for art_id in member_ids:
                art = art_by_id.get(art_id)
                if art is None:
                    continue
                other_ids = [i for i in member_ids if i != art_id]
                sim = (
                    minhashes[art_id].jaccard(minhashes[other_ids[0]])
                    if other_ids and art_id in minhashes and other_ids[0] in minhashes
                    else 0.0
                )
                session.add(
                    ClusterMember(
                        cluster_id=cluster.id,
                        article_id=art_id,
                        match_method="minhash",
                        similarity=sim,
                        needs_llm_check=needs_check,
                    )
                )

            new_clusters += 1

    return new_clusters
