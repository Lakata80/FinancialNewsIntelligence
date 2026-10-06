"""Tests for BudgetGuard — no API calls."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.llm.budget import BudgetExceeded, BudgetGuard
from app.models.news import LlmCall


def _make_call(cost: float, created_at: datetime) -> LlmCall:
    return LlmCall(
        purpose="classify",
        model="claude-haiku-4-5",
        prompt_version="classify_v1:test",
        input_tokens=100,
        output_tokens=20,
        cost_usd=cost,
        latency_ms=500,
        status="ok",
        created_at=created_at,
    )


def test_no_spend_allows_call(db_session):
    guard = BudgetGuard(db_session, daily_usd=0.5, monthly_usd=10.0)
    guard.check()  # must not raise


def test_daily_cap_exceeded(db_session):
    today = datetime.now(timezone.utc).replace(tzinfo=None)
    db_session.add(_make_call(0.5, today))
    db_session.commit()

    guard = BudgetGuard(db_session, daily_usd=0.5, monthly_usd=10.0)
    with pytest.raises(BudgetExceeded, match="Daily"):
        guard.check()


def test_daily_cap_just_below_limit_allowed(db_session):
    today = datetime.now(timezone.utc).replace(tzinfo=None)
    db_session.add(_make_call(0.499, today))
    db_session.commit()

    guard = BudgetGuard(db_session, daily_usd=0.5, monthly_usd=10.0)
    guard.check()  # must not raise


def test_monthly_cap_exceeded(db_session):
    # 11 calls of $1 each in the same month
    for day in range(1, 12):
        db_session.add(_make_call(1.0, datetime(2026, 10, day, 12, 0, 0)))
    db_session.commit()

    guard = BudgetGuard(db_session, daily_usd=999.0, monthly_usd=10.0)
    with pytest.raises(BudgetExceeded, match="Monthly"):
        guard.check()


def test_previous_month_spend_ignored(db_session):
    # Spend from September does not count toward October
    db_session.add(_make_call(0.49, datetime(2026, 9, 30, 23, 59, 59)))
    db_session.commit()

    guard = BudgetGuard(db_session, daily_usd=0.5, monthly_usd=0.5)
    guard.check()  # must not raise — September spend is excluded


def test_previous_day_spend_ignored(db_session):
    yesterday = datetime(2026, 10, 4, 23, 59, 59)
    db_session.add(_make_call(1.0, yesterday))
    db_session.commit()

    guard = BudgetGuard(db_session, daily_usd=0.5, monthly_usd=999.0)
    # Yesterday's spend exceeds daily cap but is a different calendar day
    guard.check()  # must not raise
