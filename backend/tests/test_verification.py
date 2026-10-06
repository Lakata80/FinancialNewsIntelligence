"""Tests for Sprint 5 verification layer — Level 1 checks + orchestrator."""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from sqlalchemy import select

from app.models.news import (
    Article,
    ClusterMember,
    FactEvidence,
    Source,
    Story,
    StoryCluster,
    StoryFact,
    VerificationLog,
)
from app.verification.checks import (
    check_entities_grounded,
    check_no_advice,
    check_numbers_grounded,
    check_opinion_placement,
    check_quote_exists,
)
from app.verification.normalizer import extract_numbers, normalize_text, number_matches_source
from app.verification.pipeline import verify_story

_FIXTURES = Path(__file__).parent / "fixtures" / "verification"
_NOW = datetime(2026, 10, 6, 12, 0, 0)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_article(session, clean_text: str, source_id: int, article_id_hint: int = 0) -> Article:
    article = Article(
        source_id=source_id,
        title="Test article",
        url=f"https://example.com/article-{article_id_hint}",
        canonical_url=f"https://example.com/article-{article_id_hint}",
        published_at=_NOW,
        fetched_at=_NOW,
        tickers_raw=[],
        raw_payload={},
        clean_text=clean_text,
        status="active",
    )
    session.add(article)
    session.flush()
    return article


def _make_fact(session, story_id: int, text_bg: str, order: int = 0) -> StoryFact:
    fact = StoryFact(story_id=story_id, fact_order=order, text_bg=text_bg)
    session.add(fact)
    session.flush()
    return fact


def _make_evidence(session, fact_id: int, article_id: int, quote_en: str) -> FactEvidence:
    ev = FactEvidence(fact_id=fact_id, article_id=article_id, quote_en=quote_en)
    session.add(ev)
    session.flush()
    return ev


def _seed_story(session, facts_data: list[dict]) -> tuple[Story, list[StoryFact]]:
    """Create a minimal story with facts+evidence from a list of dicts.

    Each dict: {"fact_text_bg", "quote_en", "article_clean_text"}
    """
    source = Source(name=f"src-{id(facts_data)}", kind="rss", is_official=False)
    session.add(source)
    session.flush()

    cluster = StoryCluster(
        primary_ticker="NVDA",
        first_seen_at=_NOW,
        last_seen_at=_NOW,
        article_count=len(facts_data),
        publisher_count=1,
        visible=True,
    )
    session.add(cluster)
    session.flush()

    story = Story(
        cluster_id=cluster.id,
        title_bg="Test story",
        summary_bg="Test summary.",
        tickers=["NVDA"],
        is_opinion=False,
        verification_status="pending",
        model_version="claude-sonnet-4-6",
        prompt_version="summarize_v1:test0000",
        created_at=_NOW,
    )
    session.add(story)
    session.flush()

    facts: list[StoryFact] = []
    for i, d in enumerate(facts_data):
        article = _make_article(
            session, d["article_clean_text"], source.id, article_id_hint=i
        )
        session.add(
            ClusterMember(
                cluster_id=cluster.id,
                article_id=article.id,
                match_method="exact_hash",
                similarity=1.0,
                needs_llm_check=False,
            )
        )
        fact = _make_fact(session, story.id, d["fact_text_bg"], order=i)
        _make_evidence(session, fact.id, article.id, d["quote_en"])
        facts.append(fact)

    session.flush()
    return story, facts


# ---------------------------------------------------------------------------
# normalizer tests
# ---------------------------------------------------------------------------


class TestNormalizer:
    def test_normalize_text_collapses_whitespace(self):
        assert normalize_text("hello   world") == "hello world"

    def test_normalize_text_typographic_quotes(self):
        result = normalize_text("“hello”")
        assert '"' in result or "'" in result  # converted to ASCII

    def test_extract_numbers_percentage(self):
        numbers = extract_numbers("Приходите нараснаха с 12%.")
        assert (12.0, "%") in numbers

    def test_extract_numbers_milliards_dollars(self):
        numbers = extract_numbers("Приходите са 3,5 млрд. долара.")
        assert any(abs(v - 3.5e9) < 1 and u == "usd" for v, u in numbers)

    def test_extract_numbers_quarter(self):
        numbers = extract_numbers("резултати за Q3 2026")
        assert (3.0, "quarter") in numbers

    def test_extract_numbers_bg_quarter_word(self):
        numbers = extract_numbers("резултати за третото тримесечие")
        assert (3.0, "quarter") in numbers

    def test_number_matches_source_format_cross(self):
        # "3,5 млрд. долара" ↔ "$3.5 billion"
        assert number_matches_source(3.5e9, "usd", "revenue of $3.5 billion this quarter")

    def test_number_matches_source_percentage(self):
        assert number_matches_source(12.0, "%", "revenue grew 12% year-over-year")

    def test_number_matches_source_no_match(self):
        assert not number_matches_source(21.0, "%", "revenue grew 12% year-over-year")

    def test_number_matches_source_18_1B(self):
        assert number_matches_source(18.1e9, "usd", "NVIDIA reported $18.1B revenue")


