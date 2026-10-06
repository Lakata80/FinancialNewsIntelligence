from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.db import Base
from app.dedup.sec_corroboration import run_sec_corroboration
from app.models.news import Article, ClusterMember, Source, StoryCluster


@pytest.fixture
def session():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    S = sessionmaker(bind=engine)
    with S() as s:
        yield s
    Base.metadata.drop_all(engine)


def _make_source(session, name: str, kind: str = "api", is_official: bool = False) -> Source:
    src = Source(name=name, kind=kind, is_official=is_official, enabled=True)
    session.add(src)
    session.flush()
    return src


def _make_article(
    session,
    source: Source,
    ticker: str,
    title: str,
    published_at: datetime,
    sec_form_type: str | None = None,
    sec_items: list | None = None,
    event_type_hint: str = "earnings",
    publisher: str = "Reuters",
) -> Article:
    raw_payload: dict = {}
    if sec_form_type:
        raw_payload = {
            "sec_form_type": sec_form_type,
            "sec_items": sec_items or [],
            "event_type_hint": event_type_hint,
        }
    article = Article(
        source_id=source.id,
        publisher=publisher,
        title=title,
        url=f"https://example.com/{title.replace(' ', '_')}",
        canonical_url=f"https://example.com/{title.replace(' ', '_')}",
        published_at=published_at,
        fetched_at=published_at,
        tickers_raw=[ticker],
        content_hash=f"hash_{title}",
        raw_payload=raw_payload,
        clean_text=title,
        status="active",
        sec_form_type=sec_form_type,
        sec_items=sec_items,
    )
    session.add(article)
    session.flush()
    return article


def _make_media_cluster(
    session, ticker: str, published_at: datetime, event_type: str, articles: list[Article]
) -> StoryCluster:
    cluster = StoryCluster(
        primary_ticker=ticker,
        first_seen_at=published_at,
        last_seen_at=published_at,
        article_count=len(articles),
        publisher_count=len(articles),
        event_type=event_type,
        visible=True,
        has_primary_source=False,
    )
    session.add(cluster)
    session.flush()
    for article in articles:
        session.add(ClusterMember(
            cluster_id=cluster.id,
            article_id=article.id,
            match_method="minhash",
            similarity=0.9,
            needs_llm_check=False,
        ))
    session.flush()
    return cluster


# ── Test 1: 8-K item 2.02 + 3 media articles → corroboration ──────────────

def test_8k_earnings_corroborates_media_cluster(session):
    media_src = _make_source(session, "yahoo_rss", kind="rss")
    sec_src = _make_source(session, "sec_edgar", kind="primary", is_official=True)

    pub_date = datetime(2024, 8, 28)
    a1 = _make_article(session, media_src, "NVDA", "NVIDIA Q2 results beat estimates", pub_date)
    a2 = _make_article(session, media_src, "NVDA", "NVDA reports record Q2 revenue", pub_date)
    a3 = _make_article(session, media_src, "NVDA", "Nvidia crushes Q2 expectations", pub_date)
    cluster = _make_media_cluster(session, "NVDA", pub_date, "earnings", [a1, a2, a3])

    sec_article = _make_article(
        session, sec_src, "NVDA", "8-K NVDA — Results of Operations",
        pub_date, sec_form_type="8-K", sec_items=["2.02", "9.01"], event_type_hint="earnings",
        publisher="SEC EDGAR",
    )
    session.commit()

    result = run_sec_corroboration(session, window_hours=48)

    assert result.new_corroborations == 1
    assert result.standalone_sec == 0

    session.expire_all()
    updated_cluster = session.get(StoryCluster, cluster.id)
    assert updated_cluster.has_primary_source is True
    assert updated_cluster.sec_filing_url is not None

    sec_member = session.query(ClusterMember).filter_by(
        article_id=sec_article.id, match_method="sec_corroboration"
    ).first()
    assert sec_member is not None


# ── Test 2: 8-K without media coverage → standalone cluster ───────────────

def test_8k_without_media_creates_standalone_cluster(session):
    sec_src = _make_source(session, "sec_edgar", kind="primary", is_official=True)

    pub_date = datetime(2024, 8, 28)
    sec_article = _make_article(
        session, sec_src, "NVDA", "8-K NVDA — Changes in Directors or Officers",
        pub_date, sec_form_type="8-K", sec_items=["5.02", "9.01"], event_type_hint="executive_change",
        publisher="SEC EDGAR",
    )
    session.commit()

    result = run_sec_corroboration(session, window_hours=48)

    assert result.standalone_sec == 1
    assert result.new_corroborations == 0

    # A new cluster must have been created
    clusters = session.query(StoryCluster).all()
    assert len(clusters) == 1
    assert clusters[0].has_primary_source is True
    assert clusters[0].primary_ticker == "NVDA"
    assert clusters[0].event_type == "executive_change"


# ── Test 3: media cluster with no SEC filing → has_primary_source stays False ──

