# Financial News Intelligence

Personal tool for aggregating and summarizing financial news with AI assistance.
Information aggregation only — not an investment advisor.

---

## Prerequisites

Install the following tools (Windows, via winget):

```powershell
# Python package manager (also manages the Python version automatically)
winget install --id astral-sh.uv

# Node.js LTS
winget install --id OpenJS.NodeJS.LTS

# just (cross-platform task runner)
winget install --id Casey.Just
```

After installing, restart your terminal so the tools are available in PATH.

---

## Quick start

```powershell
# 1. Copy secrets template and fill in your API keys
cp .env.example .env

# 2. Install all dependencies (Python + Node)
just setup

# 3. Start backend (port 8000) + frontend (port 5173)
just dev
```

- Backend health check: http://localhost:8000/health
- Frontend: http://localhost:5173
- API docs: http://localhost:8000/docs

---

## Common commands

| Command | Description |
|---|---|
| `just setup` | Install all dependencies |
| `just dev` | Start backend + frontend |
| `just dev-backend` | Start backend only |
| `just dev-frontend` | Start frontend only |
| `just test` | Run backend tests with coverage |
| `just lint` | Ruff + mypy |
| `just e2e` | Run Playwright e2e tests (requires dev running) |
| `just eval-replay` | Run eval harness against recorded responses (free) |
| `just eval` | Run eval harness against live API (costs money) |
| `just cleanup-dry-run` | Preview what retention cleanup would delete |
| `just cleanup` | Delete old articles/stories per retention policy |
| `just backup` | Create a timestamped SQLite backup in `backups/` |
| `just export-digest` | Export today's verified stories as Markdown |

---

## Architecture

The pipeline runs in stages. Each stage is a Python module under `backend/app/`:

```
RSS / SEC feeds
      │
      ▼
┌─────────────┐   app/ingestion/        Fetch articles from configured sources.
│    fetch    │   connectors/*.py       One connector per source kind (rss, sec_edgar).
└──────┬──────┘   models/news.py        Persists to: articles, fetch_runs
       │
       ▼
┌─────────────┐   app/dedup/            Exact-hash and fuzzy-title dedup.
│    dedup    │   dedup.py              Near-duplicate articles → same cluster.
└──────┬──────┘                         Persists to: story_clusters, cluster_members
       │
       ▼
┌─────────────┐   app/corroboration/    Cross-source signal scoring.
│ corroborate │   corroborate.py        Sets article_count, publisher_count on clusters.
└──────┬──────┘
       │
       ▼
┌─────────────┐   app/llm/classify.py   Haiku 4.5 — classify event_type, is_opinion,
│  classify   │   prompts/classify_v1   injection_suspected. Quarantines suspicious
└──────┬──────┘                         articles. Persists to: story_clusters (updated)
       │
       ▼
┌─────────────┐   app/llm/summarize.py  Sonnet 4.6 — Bulgarian summary + key facts
│  summarize  │   prompts/summarize_v1  with verbatim English quotes.
└──────┬──────┘                         Persists to: stories, story_facts, fact_evidence
       │                                Archives superseded stories to: story_versions
       ▼
┌─────────────┐   app/llm/verify.py     Sonnet 4.6 — dual-level fact verification.
│   verify    │   prompts/verify_v1     Level 1: code checks (quote presence, no numbers
└─────────────┘                         not in source). Level 2: LLM judge.
                                        Persists to: verification_log
```

Key invariants (CLAUDE.md):
- The LLM never introduces facts from training data — only from passed article text.
- Every fact carries a verbatim English quote verified by `str.find()` before save.
- LLM calls receive **no tools** (article text is untrusted input, not instructions).
- Every LLM output is validated against a pydantic v2 schema; invalid → rejected, never repaired.
- Every stored summary records `model_version` and `prompt_version`.

---

## Project structure