# ---------------------------------------------------------------------------
# Level 1 check unit tests
# ---------------------------------------------------------------------------


def _stub_fact(text_bg: str) -> SimpleNamespace:
    return SimpleNamespace(text_bg=text_bg)


def _stub_ev(article_id: int, quote_en: str) -> SimpleNamespace:
    return SimpleNamespace(article_id=article_id, quote_en=quote_en)


def _stub_art(clean_text: str) -> SimpleNamespace:
    return SimpleNamespace(clean_text=clean_text, summary_raw=None, title=None)


class TestCheckNoAdvice:
    def test_clean_text_passes(self):
        r = check_no_advice(_stub_fact("NVIDIA отчете приходи от $18.1B."))
        assert r.passed

    def test_bulgarian_buy_phrase_fails(self):
        r = check_no_advice(_stub_fact("Акциите са добра възможност за покупка."))
        assert not r.passed
        assert "no_advice" in r.details

    def test_bulgarian_sell_phrase_fails(self):
        r = check_no_advice(_stub_fact("Препоръчваме продажба на позицията."))
        assert not r.passed

    def test_english_strong_buy_fails(self):
        r = check_no_advice(_stub_fact("Анализаторите дадоха strong buy рейтинг."))
        assert not r.passed


class TestCheckQuoteExists:
    def test_exact_quote_passes(self):
        fact = _stub_fact("NVIDIA отчете Q3 приходи.")
        ev = _stub_ev(1, "NVIDIA reported record Q3 earnings")
        art = _stub_art("NVIDIA reported record Q3 earnings of $18.1B revenue.")
        r = check_quote_exists(fact, [ev], {1: art})
        assert r.passed

    def test_fabricated_quote_fails(self):
        fixture = json.loads((_FIXTURES / "fact_fabricated_quote.json").read_text(encoding="utf-8"))
        fact = _stub_fact(fixture["fact_text_bg"])
        ev = _stub_ev(1, fixture["quote_en"])
        art = _stub_art(fixture["article_clean_text"])
        r = check_quote_exists(fact, [ev], {1: art})
        assert not r.passed
        assert "quote_exists" in r.details

    def test_normalisation_whitespace_passes(self):
        fact = _stub_fact("test")
        ev = _stub_ev(1, "revenue  grew  12%")  # extra spaces
        art = _stub_art("revenue grew 12% year-over-year")
        r = check_quote_exists(fact, [ev], {1: art})
        assert r.passed


class TestCheckNumbersGrounded:
    def test_correct_number_passes(self):
        fixture = json.loads((_FIXTURES / "story_all_pass.json").read_text(encoding="utf-8"))
        fd = fixture["facts"][0]
        fact = _stub_fact(fd["fact_text_bg"])
        ev = _stub_ev(1, fd["quote_en"])
        art = _stub_art(fd["article_clean_text"])
        r = check_numbers_grounded(fact, [ev], {1: art})
        assert r.passed

    def test_wrong_number_fails(self):
        fixture = json.loads((_FIXTURES / "fact_wrong_number.json").read_text(encoding="utf-8"))
        fact = _stub_fact(fixture["fact_text_bg"])
        ev = _stub_ev(1, fixture["quote_en"])
        art = _stub_art(fixture["article_clean_text"])
        r = check_numbers_grounded(fact, [ev], {1: art})
        assert not r.passed
        assert "numbers_grounded" in r.details

    def test_cross_format_normalisation_passes(self):
        fixture = json.loads((_FIXTURES / "fact_number_format.json").read_text(encoding="utf-8"))
        fact = _stub_fact(fixture["fact_text_bg"])
        ev = _stub_ev(1, fixture["quote_en"])
        art = _stub_art(fixture["article_clean_text"])
        r = check_numbers_grounded(fact, [ev], {1: art})
        assert r.passed, f"Expected pass but got: {r.details}"

    def test_no_numbers_passes(self):
        fact = _stub_fact("NVIDIA обяви нов продукт.")
        r = check_numbers_grounded(fact, [], {})
        assert r.passed


class TestCheckOpinionPlacement:
    def test_factual_text_passes(self):
        fact = _stub_fact("NVIDIA отчете $18.1B приходи.")
        ev = _stub_ev(1, "NVIDIA reported $18.1B revenue")
        r = check_opinion_placement(fact, [ev])
        assert r.passed

    def test_analyst_in_text_bg_flags(self):
        fixture = json.loads((_FIXTURES / "fact_opinion_in_facts.json").read_text(encoding="utf-8"))
        fact = _stub_fact(fixture["fact_text_bg"])
        ev = _stub_ev(1, fixture["quote_en"])
        r = check_opinion_placement(fact, [ev])
        assert not r.passed
        assert "opinion_placement" in r.details

    def test_analyst_in_quote_flags(self):
        fact = _stub_fact("Целевата цена е повишена.")
        ev = _stub_ev(1, "analyst raises price target to $180")
        r = check_opinion_placement(fact, [ev])
        assert not r.passed


