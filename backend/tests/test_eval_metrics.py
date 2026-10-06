"""Unit tests for the eval harness metrics module."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from unittest.mock import MagicMock

import pytest

from tests.evals.runner.case import GoldenArticle, GoldenCase
from tests.evals.runner.metrics import (
    CaseResult,
    EvalMetrics,
    _advice_in_text,
    _quote_valid,
    compute_metrics,
    hard_targets_met,
)

_NOW = datetime(2026, 10, 6, 12, 0, 0)


def _case(id: str, category="normal", must_not: list[str] | None = None) -> GoldenCase:
    return GoldenCase(
        id=id,
        category=category,
        description="test",
        articles=[GoldenArticle(id=1, ticker="NVDA", publisher="Test", clean_text="NVDA test")],
        must_not_include=must_not or [],
    )


# ---------------------------------------------------------------------------
# _quote_valid
# ---------------------------------------------------------------------------


def test_quote_valid_exact():
    assert _quote_valid("NVIDIA reported revenue of $13.5 billion", "NVIDIA reported revenue of $13.5 billion")


def test_quote_valid_case_insensitive():
    assert _quote_valid("Revenue of $13.5 billion", "REVENUE OF $13.5 BILLION")


def test_quote_valid_missing():
    assert not _quote_valid("This quote does not appear", "Completely different text")


def test_quote_valid_empty_quote():
    assert not _quote_valid("", "some text")


def test_quote_valid_after_normalization():
    # Typographic quote should normalise
    assert _quote_valid(
        "“Surging demand”",
        '"Surging demand"',
    )


# ---------------------------------------------------------------------------
# _advice_in_text
# ---------------------------------------------------------------------------


def test_advice_bg_detected():
    assert _advice_in_text("Анализаторите препоръчват купете NVDA сега")


def test_advice_en_detected():
    assert _advice_in_text("This is a strong buy signal for NVDA")


def test_no_advice_clean():
    assert not _advice_in_text("NVIDIA reported revenue of $13.5 billion in Q2.")


# ---------------------------------------------------------------------------
# hard_targets_met
# ---------------------------------------------------------------------------


def _make_metrics(**overrides) -> EvalMetrics:
    defaults = dict(
        quote_validity_rate=1.0,
        number_grounding_rate=1.0,
        unsupported_fact_rate=0.0,
        leak_rate=0.0,
        injection_recall=0.9,
        injection_fpr=0.02,
        advice_leak=0,
        opinion_as_fact_rate=0.0,
        cost_per_story_usd=0.01,
        latency_p50_ms=2000.0,
        n_cases=10,
        n_injection_cases=2,
        n_errors=0,
    )
    defaults.update(overrides)
    return EvalMetrics(**defaults)


def test_hard_targets_all_pass():
    assert hard_targets_met(_make_metrics()) == []


def test_hard_target_quote_validity():
    m = _make_metrics(quote_validity_rate=0.95)
    failures = hard_targets_met(m)
    assert any("quote_validity" in f for f in failures)


def test_hard_target_advice_leak():
    m = _make_metrics(advice_leak=1)
    failures = hard_targets_met(m)
    assert any("advice_leak" in f for f in failures)


def test_hard_target_leak_rate():
    m = _make_metrics(leak_rate=0.05)
    failures = hard_targets_met(m)
    assert any("leak_rate" in f for f in failures)


def test_hard_target_number_grounding():
    m = _make_metrics(number_grounding_rate=0.90)
    failures = hard_targets_met(m)
    assert any("number_grounding" in f for f in failures)


# ---------------------------------------------------------------------------
# compute_metrics — smoke test with empty results
# ---------------------------------------------------------------------------


def test_compute_metrics_empty():
    m = compute_metrics([])
    assert m.quote_validity_rate == 1.0
    assert m.unsupported_fact_rate == 0.0
    assert m.leak_rate == 0.0
    assert m.advice_leak == 0
    assert m.injection_recall is None
    assert m.injection_fpr is None


def test_compute_metrics_no_injection_cases():
    result = CaseResult(case=_case("n1", "normal"), error=None)
    m = compute_metrics([result])
    assert m.injection_recall is None
    assert m.injection_fpr is not None  # non-injection cases exist → fpr is tracked


def test_compute_metrics_error_counted():
    result = CaseResult(case=_case("n1"), error="timeout")
    m = compute_metrics([result])
    assert m.n_errors == 1
