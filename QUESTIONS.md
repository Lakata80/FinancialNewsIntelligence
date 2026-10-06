# Open Questions

## Q-001 — ECB Press RSS URL

**Status:** Open
**Date:** 2026-10-05

What is the canonical RSS feed URL for ECB press releases?

The `ECBPressRSS` connector is stubbed in `backend/app/ingestion/ecb.py` and returns `[]` until this is resolved.
Candidate to verify on the ECB website: `https://www.ecb.europa.eu/press/` (look for RSS/Atom link in the page source).

Do not implement until the URL is confirmed and recorded in DECISIONS.md.

---

## Q-002 — Summarization model ID

**Status:** Resolved
**Date:** 2026-10-06

Sprint 4 spec referenced "Claude Sonnet 5.5" — no such model exists in the current Anthropic roster. Confirmed with user: use `claude-sonnet-4-6`. Recorded in `config.yaml` as `llm.summarize_model`.

---

## Q-004 — Pipeline trigger scope (Sprint 6)

**Status:** Open
**Date:** 2026-10-06

Бутонът „Обнови" в UI-то трябва ли да пуска пълния pipeline (fetch → dedup → classify → summarize → verify, ~2-3 мин) или само fetch стадий?

Текуща имплементация в Sprint 6: пълен pipeline с background thread + polling. LLM стадиите се пропускат тихо ако `ANTHROPIC_API_KEY` не е зададен.

---

## Q-003 — Verification judge model ID

**Status:** Open
**Date:** 2026-10-06

Sprint 5 spec references "Claude Sonnet 5.5" for the Level 2 LLM judge. That model ID does not exist (same situation as Q-002). Should we use `claude-sonnet-4-6` (consistent with summarization) and expose it as `llm.verify_model` in `config.yaml`?

Current default: `claude-sonnet-4-6` (same as summarize_model). Pending user confirmation.

---

## Q-005 — Summarization of standalone SEC filings (10-Q / 10-K)

**Status:** Open
**Date:** 2026-10-06

When a 10-Q or 10-K filing has no matching media cluster, it becomes a standalone `StoryCluster`. Should the system generate a Bulgarian LLM summary for it?

10-K filings can exceed 200 pages; passing the full `clean_text` to Sonnet would exceed token limits and cost significantly. Proposed rule: the summarizer runs only if `clean_text ≤ 8 000 characters`; otherwise the cluster remains without a `Story` row (visible in UI as a raw SEC entry without summary).

Do not implement the summarizer guard until this limit is confirmed.

---

## Q-006 — `Source.kind` value for SEC EDGAR connector

**Status:** Open
**Date:** 2026-10-06

Current valid values for `Source.kind`: `"rss"` | `"api"`. Sprint 8 spec says `"source kind=primary"`.

Two options:
- **Option A (recommended):** Add `"primary"` as a new kind value. Clearer semantic signal; easier to distinguish in debug queries and logs.
- **Option B:** Reuse `"api"` and rely solely on `Source.is_official = True`.

Sprint 8 implementation uses `"primary"` (Option A) pending confirmation. SQLite does not enforce VARCHAR domains, so no DDL change is required — the value is documented in ADR-024.

---

## Q-007 — Retention cascade for cited articles

**Status:** Open
**Date:** 2026-10-06

Raw articles are configured for deletion after 90 days; stories are kept for 1 year. Articles cited in `fact_evidence` have an FK to `articles.id`. Should cited articles be kept for the full story retention period (1 year) even though the raw-article policy says 90 days, or is `fact_evidence.quote_en` (the verbatim quote already stored) sufficient to satisfy CLAUDE.md Rule c once the article ages out?

Current plan (pending answer): cited articles are **not** deleted until their story expires. The cleanup command skips any article that has at least one `fact_evidence` row referencing it.
