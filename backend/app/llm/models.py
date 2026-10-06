from __future__ import annotations

from enum import Enum
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, field_validator


class EventType(str, Enum):
    earnings = "earnings"
    merger_acquisition = "merger_acquisition"
    product_launch = "product_launch"
    regulatory = "regulatory"
    executive_change = "executive_change"
    legal = "legal"
    macro = "macro"
    analyst_opinion = "analyst_opinion"
    promotional = "promotional"
    other = "other"


class ClusterClassification(BaseModel):
    model_config = ConfigDict(extra="forbid")

    cluster_id: int
    is_main_subject: bool
    event_type: EventType
    is_opinion: bool
    relevance_score: Annotated[float, Field(ge=0.0, le=1.0)]
    injection_suspected: bool
    injection_reason: str | None = None
    rationale_en: str


class DedupCheckResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    same_event: bool
    confidence: Annotated[float, Field(ge=0.0, le=1.0)]
    rationale_en: str


class EvidenceItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    article_id: int
    quote_en: Annotated[str, Field(max_length=200)]


class KeyFact(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text_bg: str
    evidence: Annotated[list[EvidenceItem], Field(min_length=1)]


class AttributedOpinion(BaseModel):
    model_config = ConfigDict(extra="forbid")

    who: str
    publisher: str
    opinion_bg: str
    evidence: list[EvidenceItem]


class SummarizationOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    cluster_id: int
    title_bg: Annotated[str, Field(max_length=90)]
    summary_bg: str
    key_facts: list[KeyFact]
    attributed_opinions: list[AttributedOpinion]
    uncertainties_bg: list[str]
    injection_suspected: bool

    @field_validator("title_bg")
    @classmethod
    def title_max_90(cls, v: str) -> str:
        if len(v) > 90:
            raise ValueError(f"title_bg exceeds 90 characters: {len(v)}")
        return v
