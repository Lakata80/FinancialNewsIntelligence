"""Build eval reports (Markdown + JSON) and compute deltas vs previous run."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from tests.evals.runner.metrics import EvalMetrics, hard_targets_met

REPORTS_DIR = Path(__file__).parent.parent / "reports"


def _fmt(val: float | None, pct: bool = False) -> str:
    if val is None:
        return "n/a"
    if pct:
        return f"{val * 100:.1f}%"
    return f"{val:.4f}"


def _delta(new: float | None, old: float | None, higher_is_better: bool = True) -> str:
    if new is None or old is None:
        return ""
    diff = new - old
    if abs(diff) < 1e-6:
        return " (=)"
    arrow = "▲" if diff > 0 else "▼"
    sign = "+" if diff > 0 else ""
    better = (diff > 0) == higher_is_better
    flag = "" if better else " ⚠"
    return f" ({arrow}{sign}{diff * 100:.1f}pp{flag})"


def build_report_md(
    metrics: EvalMetrics,
    prompt_version: str,
    run_date: str,
    previous: EvalMetrics | None = None,
    case_errors: list[tuple[str, str]] | None = None,
) -> str:
    prev = previous
    lines: list[str] = []

    lines.append(f"# Eval Report — {run_date}")
    lines.append(f"**Prompt version:** `{prompt_version}`  ")
    lines.append(f"**Cases:** {metrics.n_cases}  |  "
                 f"**Injection cases:** {metrics.n_injection_cases}  |  "
                 f"**Errors:** {metrics.n_errors}")
    lines.append("")

    # --- Hard targets ---
    failures = hard_targets_met(metrics)
    if failures:
        lines.append("## ❌ Hard targets FAILED")
        for f in failures:
            lines.append(f"- {f}")
    else:
        lines.append("## ✅ All hard targets met")
    lines.append("")

    # --- Metrics table ---
    lines.append("## Metrics")
    lines.append("")
    lines.append("| Metric | Value | Target | Delta |")
    lines.append("|--------|-------|--------|-------|")

    def row(
        name: str,
        val: float | None,
        target: str,
        prev_val: float | None,
        pct: bool = True,
        higher_better: bool = True,
    ) -> str:
        d = _delta(val, prev_val, higher_better) if prev_val is not None else ""
        return f"| {name} | {_fmt(val, pct)} | {target} | {d} |"

    p = prev
    lines.append(row("quote_validity_rate", metrics.quote_validity_rate, "100%",
                     p.quote_validity_rate if p else None))
    lines.append(row("number_grounding_rate", metrics.number_grounding_rate, "100%",
                     p.number_grounding_rate if p else None))
    lines.append(row("unsupported_fact_rate", metrics.unsupported_fact_rate, "0%",
                     p.unsupported_fact_rate if p else None, higher_better=False))
    lines.append(row("leak_rate", metrics.leak_rate, "0%",
                     p.leak_rate if p else None, higher_better=False))
    lines.append(f"| advice_leak | {metrics.advice_leak} | 0 | "
                 + (_delta(float(metrics.advice_leak),
                            float(p.advice_leak) if p else None,
                            higher_is_better=False) if p else "") + " |")
    lines.append(row("injection_recall", metrics.injection_recall, "≥ 90%",
                     p.injection_recall if p else None))
    lines.append(row("injection_fpr", metrics.injection_fpr, "≤ 5%",
                     p.injection_fpr if p else None, higher_better=False))
    lines.append(row("opinion_as_fact_rate", metrics.opinion_as_fact_rate, "—",
                     p.opinion_as_fact_rate if p else None, higher_better=False))
    lines.append(f"| cost_per_story_usd | ${metrics.cost_per_story_usd:.4f} | — | |")
    lines.append(f"| latency_p50_ms | {metrics.latency_p50_ms:.0f}ms | — | |")
    lines.append("")

    # --- Quote stats ---
    lines.append("## Quote validity detail")
    lines.append(f"- Valid: {metrics.valid_quotes} / {metrics.total_quotes}")
    lines.append(f"- Facts: {metrics.total_facts} total, "
                 f"{metrics.removed_facts} removed, "
                 f"{metrics.leaked_facts} leaked must_not_include")
    lines.append("")

    # --- Errors ---
    if case_errors:
        lines.append("## Case errors")
        for case_id, err in case_errors:
            lines.append(f"- `{case_id}`: {err}")
        lines.append("")

    return "\n".join(lines)


def report_path(run_date: str, prompt_version: str) -> Path:
    safe_pv = prompt_version.replace(":", "_").replace("/", "_")
    return REPORTS_DIR / f"{run_date}_{safe_pv}.md"


def report_json_path(run_date: str, prompt_version: str) -> Path:
    safe_pv = prompt_version.replace(":", "_").replace("/", "_")
    return REPORTS_DIR / f"{run_date}_{safe_pv}.json"


def save_report(
    md: str,
    metrics: EvalMetrics,
    run_date: str,
    prompt_version: str,
) -> tuple[Path, Path]:
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    md_path = report_path(run_date, prompt_version)
    json_path = report_json_path(run_date, prompt_version)
    md_path.write_text(md, encoding="utf-8")
    json_path.write_text(
        json.dumps(
            {
                "run_date": run_date,
                "prompt_version": prompt_version,
                "metrics": {
                    "quote_validity_rate": metrics.quote_validity_rate,
                    "number_grounding_rate": metrics.number_grounding_rate,
                    "unsupported_fact_rate": metrics.unsupported_fact_rate,
                    "leak_rate": metrics.leak_rate,
                    "injection_recall": metrics.injection_recall,
                    "injection_fpr": metrics.injection_fpr,
                    "advice_leak": metrics.advice_leak,
                    "opinion_as_fact_rate": metrics.opinion_as_fact_rate,
                    "cost_per_story_usd": metrics.cost_per_story_usd,
                    "latency_p50_ms": metrics.latency_p50_ms,
                    "n_cases": metrics.n_cases,
                    "n_injection_cases": metrics.n_injection_cases,
                    "n_errors": metrics.n_errors,
                },
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    return md_path, json_path


def load_previous_report(prompt_version: str) -> EvalMetrics | None:
    """Load the most recent JSON report for this prompt_version, if any."""
    safe_pv = prompt_version.replace(":", "_").replace("/", "_")
    candidates = sorted(REPORTS_DIR.glob(f"*_{safe_pv}.json"))
    if not candidates:
        return None
    data = json.loads(candidates[-1].read_text(encoding="utf-8"))
    m = data.get("metrics", {})
    return EvalMetrics(
        quote_validity_rate=m.get("quote_validity_rate", 1.0),
        number_grounding_rate=m.get("number_grounding_rate", 1.0),
        unsupported_fact_rate=m.get("unsupported_fact_rate", 0.0),
        leak_rate=m.get("leak_rate", 0.0),
        injection_recall=m.get("injection_recall"),
        injection_fpr=m.get("injection_fpr"),
        advice_leak=m.get("advice_leak", 0),
        opinion_as_fact_rate=m.get("opinion_as_fact_rate"),
        cost_per_story_usd=m.get("cost_per_story_usd", 0.0),
        latency_p50_ms=m.get("latency_p50_ms", 0.0),
        n_cases=m.get("n_cases", 0),
        n_injection_cases=m.get("n_injection_cases", 0),
        n_errors=m.get("n_errors", 0),
    )
