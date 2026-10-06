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
