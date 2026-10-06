"""Tests for summarize_cluster — no real API calls."""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from app.llm.budget import BudgetExceeded, BudgetGuard
from app.llm.client import AnthropicLlmClient
from app.llm.summarize import summarize_cluster
from app.models.news import Article, ClusterMember, FactEvidence, Source, Story, StoryCluster, StoryFact
from sqlalchemy import select

_FIXTURES = Path(__file__).parent / "fixtures" / "llm"

_NOW = datetime(2026, 10, 6, 12, 0, 0)


def _fake_client(db_session, raw_payload: str) -> AnthropicLlmClient:
    guard = BudgetGuard(db_session, daily_usd=10.0, monthly_usd=100.0)
    client = AnthropicLlmClient.__new__(AnthropicLlmClient)
    client._guard = guard
    client._model = "claude-sonnet-4-6"
    client._input_cost = 3.00 / 1_000_000
    client._output_cost = 15.00 / 1_000_000
    client.call = MagicMock(return_value=raw_payload)
    return client


def _seed_cluster(db_session) -> tuple[StoryCluster, Article]:
    source = Source(name="test-source", kind="rss", is_official=False)
    db_session.add(source)
    db_session.flush()

    article = Article(
        source_id=source.id,
        title="NVDA posts record Q3 earnings",
        url="https://example.com/nvda-q3",
        canonical_url="https://example.com/nvda-q3",
        published_at=_NOW,
        fetched_at=_NOW,
        tickers_raw=["NVDA"],
        raw_payload={},
        clean_text="NVIDIA reported record Q3 earnings of $18.1B revenue.",
        status="active",
    )
    db_session.add(article)
    db_session.flush()

    cluster = StoryCluster(
        primary_ticker="NVDA",
        first_seen_at=_NOW,
        last_seen_at=_NOW,
        article_count=1,
        publisher_count=1,
        visible=True,
    )
    db_session.add(cluster)
    db_session.flush()

    db_session.add(
        ClusterMember(
            cluster_id=cluster.id,
            article_id=article.id,
            match_method="exact_hash",
            similarity=1.0,
            needs_llm_check=False,
        )
    )
    db_session.flush()
    return cluster, article


def _load_fixture_with_cluster_id(fixture_name: str, cluster_id: int, article_id: int) -> str:
    payload = json.loads((_FIXTURES / fixture_name).read_text(encoding="utf-8"))
    payload["cluster_id"] = cluster_id
    for fact in payload.get("key_facts", []):
        for ev in fact.get("evidence", []):
            if ev["article_id"] != 9999:
                ev["article_id"] = article_id
    for opinion in payload.get("attributed_opinions", []):
        for ev in opinion.get("evidence", []):
            if ev["article_id"] != 9999:
                ev["article_id"] = article_id
    return json.dumps(payload)