# ---------------------------------------------------------------------------
# Orchestrator integration tests
# ---------------------------------------------------------------------------


class TestVerifyStory:
    def test_all_pass_story_verified(self, db_session):
        fixture = json.loads((_FIXTURES / "story_all_pass.json").read_text(encoding="utf-8"))
        story, facts = _seed_story(db_session, fixture["facts"])

        result = verify_story(story, db_session, client=None)

        assert result.verification_status == "verified"
        db_session.refresh(facts[0])
        db_session.refresh(facts[1])
        assert facts[0].verification_status == "verified"
        assert facts[1].verification_status == "verified"

    def test_fabricated_quote_removes_fact(self, db_session):
        fixture = json.loads((_FIXTURES / "fact_fabricated_quote.json").read_text(encoding="utf-8"))
        # One bad fact + one good fact → partial
        good = {
            "fact_text_bg": "NVIDIA обяви резултати.",
            "quote_en": "NVIDIA reported record Q3 earnings",
            "article_clean_text": "NVIDIA reported record Q3 earnings of $18.1B.",
        }
        story, facts = _seed_story(db_session, [
            {
                "fact_text_bg": fixture["fact_text_bg"],
                "quote_en": fixture["quote_en"],
                "article_clean_text": fixture["article_clean_text"],
            },
            good,
        ])

        result = verify_story(story, db_session, client=None)

        assert result.verification_status == "partial"
        db_session.refresh(facts[0])
        db_session.refresh(facts[1])
        assert facts[0].verification_status == "removed"
        assert facts[1].verification_status == "verified"

    def test_no_advice_removes_fact(self, db_session):
        fixture = json.loads((_FIXTURES / "fact_advice_bg.json").read_text(encoding="utf-8"))
        story, facts = _seed_story(db_session, [
            {
                "fact_text_bg": fixture["fact_text_bg"],
                "quote_en": fixture["quote_en"],
                "article_clean_text": fixture["article_clean_text"],
            }
        ])

        result = verify_story(story, db_session, client=None)

        assert result.verification_status == "unverified"
        db_session.refresh(facts[0])
        assert facts[0].verification_status == "removed"

    def test_all_facts_removed_gives_unverified(self, db_session):
        fixture = json.loads((_FIXTURES / "fact_fabricated_quote.json").read_text(encoding="utf-8"))
        story, facts = _seed_story(db_session, [
            {
                "fact_text_bg": fixture["fact_text_bg"],
                "quote_en": fixture["quote_en"],
                "article_clean_text": fixture["article_clean_text"],
            }
        ])

        result = verify_story(story, db_session, client=None)

        assert result.verification_status == "unverified"

    def test_verification_log_populated(self, db_session):
        fixture = json.loads((_FIXTURES / "story_all_pass.json").read_text(encoding="utf-8"))
        story, _ = _seed_story(db_session, fixture["facts"])

        verify_story(story, db_session, client=None)

        logs = db_session.scalars(
            select(VerificationLog).where(VerificationLog.story_id == story.id)
        ).all()
        assert len(logs) > 0
        check_names = {log.check for log in logs}
        assert "quote_exists" in check_names

    def test_opinion_placement_flags_without_level2(self, db_session):
        """opinion_placement flags the fact; without a client it stays pending."""
        fixture = json.loads((_FIXTURES / "fact_opinion_in_facts.json").read_text(encoding="utf-8"))
        story, facts = _seed_story(db_session, [
            {
                "fact_text_bg": fixture["fact_text_bg"],
                "quote_en": fixture["quote_en"],
                "article_clean_text": fixture["article_clean_text"],
            }
        ])

        verify_story(story, db_session, client=None)

        logs = db_session.scalars(
            select(VerificationLog)
            .where(VerificationLog.story_id == story.id)
            .where(VerificationLog.check == "opinion_placement")
        ).all()
        assert len(logs) == 1
        assert not logs[0].passed

    def test_empty_story_verified(self, db_session):
        """A story with no facts at all gets verification_status='verified'."""
        source = Source(name="empty-src", kind="rss", is_official=False)
        db_session.add(source)
        db_session.flush()
        cluster = StoryCluster(
            primary_ticker="AAPL",
            first_seen_at=_NOW,
            last_seen_at=_NOW,
            article_count=0,
            publisher_count=0,
            visible=True,
        )
        db_session.add(cluster)
        db_session.flush()
        story = Story(
            cluster_id=cluster.id,
            title_bg="Empty story",
            summary_bg="No facts.",
            tickers=[],
            is_opinion=False,
            verification_status="pending",
            model_version="claude-sonnet-4-6",
            prompt_version="summarize_v1:test0000",
            created_at=_NOW,
        )
        db_session.add(story)
        db_session.flush()

        result = verify_story(story, db_session, client=None)

        assert result.verification_status == "verified"
