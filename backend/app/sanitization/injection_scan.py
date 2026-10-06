from __future__ import annotations

import base64
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol, runtime_checkable

import yaml

_DEFAULT_RULES_PATH = Path(__file__).parent / "injection_rules.yaml"

# Zero-width and bidi control chars: replace with space so
# "ignore​previous" becomes "ignore previous" and still matches phrase rules.
_OBFUSCATION_CHARS = (
    "​"  # zero-width space
    "‌"  # zero-width non-joiner
    "‍"  # zero-width joiner
    "﻿"  # BOM / zero-width no-break space
    "⁠"  # word joiner
    "‎"  # left-to-right mark
    "‏"  # right-to-left mark
    "‪"  # left-to-right embedding
    "‫"  # right-to-left embedding
    "‬"  # pop directional formatting
    "‭"  # left-to-right override
    "‮"  # right-to-left override
    "⁦"  # left-to-right isolate
    "⁧"  # right-to-left isolate
    "⁨"  # first strong isolate
    "⁩"  # pop directional isolate
)
_OBFUSCATION_RE = re.compile("[" + re.escape(_OBFUSCATION_CHARS) + "]")
_MULTI_WS = re.compile(r"\s+")


def _preprocess(text: str) -> str:
    """Replace obfuscation chars with spaces and collapse whitespace."""
    text = _OBFUSCATION_RE.sub(" ", text)
    return _MULTI_WS.sub(" ", text)


@dataclass
class InjectionResult:
    injection_score: float  # 0..1, capped at 1.0
    matched_rules: list[str] = field(default_factory=list)


@runtime_checkable
class ScanLayer(Protocol):
    """Interface for scan layers — rule-based (Sprint 2) or LLM-based (Sprint 5)."""

    def scan(self, text: str) -> InjectionResult: ...


class _RuleBasedScanner:
    def __init__(self, rules_path: Path) -> None:
        with open(rules_path, encoding="utf-8") as fh:
            cfg = yaml.safe_load(fh)
        self._threshold: float = float(cfg.get("quarantine_threshold", 0.5))
        self._rules: list[dict] = cfg.get("rules", [])

    @property
    def threshold(self) -> float:
        return self._threshold

    def scan(self, text: str) -> InjectionResult:
        # Preprocess: replace obfuscation chars with spaces, collapse whitespace
        cleaned = _preprocess(text)
        lower = cleaned.lower()

        matched: list[str] = []
        total_weight = 0.0

        for rule in self._rules:
            name: str = rule["name"]
            kind: str = rule["type"]
            weight: float = float(rule.get("weight", 0.1))

            hit = False
            if kind == "phrase":
                for pat in rule.get("patterns", []):
                    if pat.lower() in lower:
                        hit = True
                        break
            elif kind == "regex":
                for pat in rule.get("patterns", []):
                    if re.search(pat, cleaned):
                        hit = True
                        break
            elif kind == "base64":
                min_len: int = int(rule.get("min_length", 100))
                b64_re = re.compile(r"[A-Za-z0-9+/]{" + str(min_len) + r",}={0,2}")
                for m in b64_re.finditer(text):
                    candidate = m.group(0)
                    padding = (4 - len(candidate) % 4) % 4
                    try:
                        base64.b64decode(candidate + "=" * padding, validate=True)
                        hit = True
                        break
                    except Exception:
                        pass

            if hit:
                matched.append(name)
                total_weight += weight

        score = min(1.0, total_weight)
        return InjectionResult(injection_score=score, matched_rules=matched)


# Module-level cache so rules file is parsed once per process per path
_scanner_cache: dict[Path, _RuleBasedScanner] = {}


def _get_scanner(rules_path: Path) -> _RuleBasedScanner:
    if rules_path not in _scanner_cache:
        _scanner_cache[rules_path] = _RuleBasedScanner(rules_path)
    return _scanner_cache[rules_path]


def clear_cache() -> None:
    """Clear the rules-file cache. Useful in tests after modifying rule files."""
    _scanner_cache.clear()


def scan_article(
    text: str,
    rules_path: Path | None = None,
) -> InjectionResult:
    """Scan *text* for prompt-injection patterns.

    Pass the RAW text (including any HTML) so hidden elements, alt attributes,
    and zero-width obfuscation are all visible to the scanner.

    Returns InjectionResult with injection_score (0..1) and matched rule names.
    """
    path = rules_path or _DEFAULT_RULES_PATH
    scanner = _get_scanner(path)
    return scanner.scan(text)


def quarantine_threshold(rules_path: Path | None = None) -> float:
    """Return the configured quarantine threshold."""
    path = rules_path or _DEFAULT_RULES_PATH
    return _get_scanner(path).threshold
