"""Text and number normalisation utilities for verification checks."""
from __future__ import annotations

import re
import unicodedata

# ---------------------------------------------------------------------------
# Text normalisation
# ---------------------------------------------------------------------------

# Typographic quotes → ASCII
_QUOTE_MAP = str.maketrans(
    "‘’‚‛“”„‟«»‹›",
    "''" + "''" + '""' + '""' + "\"\"" + "''",
)
# Em-dash / en-dash / figure-dash / horizontal bar → hyphen
_DASH_MAP = str.maketrans("–—―‒", "----")


def normalize_text(s: str) -> str:
    """Collapse whitespace; normalise typographic quotes and dashes to ASCII."""
    s = s.translate(_QUOTE_MAP)
    s = s.translate(_DASH_MAP)
    # Strip soft-hyphens and zero-width spaces
    s = unicodedata.normalize("NFKC", s)
    s = re.sub(r"[­​‌‍﻿]", "", s)
    return re.sub(r"\s+", " ", s).strip()


# ---------------------------------------------------------------------------
# Number extraction from Bulgarian text
# ---------------------------------------------------------------------------

# Bulgarian magnitude words → multiplier
_BG_MAGNITUDE: dict[str, float] = {
    "трлн": 1e12,
    "трилиона": 1e12,
    "трилиони": 1e12,
    "млрд": 1e9,
    "милиарда": 1e9,
    "милиарди": 1e9,
    "млн": 1e6,
    "милиона": 1e6,
    "милиони": 1e6,
    "хил": 1e3,
    "хиляди": 1e3,
    "хиляда": 1e3,
}

# English magnitude words → multiplier
_EN_MAGNITUDE: dict[str, float] = {
    "trillion": 1e12,
    "billion": 1e9,
    "million": 1e6,
    "thousand": 1e3,
    "b": 1e9,   # $3.5B
    "m": 1e6,   # $3.5M
    "t": 1e12,  # $3.5T
    "k": 1e3,
}

# Quarter ordinal words in Bulgarian → Q number
_BG_QUARTER: dict[str, int] = {
    "първото": 1, "първи": 1,
    "второто": 2, "втори": 2,
    "третото": 3, "трети": 3,
    "четвъртото": 4, "четвърти": 4,
}

# Regex to capture a BG number token:
#   optional currency prefix ($, €, £, лв), digits (comma decimal), optional magnitude
_BG_NUMBER_RE = re.compile(
    r"(?P<cur>[$€£])?"
    r"(?P<int>\d{1,3}(?:[.,]\d{3})*|\d+)"
    r"(?:[,.](?P<dec>\d+))?"
    r"\s*(?P<mag>" + "|".join(sorted(_BG_MAGNITUDE, key=len, reverse=True)) + r")?"
    r"\.?"
    r"(?:\s*(?P<cur2>[дД]олара|долари|[еЕ]вро|лв\.?))?"
    r"(?P<pct>\s*%)?",
    re.IGNORECASE,
)

# Quarter pattern in BG: "Q3", "Q 3", "тримесечие"
_BG_QUARTER_RE = re.compile(
    r"\b(?:Q\s*([1-4])|"
    r"([първивторотретичетвърт]\w+)\s+тримесечие)",
    re.IGNORECASE,
)

# EPS / per-share pattern
_BG_EPS_RE = re.compile(
    r"(?P<cur>[$€])?\s*(?P<val>\d+[.,]\d+)\s*(?:долара|евро)?\s*на\s+акция",
    re.IGNORECASE,
)


def _parse_float(int_part: str, dec_part: str | None) -> float:
    """Convert BG integer + decimal parts to float.

    BG uses comma as decimal separator and period/space as thousands separator.
    E.g. "18,1" → 18.1 ; "1.234" → 1234 ; "1 234" → 1234
    """
    # Remove thousands separators (period or space between digit groups)
    clean_int = re.sub(r"[.\s](?=\d{3})", "", int_part)
    # Remove any remaining periods (could be stray)
    clean_int = clean_int.replace(".", "")
    value = float(clean_int)
    if dec_part:
        value += float(dec_part) / (10 ** len(dec_part))
    return value


