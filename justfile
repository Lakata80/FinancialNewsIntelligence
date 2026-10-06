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
