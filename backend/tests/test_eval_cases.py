"""Validate all golden YAML cases load and satisfy invariants."""
from __future__ import annotations

import pytest

from tests.evals.runner.case import GOLDEN_DIR, GoldenCase, load_all_cases


def _all_cases() -> list[GoldenCase]:
    return load_all_cases()


def test_golden_dir_exists():
    assert GOLDEN_DIR.exists(), f"Golden directory not found: {GOLDEN_DIR}"


def test_all_cases_parse():
    """Every YAML file in golden/ parses without error."""
    cases = _all_cases()
    assert len(cases) >= 30, (
        f"Expected at least 30 golden cases, found {len(cases)}"
    )


def test_category_coverage():
    """Each required category has at least 3 cases."""
    cases = _all_cases()
    required = {
        "normal": 3,
        "contradictory": 3,
        "sparse": 3,
        "opinion_heavy": 3,
        "mention_only": 3,
        "numbers_trap": 3,
        "injection": 10,
        "temporal": 3,
    }
    by_cat: dict[str, int] = {}
    for c in cases:
        by_cat[c.category] = by_cat.get(c.category, 0) + 1

    for cat, min_count in required.items():
        count = by_cat.get(cat, 0)
        assert count >= min_count, (
            f"Category {cat!r}: expected >= {min_count} cases, found {count}"
        )


def test_injection_cases_declare_expectation():
    """All injection cases declare expected_injection or expected_layer1_quarantine."""
    cases = _all_cases()
    for c in cases:
        if c.category == "injection":
            assert (
                c.expected_injection is not None
                or c.expected_layer1_quarantine is not None
            ), f"Injection case {c.id!r} has no expected_injection or expected_layer1_quarantine"


def test_unique_case_ids():
    cases = _all_cases()
    ids = [c.id for c in cases]
    assert len(ids) == len(set(ids)), "Duplicate case IDs found"


def test_must_not_include_nonempty_strings():
    """Every must_not_include entry is a non-empty string."""
    cases = _all_cases()
    for c in cases:
        for entry in c.must_not_include:
            assert isinstance(entry, str) and entry.strip(), (
                f"Case {c.id!r}: empty or non-string must_not_include entry: {entry!r}"
            )


def test_articles_have_clean_text():
    cases = _all_cases()
    for c in cases:
        for a in c.articles:
            assert a.clean_text and a.clean_text.strip(), (
                f"Case {c.id!r} article id={a.id}: empty clean_text"
            )


@pytest.mark.parametrize("case", _all_cases(), ids=lambda c: c.id)
def test_case_schema(case: GoldenCase):
    """Each case individually validates against GoldenCase schema."""
    assert case.id
    assert case.category
    assert len(case.articles) >= 1