def test_media_cluster_without_sec_remains_unmatched(session):
    media_src = _make_source(session, "yahoo_rss", kind="rss")

    pub_date = datetime(2024, 8, 28)
    a1 = _make_article(session, media_src, "NVDA", "NVIDIA announces earnings", pub_date)
    cluster = _make_media_cluster(session, "NVDA", pub_date, "earnings", [a1])
    session.commit()

    result = run_sec_corroboration(session, window_hours=48)

    assert result.new_corroborations == 0
    assert result.standalone_sec == 0

    session.expire_all()
    assert cluster.has_primary_source is False


# ── Test 4: LLM check for uncertain match — LLM rejects → standalone ──────

def test_uncertain_match_llm_rejects_creates_standalone(session):
    media_src = _make_source(session, "yahoo_rss", kind="rss")
    sec_src = _make_source(session, "sec_edgar", kind="primary", is_official=True)

    pub_date = datetime(2024, 8, 28)
    a1 = _make_article(session, media_src, "NVDA", "NVDA general news", pub_date)
    _make_media_cluster(session, "NVDA", pub_date, "other", [a1])

    sec_article = _make_article(
        session, sec_src, "NVDA", "8-K NVDA — Other Events",
        pub_date, sec_form_type="8-K", sec_items=["8.01"], event_type_hint="other",
        publisher="SEC EDGAR",
    )
    session.commit()

    mock_client = MagicMock()
    mock_client.call.return_value = '{"matches": false, "confidence": 0.3, "rationale_en": "No match"}'

    result = run_sec_corroboration(session, window_hours=48, llm_client=mock_client)

    assert result.standalone_sec == 1
    assert result.new_corroborations == 0
    assert result.llm_checks >= 1


# ── Test 5: LLM check for uncertain match — LLM confirms → corroboration ──

def test_uncertain_match_llm_confirms_corroboration(session):
    media_src = _make_source(session, "yahoo_rss", kind="rss")
    sec_src = _make_source(session, "sec_edgar", kind="primary", is_official=True)

    pub_date = datetime(2024, 8, 28)
    a1 = _make_article(session, media_src, "NVDA", "NVDA regulatory filing news", pub_date)
    cluster = _make_media_cluster(session, "NVDA", pub_date, "other", [a1])

    _make_article(
        session, sec_src, "NVDA", "8-K NVDA — Other Events",
        pub_date, sec_form_type="8-K", sec_items=["8.01"], event_type_hint="other",
        publisher="SEC EDGAR",
    )
    session.commit()

    mock_client = MagicMock()
    mock_client.call.return_value = '{"matches": true, "confidence": 0.85, "rationale_en": "Same event"}'

    result = run_sec_corroboration(session, window_hours=48, confidence_threshold=0.7, llm_client=mock_client)

    assert result.new_corroborations == 1
    assert result.llm_matches == 1

    session.expire_all()
    assert cluster.has_primary_source is True


# ── Test 6: idempotency — running twice does not duplicate ─────────────────

def test_corroboration_is_idempotent(session):
    media_src = _make_source(session, "yahoo_rss", kind="rss")
    sec_src = _make_source(session, "sec_edgar", kind="primary", is_official=True)

    pub_date = datetime(2024, 8, 28)
    a1 = _make_article(session, media_src, "NVDA", "NVDA Q2 earnings beat", pub_date)
    _make_media_cluster(session, "NVDA", pub_date, "earnings", [a1])
    _make_article(
        session, sec_src, "NVDA", "8-K NVDA — Results of Operations",
        pub_date, sec_form_type="8-K", sec_items=["2.02"], event_type_hint="earnings",
        publisher="SEC EDGAR",
    )
    session.commit()

    run_sec_corroboration(session, window_hours=48)
    result2 = run_sec_corroboration(session, window_hours=48)

    assert result2.new_corroborations == 0
    assert result2.standalone_sec == 0


# ── Test 7: filing outside time window → standalone ───────────────────────

def test_filing_outside_window_creates_standalone(session):
    media_src = _make_source(session, "yahoo_rss", kind="rss")
    sec_src = _make_source(session, "sec_edgar", kind="primary", is_official=True)

    media_date = datetime(2024, 8, 1)
    sec_date = datetime(2024, 9, 1)  # 31 days apart, outside 48h window

    a1 = _make_article(session, media_src, "NVDA", "NVDA Q1 earnings beat", media_date)
    _make_media_cluster(session, "NVDA", media_date, "earnings", [a1])
    _make_article(
        session, sec_src, "NVDA", "8-K NVDA — Results of Operations",
        sec_date, sec_form_type="8-K", sec_items=["2.02"], event_type_hint="earnings",
        publisher="SEC EDGAR",
    )
    session.commit()

    result = run_sec_corroboration(session, window_hours=48)

    assert result.standalone_sec == 1
    assert result.new_corroborations == 0