def extract_numbers(text_bg: str) -> list[tuple[float, str]]:
    """Return (canonical_value, unit) pairs from Bulgarian text.

    unit is one of: "%" | "usd" | "eur" | "bgn" | "shares" | "Q1".."Q4" | ""
    canonical_value is the full numeric value (e.g. 3.5e9 for "3,5 млрд.").
    """
    results: list[tuple[float, str]] = []
    text = normalize_text(text_bg)

    # Percentages (simple, handle before general number scan)
    for m in re.finditer(r"(\d+(?:[.,]\d+)?)\s*%", text):
        int_p, _, dec_p = m.group(1).partition(",")
        if not dec_p:
            int_p, _, dec_p2 = m.group(1).partition(".")
            dec_p = dec_p2 if "." in m.group(1) and not dec_p else dec_p
        val = _parse_float(int_p, dec_p or None)
        results.append((val, "%"))

    # EPS / per-share
    for m in _BG_EPS_RE.finditer(text):
        int_p, _, dec_p = m.group("val").replace(",", ".").partition(".")
        # val already has decimal point replaced
        try:
            val = float(m.group("val").replace(",", "."))
        except ValueError:
            continue
        unit = "usd" if (m.group("cur") or "") == "$" else "eur"
        results.append((val, unit + "_per_share"))

    # General currency / magnitude numbers
    for m in _BG_NUMBER_RE.finditer(text):
        int_part = m.group("int")
        dec_part = m.group("dec")
        mag_word = (m.group("mag") or "").lower().rstrip(".")
        cur = (m.group("cur") or "").strip()
        cur2 = (m.group("cur2") or "").lower()
        pct = m.group("pct")

        # Skip if already captured as percentage
        if pct:
            continue
        # Skip pure integer that is a year (1900–2099)
        if not dec_part and not mag_word and not cur and not cur2:
            try:
                v = int(int_part)
                if 1900 <= v <= 2099:
                    continue
                if v == 0:
                    continue
            except ValueError:
                pass

        try:
            val = _parse_float(int_part, dec_part)
        except ValueError:
            continue

        multiplier = _BG_MAGNITUDE.get(mag_word, 1.0) if mag_word else 1.0
        val *= multiplier

        if cur == "$" or "долар" in cur2:
            unit = "usd"
        elif cur == "€" or "евро" in cur2:
            unit = "eur"
        elif "лв" in cur2:
            unit = "bgn"
        elif mag_word:
            unit = "usd"  # unnamed large number — assume USD in financial context
        else:
            unit = ""

        if val > 0:
            results.append((val, unit))

    # Quarters
    for m in _BG_QUARTER_RE.finditer(text):
        if m.group(1):
            results.append((float(m.group(1)), "quarter"))
        else:
            ord_word = m.group(2).lower()
            q = _BG_QUARTER.get(ord_word)
            if q:
                results.append((float(q), "quarter"))

    # Deduplicate while preserving order
    seen: set[tuple[float, str]] = set()
    unique: list[tuple[float, str]] = []
    for item in results:
        if item not in seen:
            seen.add(item)
            unique.append(item)
    return unique


# ---------------------------------------------------------------------------
# Number surface-form matching against English source text
# ---------------------------------------------------------------------------

def _en_surface_forms(value: float, unit: str) -> list[str]:
    """Generate English surface forms that represent (value, unit)."""
    forms: list[str] = []

    if unit == "%":
        # 12.5 → "12.5%", "12.5 percent"
        if value == int(value):
            s = str(int(value))
        else:
            s = f"{value:g}"
        forms += [f"{s}%", f"{s} percent", f"{s} per cent"]
        return forms

    if unit == "quarter":
        q = int(value)
        _ordinals = {1: "first", 2: "second", 3: "third", 4: "fourth"}
        forms += [
            f"Q{q}", f"Q {q}", f"quarter {q}",
            f"{_ordinals.get(q, str(q))} quarter",
        ]
        return forms

    # Monetary values
    for mag_val, mag_suffixes in [
        (1e12, ["trillion", "T"]),
        (1e9, ["billion", "B"]),
        (1e6, ["million", "M"]),
        (1e3, ["thousand", "K"]),
    ]:
        if abs(value) >= mag_val * 0.9:
            scaled = value / mag_val
            if scaled == int(scaled):
                s = str(int(scaled))
            else:
                s = f"{scaled:g}"
            for mag_s in mag_suffixes:
                if unit == "usd":
                    forms += [f"${s} {mag_s}", f"${s}{mag_s}", f"{s} {mag_s}"]
                elif unit == "eur":
                    forms += [f"€{s} {mag_s}", f"{s} {mag_s}"]
                else:
                    forms += [f"{s} {mag_s}", f"{s}{mag_s}"]
            break
    else:
        # No magnitude match — bare number
        if value == int(value):
            s = str(int(value))
        else:
            s = f"{value:g}"
        if unit == "usd":
            forms += [f"${s}", s]
        elif unit == "eur":
            forms += [f"€{s}", s]
        else:
            forms.append(s)

    return forms


def number_matches_source(value: float, unit: str, source_text: str) -> bool:
    """Return True if any surface form of (value, unit) appears in source_text."""
    source_norm = normalize_text(source_text).lower()
    for form in _en_surface_forms(value, unit):
        if form.lower() in source_norm:
            return True
    return False
