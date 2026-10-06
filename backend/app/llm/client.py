from __future__ import annotations

import json
import time
from datetime import datetime, timezone

import anthropic

from app.llm.budget import BudgetExceeded, BudgetGuard
from app.models.news import LlmCall

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
    ) -> None:
        self._sdk = anthropic.Anthropic(api_key=api_key)
        self._model = model
        self._guard = guard
        self._input_cost = input_cost_per_token
        self._output_cost = output_cost_per_token

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

        Raises:
            BudgetExceeded: if the daily or monthly cap is reached.
            ValueError: if the LLM returns invalid JSON on both attempts.
        """
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
