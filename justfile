set shell := ["powershell", "-Command"]

# Install all dependencies
setup:
    Set-Location backend; uv sync
    Set-Location frontend; npm install
    Set-Location e2e; npm install

# Start backend only (port 8000)
dev-backend:
    Set-Location backend; uv run uvicorn app.main:app --reload --port 8000

# Start frontend only (port 5173)
dev-frontend:
    Set-Location frontend; npm run dev

# Start backend in a new window, frontend in current window
dev:
    Start-Process powershell -ArgumentList "-NoExit", "-Command", "Set-Location '{{justfile_directory()}}/backend'; uv run uvicorn app.main:app --reload --port 8000"
    Set-Location frontend; npm run dev

# Run backend tests with coverage
test:
    Set-Location backend; uv run pytest tests/ -v --cov=app --cov-report=term-missing

# Lint and type-check backend
lint:
    Set-Location backend; uv run ruff check app tests
    Set-Location backend; uv run mypy app

# Run e2e tests (requires `just dev` running in another terminal)
e2e:
    Set-Location e2e; npx playwright test

# Run evaluation suite against real API (costs money — prompts for confirmation)
eval:
    Set-Location backend; uv run python -m tests.evals.runner --mode live

# Run evaluation suite using recorded responses (free, safe for CI)
eval-replay:
    Set-Location backend; uv run python -m tests.evals.runner --mode replay

# Delete old articles/stories per retention policy (dry-run: shows what would be deleted)
cleanup:
    Set-Location backend; uv run python -m app.maintenance cleanup

# Preview cleanup without making any changes
cleanup-dry-run:
    Set-Location backend; uv run python -m app.maintenance cleanup --dry-run

# Create a timestamped SQLite backup in backups/
backup:
    Set-Location backend; uv run python -m app.maintenance backup

# Export today's verified stories as a Markdown digest to exports/
export-digest:
    Set-Location backend; uv run python -m app.maintenance export-digest

# Export a specific date's digest (usage: just export-digest-date 2026-10-06)
export-digest-date DATE:
    Set-Location backend; uv run python -m app.maintenance export-digest --date {{DATE}}