```
.
├── backend/          Python 3.12 · FastAPI · SQLAlchemy 2 · SQLite
│   ├── app/
│   │   ├── api/          FastAPI routers (pipeline, stories, debug)
│   │   ├── core/         Config, DB, logging, budget guard
│   │   ├── ingestion/    Source connectors + fetch runner
│   │   ├── dedup/        Clustering and deduplication
│   │   ├── corroboration/ Cross-source scoring
│   │   ├── llm/          Client, classify, summarize, verify, spotlighting
│   │   ├── models/       SQLAlchemy ORM models
│   │   └── maintenance.py Cleanup, backup, digest export
│   ├── alembic/      Database migrations (0001–0007)
│   └── tests/
│       └── evals/    Golden-case eval harness (36 cases)
├── frontend/         React 18 · Vite · TypeScript · TanStack Query
├── e2e/              Playwright end-to-end tests
├── config.yaml       Sources, watchlist, budget limits, retention policy
├── .env              API keys (never committed)
├── CLAUDE.md         AI safety rules (immutable)
├── DECISIONS.md      Architecture Decision Records (ADR-001 – ADR-027)
└── QUESTIONS.md      Open questions pending clarification
```

---

## Adding a new source

1. Create `backend/app/ingestion/connectors/<name>.py` implementing `BaseConnector`
   (see `rss_connector.py` or `sec_edgar_connector.py` for examples).
2. Register the connector class in `backend/app/ingestion/fetch_runner.py`
   in the `_CONNECTOR_REGISTRY` dict, keyed by the `kind` string.
3. Add the source to `config.yaml` under `sources:` with the matching `kind:` value.
4. Add a fixture and at least one unit test in `backend/tests/test_<name>_connector.py`.
5. Run `just test` to verify everything passes.

---

## Changing a prompt

1. Edit the prompt file in `backend/app/llm/prompts/` (e.g. `summarize_v1.md`).
2. Restart the backend — `prompt_version` is computed at import time as
   `sha256(prompt_text)[:8]`, so it updates automatically.
3. Run `just eval-replay` to verify the eval harness still passes against recorded
   responses. If the prompt change is intentional and causes eval drift, update the
   golden cases in `backend/tests/evals/cases/`.
4. Commit with a message that includes the new prompt hash (shown in logs as
   `prompt_version`), e.g. `update summarize prompt (summarize_v1:a3f8b2c1)`.

---

## Operations

### Retention cleanup

```powershell
just cleanup-dry-run    # preview what would be deleted (safe to run anytime)
just cleanup            # delete old data per config.yaml retention policy
```

Retention policy (configurable in `config.yaml`):
- Raw articles: 90 days (skips articles cited in `fact_evidence`)
- Stories + facts + evidence: 365 days
- `verification_log`: never deleted (permanent audit trail)

### Backup

```powershell
just backup             # writes backups/news_YYYYMMDD_HHMMSS.db
```

Uses `sqlite3.Connection.backup()` — safe to run while the backend is running.

### Digest export

```powershell
just export-digest                      # today's verified stories → exports/digest_YYYY-MM-DD.md
just export-digest-date 2026-10-06      # specific date
```

### Eval harness

```powershell
just eval-replay        # replay 36 golden cases against recorded responses (free, CI-safe)
just eval               # run against live API (costs money — prompts for confirmation)
```

---

## Sprint roadmap

| Sprint | Focus | Status |
|---|---|---|
| Sprint 0 | Skeleton, /health, Hello page | Done |
| Sprint 1 | Article ingestion (Yahoo Finance RSS, Finnhub) | Done |
| Sprint 2 | Deduplication and clustering | Done |
| Sprint 3 | AI classification (Haiku 4.5), budget guard, spotlighting | Done |
| Sprint 4 | AI summarization (Sonnet 4.6), story/fact/evidence tables | Done |
| Sprint 5 | Dual-level fact verification, verification_log | Done |
| Sprint 6 | Frontend news feed UI, story detail, watchlist | Done |
| Sprint 7 | Eval harness, 36 golden cases, replay mode | Done |
| Sprint 8 | SEC EDGAR connector, corroboration scoring | Done |
| Sprint 9 | Hardening: incremental LLM, cache, observability, maintenance | Done |
