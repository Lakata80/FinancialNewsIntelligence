"""Level 1 deterministic verification checks — no LLM calls."""
from __future__ import annotations

import re
from dataclasses import dataclass

from app.models.news import Article, FactEvidence, StoryFact
from app.verification.normalizer import (
    extract_numbers,
    normalize_text,
    number_matches_source,
)

# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------


@dataclass
class CheckResult:
    passed: bool
    details: str


# ---------------------------------------------------------------------------
# 1. no_advice — forbidden phrase check
# ---------------------------------------------------------------------------

_FORBIDDEN_BG = [
    "купете", "купувайте", "продайте", "продавайте",
    "препоръчваме", "препоръчва се", "препоръчвам",
    "добра възможност", "отлична възможност",
    "силна покупка", "силна продажба",
    "инвестирайте в", "вложете в",
    "целева цена от наше",
]

_FORBIDDEN_EN = [
    "buy signal", "sell signal",
    "strong buy", "strong sell",
    "we recommend", "we advise", "we suggest",
    "good buying opportunity", "great opportunity to buy",
    "price target of our",
]


def check_no_advice(fact: StoryFact) -> CheckResult:
    """Fail if fact.text_bg contains a forbidden buy/sell/advice phrase."""
    text_lower = fact.text_bg.lower()
    for phrase in _FORBIDDEN_BG:
        if phrase in text_lower:
            return CheckResult(
                passed=False,
                details=f"no_advice: забранена формулировка '{phrase}' в text_bg",
            )
    for phrase in _FORBIDDEN_EN:
        if phrase in text_lower:
            return CheckResult(
                passed=False,
                details=f"no_advice: forbidden phrase '{phrase}' in text_bg",
            )
    return CheckResult(passed=True, details="")


# ---------------------------------------------------------------------------
# 2. quote_exists — verbatim quote present in article after normalisation
# ---------------------------------------------------------------------------


def check_quote_exists(
    fact: StoryFact,
    evidence: list[FactEvidence],
    articles: dict[int, Article],
) -> CheckResult:
    """Fail if any quote_en is not found verbatim (after normalisation) in its article."""
    for ev in evidence:
        article = articles.get(ev.article_id)
        if article is None:
            return CheckResult(
                passed=False,
                details=f"quote_exists: article_id={ev.article_id} not found",
            )
        haystack_raw = article.clean_text or article.summary_raw or article.title or ""
        haystack = normalize_text(haystack_raw)
        quote = normalize_text(ev.quote_en)
        if not quote:
            return CheckResult(
                passed=False,
                details=f"quote_exists: empty quote_en for article_id={ev.article_id}",
            )
        if haystack.find(quote) == -1:
            # Case-insensitive fallback
            if haystack.lower().find(quote.lower()) == -1:
                return CheckResult(
                    passed=False,
                    details=(
                        f"quote_exists: цитатът не е намерен в article_id={ev.article_id}: "
                        f"{ev.quote_en[:60]!r}"
                    ),
                )
    return CheckResult(passed=True, details="")


# ---------------------------------------------------------------------------
# 3. numbers_grounded — every number in text_bg traces to a source
# ---------------------------------------------------------------------------


def check_numbers_grounded(
    fact: StoryFact,
    evidence: list[FactEvidence],
    articles: dict[int, Article],
) -> CheckResult:
    """Fail if any number in fact.text_bg cannot be found in the cited evidence."""
    numbers = extract_numbers(fact.text_bg)
    if not numbers:
        return CheckResult(passed=True, details="")

    # Build candidate texts: each ev.quote_en + article clean_text
    candidate_texts: list[str] = []
    for ev in evidence:
        candidate_texts.append(ev.quote_en)
        article = articles.get(ev.article_id)
        if article:
            candidate_texts.append(
                article.clean_text or article.summary_raw or article.title or ""
            )

    for value, unit in numbers:
        found = any(
            number_matches_source(value, unit, src) for src in candidate_texts
        )
        if not found:
            return CheckResult(
                passed=False,
                details=(
                    f"numbers_grounded: стойността {value!r} ({unit}) от text_bg "
                    f"не е намерена в изворите"
                ),
            )
    return CheckResult(passed=True, details="")


