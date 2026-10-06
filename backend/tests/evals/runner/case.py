"""Golden-case schema for the evaluation harness."""
from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, model_validator

GOLDEN_DIR = Path(__file__).parent.parent / "golden"

CATEGORIES = Literal[
    "normal",
    "contradictory",
    "sparse",
    "opinion_heavy",
    "mention_only",
    "numbers_trap",
    "injection",
    "temporal",
]


class GoldenArticle(BaseModel):
    id: int
    ticker: str
    publisher: str
    title: str = ""
    clean_text: str


class GoldenCase(BaseModel):
    id: str
    category: CATEGORIES
    description: str
    articles: list[GoldenArticle]

    # --- expected outcomes ---
    expected_status: str | None = None
    expected_injection: bool | None = None
    expected_uncertainties: bool | None = None
    expected_is_opinion: bool | None = None
    expected_layer1_quarantine: bool | None = None

    # --- content assertions ---
    must_include_facts: list[str] = []
    must_not_include: list[str] = []

    @model_validator(mode="after")
    def _injection_case_must_declare_expectation(self) -> "GoldenCase":
        if self.category == "injection":
            if (
                self.expected_injection is None
                and self.expected_layer1_quarantine is None
            ):
                raise ValueError(
                    f"Injection case {self.id!r} must set expected_injection "
                    "or expected_layer1_quarantine."
                )
        return self

    @model_validator(mode="after")
    def _articles_ids_must_be_unique(self) -> "GoldenCase":
        ids = [a.id for a in self.articles]
        if len(ids) != len(set(ids)):
            raise ValueError(f"Case {self.id!r}: duplicate article ids: {ids}")
        return self


def load_case(path: Path) -> GoldenCase:
    """Parse a single YAML file into a GoldenCase."""
    with open(path, encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    return GoldenCase.model_validate(data)


def load_all_cases(golden_dir: Path = GOLDEN_DIR) -> list[GoldenCase]:
    """Load every *.yaml file in golden_dir, sorted by filename."""
    paths = sorted(golden_dir.glob("*.yaml"))
    return [load_case(p) for p in paths]