class TestSummarizeCluster:
    def test_valid_saves_story_and_facts(self, db_session):
        cluster, article = _seed_cluster(db_session)
        raw = _load_fixture_with_cluster_id("summarize_valid.json", cluster.id, article.id)
        client = _fake_client(db_session, raw)

        result = summarize_cluster(cluster, client, db_session)

        assert result is not None
        assert result.cluster_id == cluster.id
        assert result.verification_status == "pending"
        assert result.model_version == "claude-sonnet-4-6"
        assert result.prompt_version.startswith("summarize_v1:")
        assert result.title_bg == "NVIDIA отчете рекордни приходи за Q3"

        facts = db_session.scalars(
            select(StoryFact).where(StoryFact.story_id == result.id).order_by(StoryFact.fact_order)
        ).all()
        assert len(facts) == 2

        evidence = db_session.scalars(
            select(FactEvidence).where(FactEvidence.fact_id == facts[0].id)
        ).all()
        assert len(evidence) == 1
        assert evidence[0].quote_start is not None
        assert evidence[0].quote_start >= 0
        assert evidence[0].quote_end > evidence[0].quote_start

    def test_unknown_article_id_rejected(self, db_session):
        cluster, article = _seed_cluster(db_session)
        payload = json.loads((_FIXTURES / "summarize_unknown_article.json").read_text(encoding="utf-8"))
        payload["cluster_id"] = cluster.id
        client = _fake_client(db_session, json.dumps(payload))

        result = summarize_cluster(cluster, client, db_session)

        assert result is None
        assert db_session.scalars(select(Story)).all() == []

    def test_empty_facts_valid(self, db_session):
        cluster, article = _seed_cluster(db_session)
        payload = json.loads((_FIXTURES / "summarize_empty_facts.json").read_text(encoding="utf-8"))
        payload["cluster_id"] = cluster.id
        client = _fake_client(db_session, json.dumps(payload))

        result = summarize_cluster(cluster, client, db_session)

        assert result is not None
        facts = db_session.scalars(
            select(StoryFact).where(StoryFact.story_id == result.id)
        ).all()
        assert facts == []

    def test_cluster_id_mismatch_rejected(self, db_session):
        cluster, article = _seed_cluster(db_session)
        payload = json.loads((_FIXTURES / "summarize_valid.json").read_text(encoding="utf-8"))
        payload["cluster_id"] = cluster.id + 9999
        for fact in payload["key_facts"]:
            for ev in fact["evidence"]:
                ev["article_id"] = article.id
        client = _fake_client(db_session, json.dumps(payload))

        result = summarize_cluster(cluster, client, db_session)

        assert result is None
        assert db_session.scalars(select(Story)).all() == []

    def test_budget_exceeded_returns_none(self, db_session):
        cluster, _ = _seed_cluster(db_session)
        guard = BudgetGuard(db_session, daily_usd=10.0, monthly_usd=100.0)
        client = AnthropicLlmClient.__new__(AnthropicLlmClient)
        client._guard = guard
        client._model = "claude-sonnet-4-6"
        client._input_cost = 3.00 / 1_000_000
        client._output_cost = 15.00 / 1_000_000
        client.call = MagicMock(side_effect=BudgetExceeded("daily cap"))

        result = summarize_cluster(cluster, client, db_session)

        assert result is None
        assert db_session.scalars(select(Story)).all() == []

    def test_existing_story_skipped(self, db_session):
        cluster, _ = _seed_cluster(db_session)
        existing = Story(
            cluster_id=cluster.id,
            title_bg="Съществуваща история",
            summary_bg="Резюме.",
            tickers=["NVDA"],
            is_opinion=False,
            model_version="claude-sonnet-4-6",
            prompt_version="summarize_v1:abcd1234",
            created_at=_NOW,
        )
        db_session.add(existing)
        db_session.commit()

        guard = BudgetGuard(db_session, daily_usd=10.0, monthly_usd=100.0)
        client = AnthropicLlmClient.__new__(AnthropicLlmClient)
        client._guard = guard
        client._model = "claude-sonnet-4-6"
        client._input_cost = 3.00 / 1_000_000
        client._output_cost = 15.00 / 1_000_000
        client.call = MagicMock()

        result = summarize_cluster(cluster, client, db_session)

        assert result is not None
        assert result.id == existing.id
        client.call.assert_not_called()

    def test_opinion_in_facts_rejected(self, db_session):
        """Sprint 5: opinion in key_facts is caught by the verification pipeline."""
        from sqlalchemy import select as sa_select

        from app.models.news import VerificationLog
        from app.verification.pipeline import verify_story

        cluster, article = _seed_cluster(db_session)
        raw = _load_fixture_with_cluster_id(
            "summarize_opinion_in_facts.json", cluster.id, article.id
        )
        client = _fake_client(db_session, raw)

        # summarize_cluster saves the story (pending) — opinion is not caught here
        story = summarize_cluster(cluster, client, db_session)
        assert story is not None, "story should be saved before verification"
        assert story.verification_status == "pending"

        # verification pipeline detects the opinion marker
        result = verify_story(story, db_session, client=None)
        assert result.verification_status != "pending"

        # The fact with an analyst opinion must be caught by some verification check
        failed_logs = db_session.scalars(
            sa_select(VerificationLog)
            .where(VerificationLog.story_id == story.id)
            .where(VerificationLog.passed.is_(False))
        ).all()
        assert len(failed_logs) >= 1, "expected at least one failed check in verification log"
