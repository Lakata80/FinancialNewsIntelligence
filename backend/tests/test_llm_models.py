"""Tests for LLM pydantic schemas — no API calls."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.llm.models import ClusterClassification, DedupCheckResult, EventType

_FIXTURES = Path(__file__).parent / "fixtures" / "llm"


def _load(name: str) -> str:
    return (_FIXTURES / name).read_text(encoding="utf-8")


class TestClusterClassification:
    def test_valid_parse(self):
        result = ClusterClassification.model_validate_json(_load("classify_valid.json"))
        assert result.cluster_id == 1
        assert result.event_type == EventType.earnings
        assert result.is_main_subject is True
        assert result.relevance_score == 0.9
        assert result.injection_suspected is False
        assert result.injection_reason is None

    def test_injection_fixture(self):
        result = ClusterClassification.model_validate_json(_load("classify_injection.json"))
        assert result.injection_suspected is True
        assert result.injection_reason is not None

    def test_promotional_fixture(self):
        result = ClusterClassification.model_validate_json(_load("classify_promotional.json"))
        assert result.event_type == EventType.promotional

    def test_extra_fields_rejected(self):
        data = json.loads(_load("classify_valid.json"))
        data["unexpected_field"] = "surprise"
        with pytest.raises(ValidationError):
            ClusterClassification.model_validate(data)

    def test_relevance_score_out_of_range(self):
        data = json.loads(_load("classify_valid.json"))
        data["relevance_score"] = 1.5
        with pytest.raises(ValidationError):
            ClusterClassification.model_validate(data)

    def test_relevance_score_negative(self):
        data = json.loads(_load("classify_valid.json"))
        data["relevance_score"] = -0.1
        with pytest.raises(ValidationError):
            ClusterClassification.model_validate(data)

    def test_unknown_event_type(self):
        data = json.loads(_load("classify_valid.json"))
        data["event_type"] = "moon_launch"
        with pytest.raises(ValidationError):
            ClusterClassification.model_validate(data)

    def test_missing_required_field(self):
        data = json.loads(_load("classify_valid.json"))
        del data["rationale_en"]
        with pytest.raises(ValidationError):
            ClusterClassification.model_validate(data)


class TestDedupCheckResult:
    def test_same_event(self):
        result = DedupCheckResult.model_validate_json(_load("dedup_same_event.json"))
        assert result.same_event is True
        assert result.confidence == 0.95

    def test_different_event(self):
        result = DedupCheckResult.model_validate_json(_load("dedup_different_event.json"))
        assert result.same_event is False
        assert result.confidence == 0.88

    def test_confidence_out_of_range(self):
        data = {"same_event": True, "confidence": 1.1, "rationale_en": "x"}
        with pytest.raises(ValidationError):
            DedupCheckResult.model_validate(data)

    def test_extra_fields_rejected(self):
        data = json.loads(_load("dedup_same_event.json"))
        data["extra"] = "bad"
        with pytest.raises(ValidationError):
            DedupCheckResult.model_validate(data)
