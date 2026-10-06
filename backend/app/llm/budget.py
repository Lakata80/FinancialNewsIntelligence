from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.news import LlmCall


class BudgetExceeded(Exception):
    """Raised when the daily or monthly LLM spend cap is reached."""


class BudgetGuard:
    """Enforces calendar-day and calendar-month LLM spend caps.

    Both caps are checked against the SUM of cost_usd in llm_calls for
    the current UTC calendar day and calendar month respectively.
    """

    def __init__(
        self,
        session: Session,
        daily_usd: float,
        monthly_usd: float,
    ) -> None:
        self._session = session
        self._daily_usd = daily_usd
        self._monthly_usd = monthly_usd

    @property
    def session(self) -> Session:
        return self._session

    def check(self) -> None:
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        today_str = now.strftime("%Y-%m-%d")
        month_str = now.strftime("%Y-%m")

        daily_stmt = select(
            func.coalesce(func.sum(LlmCall.cost_usd), 0.0)
        ).where(func.strftime("%Y-%m-%d", LlmCall.created_at) == today_str)
        daily_spent: float = self._session.scalar(daily_stmt) or 0.0

        if daily_spent >= self._daily_usd:
            raise BudgetExceeded(
                f"Daily LLM budget exhausted: ${daily_spent:.4f} >= ${self._daily_usd}"
            )

        monthly_stmt = select(
            func.coalesce(func.sum(LlmCall.cost_usd), 0.0)
        ).where(func.strftime("%Y-%m", LlmCall.created_at) == month_str)
        monthly_spent: float = self._session.scalar(monthly_stmt) or 0.0

        if monthly_spent >= self._monthly_usd:
            raise BudgetExceeded(
                f"Monthly LLM budget exhausted: ${monthly_spent:.4f} >= ${self._monthly_usd}"
            )
