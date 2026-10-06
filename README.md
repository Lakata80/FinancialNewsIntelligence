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

---

## Project structure

```
.
├── backend/          Python 3.12 · FastAPI · SQLAlchemy 2 · SQLite
│   ├── app/
│   │   ├── core/     Domain logic (mypy strict)
│   │   └── main.py   FastAPI application entry point
│   └── tests/
├── frontend/         React 18 · Vite · TypeScript
├── e2e/              Playwright end-to-end tests
├── tests/fixtures/   Recorded articles for deterministic tests
├── config.yaml       Watchlist, sources, budget limits
├── .env              API keys (never committed)
├── CLAUDE.md         AI safety rules (immutable)
├── DECISIONS.md      Architecture Decision Records
└── QUESTIONS.md      Open questions pending clarification
```

---

## Sprint roadmap

- **Sprint 0** (current) — Skeleton, /health endpoint, Hello page
- Sprint 1 — Article ingestion (Yahoo Finance RSS, Finnhub)
- Sprint 2 — Deduplication and clustering
- Sprint 3 — AI summarization with verification layer
- Sprint 4 — Frontend news feed UI