# ---------------------------------------------------------------------------
# 4. entities_grounded — tickers and company names in text_bg appear in sources
# ---------------------------------------------------------------------------

# Simple ticker pattern: 1-5 uppercase letters, optionally preceded by $
_TICKER_RE = re.compile(r"\$([A-Z]{1,5})\b|(?<!\w)([A-Z]{2,5})(?!\w)")

_COMMON_WORDS = frozenset(
    [
        "Q1", "Q2", "Q3", "Q4",
        "EPS", "CEO", "CFO", "COO", "CTO",
        "AI", "ML", "IPO", "M&A",
        "US", "EU", "UK", "ECB", "FED",
        "GDP", "CPI", "PPI", "USD", "EUR",
    ]
)


def _extract_tickers(text: str) -> set[str]:
    tickers: set[str] = set()
    for m in _TICKER_RE.finditer(text):
        t = m.group(1) or m.group(2)
        if t and t not in _COMMON_WORDS:
            tickers.add(t)
    return tickers


def check_entities_grounded(
    fact: StoryFact,
    evidence: list[FactEvidence],
    articles: dict[int, Article],
) -> CheckResult:
    """Fail if a ticker mentioned in text_bg does not appear in any source."""
    tickers = _extract_tickers(fact.text_bg)
    if not tickers:
        return CheckResult(passed=True, details="")

    source_texts: list[str] = []
    for ev in evidence:
        source_texts.append(ev.quote_en)
        article = articles.get(ev.article_id)
        if article:
            source_texts.append(
                article.clean_text or article.summary_raw or article.title or ""
            )
    combined = " ".join(source_texts).upper()

    missing = [t for t in tickers if t not in combined]
    if missing:
        return CheckResult(
            passed=False,
            details=f"entities_grounded: тикери {missing} не са намерени в изворите",
        )
    return CheckResult(passed=True, details="")


# ---------------------------------------------------------------------------
# 5. opinion_placement — detect opinion markers (flags for Level 2, not hard remove)
# ---------------------------------------------------------------------------

_OPINION_MARKERS_EN = [
    "analyst", "analysts", "expect", "expects", "expected",
    "we believe", "we think", "rating", "upgrade", "downgrade",
    "overweight", "underweight", "outperform", "underperform",
    "price target", "target price", "buy rating", "sell rating",
    "initiates coverage", "raises target", "lowers target",
]

_OPINION_MARKERS_BG = [
    "анализатор", "анализатори", "анализаторите",
    "очаква", "очакват", "очакване", "очакванията",
    "рейтинг", "препоръчва", "препоръчват",
    "целева цена", "целева цена от",
    "повиши целевата", "намали целевата",
    "надгради", "понижи препоръката",
    "смятаме", "считаме",
]


def check_opinion_placement(
    fact: StoryFact,
    evidence: list[FactEvidence],
) -> CheckResult:
    """Return passed=False (flag for Level 2) if opinion markers are detected.

    This check does NOT hard-remove the fact — it signals that Level 2 should
    decide whether the claim is actually supported by the quotes.
    """
    text_lower = fact.text_bg.lower()
    for marker in _OPINION_MARKERS_BG:
        if marker in text_lower:
            return CheckResult(
                passed=False,
                details=f"opinion_placement: маркер '{marker}' в text_bg → изпрати на ниво 2",
            )
    for ev in evidence:
        quote_lower = ev.quote_en.lower()
        for marker in _OPINION_MARKERS_EN:
            if marker in quote_lower:
                return CheckResult(
                    passed=False,
                    details=(
                        f"opinion_placement: маркер '{marker}' в цитата "
                        f"→ изпрати на ниво 2"
                    ),
                )
    return CheckResult(passed=True, details="")
