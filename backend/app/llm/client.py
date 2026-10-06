from __future__ import annotations

import hashlib
import json
import time
from datetime import datetime, timezone

import anthropic
from sqlalchemy import select

from app.llm.budget import BudgetExceeded, BudgetGuard
from app.models.news import LlmCall, LlmResponseCache

HAIKU_INPUT_COST = 1.00 / 1_000_000    # USD per input token
HAIKU_OUTPUT_COST = 5.00 / 1_000_000   # USD per output token
SONNET_INPUT_COST = 3.00 / 1_000_000   # USD per input token
SONNET_OUTPUT_COST = 15.00 / 1_000_000 # USD per output token


class AnthropicLlmClient:
    """Thin wrapper over the Anthropic SDK with budget enforcement and audit logging.

    Every call is logged to llm_calls. On JSON parse failure one retry is
    attempted with error feedback in the user message. A second parse failure
    raises ValueError — the caller must reject, never repair (CLAUDE.md Rule g).

    No tools are ever passed to the API (CLAUDE.md Rule e).
    """

    def __init__(
        self,
        api_key: str,
        model: str,
        guard: BudgetGuard,
        input_cost_per_token: float = HAIKU_INPUT_COST,
        output_cost_per_token: float = HAIKU_OUTPUT_COST,
        cache_ttl_days: int = -1,
    ) -> None:
        self._sdk = anthropic.Anthropic(api_key=api_key)
        self._model = model
        self._guard = guard
        self._input_cost = input_cost_per_token
        self._output_cost = output_cost_per_token
        self._cache_ttl_days = cache_ttl_days

    def _cache_key(self, prompt_version: str, user: str) -> str:
        raw = f"{prompt_version}:{self._model}:{user}"
        return hashlib.sha256(raw.encode()).hexdigest()[:32]

    def _get_cached(self, cache_key: str) -> LlmResponseCache | None:
        entry = self._guard.session.scalar(
            select(LlmResponseCache).where(LlmResponseCache.cache_key == cache_key)
        )
        if entry is None:
            return None
        if self._cache_ttl_days != -1:
            age_days = (datetime.now(timezone.utc).replace(tzinfo=None) - entry.created_at).days
            if age_days >= self._cache_ttl_days:
                return None
        return entry

    def _store_cache(
        self,
        cache_key: str,
        purpose: str,
        prompt_version: str,
        response_text: str,
        input_tokens: int,
        output_tokens: int,
    ) -> None:
        existing = self._guard.session.scalar(
            select(LlmResponseCache).where(LlmResponseCache.cache_key == cache_key)
        )
        if existing is not None:
            existing.response_text = response_text
            existing.input_tokens = input_tokens
            existing.output_tokens = output_tokens
            existing.created_at = datetime.now(timezone.utc).replace(tzinfo=None)
            existing.last_hit_at = None
        else:
            self._guard.session.add(LlmResponseCache(
                cache_key=cache_key,
                purpose=purpose,
                model=self._model,
                prompt_version=prompt_version,
                response_text=response_text,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                hit_count=0,
                created_at=datetime.now(timezone.utc).replace(tzinfo=None),
            ))
        self._guard.session.flush()

    def call(
        self,
        *,
        system: str,
        user: str,
        purpose: str,
        prompt_version: str,
        max_tokens: int = 1024,
    ) -> str:
        """Make one LLM call, with one JSON-retry on parse failure.

        Checks DB cache first (ADR-026). Cache hits are logged with cost_usd=0.

        Raises:
            BudgetExceeded: if the daily or monthly cap is reached.
            ValueError: if the LLM returns invalid JSON on both attempts.
        """
        cache_key = self._cache_key(prompt_version, user)
        cached = self._get_cached(cache_key)
        if cached is not None:
            cached.hit_count += 1
            cached.last_hit_at = datetime.now(timezone.utc).replace(tzinfo=None)
            self._log_call(
                purpose=purpose,
                prompt_version=prompt_version,
                input_tokens=0,
                output_tokens=0,
                cost=0.0,
                latency_ms=0,
                status="cache_hit",
            )
            return cached.response_text

        try:
            self._guard.check()
        except BudgetExceeded:
            self._log_call(
                purpose=purpose,
                prompt_version=prompt_version,
                input_tokens=0,
                output_tokens=0,
                cost=0.0,
                latency_ms=0,
                status="budget_exceeded",
            )
            raise

        current_user = user
        last_exc: json.JSONDecodeError | None = None

        for attempt in range(1, 3):
            if last_exc is not None:
                current_user = (
                    f"{user}\n\n"
                    f"Your previous response was not valid JSON: {last_exc}\n"
                    "Respond with valid JSON only, no surrounding prose."
                )

            start = time.perf_counter()
            response = self._sdk.messages.create(
                model=self._model,
                max_tokens=max_tokens,
                system=system,
                messages=[{"role": "user", "content": current_user}],
                # No tools — CLAUDE.md Rule e
            )
            latency_ms = int((time.perf_counter() - start) * 1000)

            in_tok: int = response.usage.input_tokens
            out_tok: int = response.usage.output_tokens
            cost = in_tok * self._input_cost + out_tok * self._output_cost
            text = response.content[0].text.strip()

            try:
                json.loads(text)
            except json.JSONDecodeError as exc:
                last_exc = exc
                self._log_call(
                    purpose=purpose,
                    prompt_version=prompt_version,
                    input_tokens=in_tok,
                    output_tokens=out_tok,
                    cost=cost,
                    latency_ms=latency_ms,
                    status="rejected",
                )
                continue

            self._log_call(
                purpose=purpose,
                prompt_version=prompt_version,
                input_tokens=in_tok,
                output_tokens=out_tok,
                cost=cost,
                latency_ms=latency_ms,
                status="ok",
            )
            self._store_cache(
                cache_key=cache_key,
                purpose=purpose,
                prompt_version=prompt_version,
                response_text=text,
                input_tokens=in_tok,
                output_tokens=out_tok,
            )
            return text

        raise ValueError(
            f"LLM returned invalid JSON on both attempts: {last_exc}"
        ) from last_exc

    def _log_call(
        self,
        *,
        purpose: str,
        prompt_version: str,
        input_tokens: int,
        output_tokens: int,
        cost: float,
        latency_ms: int,
        status: str,
    ) -> None:
        record = LlmCall(
            purpose=purpose,
            model=self._model,
            prompt_version=prompt_version,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd=cost,
            latency_ms=latency_ms,
            status=status,
            created_at=datetime.now(timezone.utc).replace(tzinfo=None),
        )
        self._guard.session.add(record)
        self._guard.session.flush()
