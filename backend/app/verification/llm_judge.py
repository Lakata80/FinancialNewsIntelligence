"""Level 2 LLM judge — verifies that a fact is supported by its evidence quotes."""
from __future__ import annotations

import hashlib
import json
import logging
from enum import Enum
from pathlib import Path

from pydantic import BaseModel, ConfigDict, ValidationError

from app.llm.client import AnthropicLlmClient
from app.models.news import StoryFact

logger = logging.getLogger(__name__)

_PROMPT_PATH = Path(__file__).parent.parent / "llm" / "prompts" / "verify_v1.md"
_PROMPT_TEXT = _PROMPT_PATH.read_text(encoding="utf-8")
VERIFY_PROMPT_VERSION = (
    "verify_v1:" + hashlib.sha256(_PROMPT_TEXT.encode()).hexdigest()[:8]
)


class FactSupport(str, Enum):
    supported = "supported"
    partially_supported = "partially_supported"
    not_supported = "not_supported"


class VerifyOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    fact_id: int
    support: FactSupport
    missing_or_added_bg: str | None = None


def judge_fact(
    fact: StoryFact,
    quote_texts: list[str],
    client: AnthropicLlmClient,
) -> FactSupport:
    """Call the LLM judge to determine support level for a fact.

    Returns FactSupport. On budget exhaustion or double JSON failure, raises the
    exception — caller decides whether to skip or abort.
    """
    payload = {
        "fact_id": fact.id,
        "fact_text_bg": fact.text_bg,
        "quotes": quote_texts,
    }
    user_msg = json.dumps(payload, ensure_ascii=False)

    raw = client.call(
        system=_PROMPT_TEXT,
        user=user_msg,
        purpose="verify",
        prompt_version=VERIFY_PROMPT_VERSION,
        max_tokens=512,
    )

    try:
        output = VerifyOutput.model_validate_json(raw)
    except ValidationError as exc:
        logger.warning("verify fact %d: schema validation failed: %s", fact.id, exc)
        raise ValueError(f"judge_fact: schema error for fact {fact.id}") from exc

    if output.fact_id != fact.id:
        logger.warning(
            "verify fact %d: response fact_id mismatch (%d) — rejected",
            fact.id,
            output.fact_id,
        )
        raise ValueError(
            f"judge_fact: fact_id mismatch: got {output.fact_id}, expected {fact.id}"
        )

    return output.support
