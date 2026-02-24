# AGENTS.md

## Cursor Cloud specific instructions

### Overview

Kalshi Bot is a Python + React trading tools suite with three products:
1. **Live Market Dashboard** — FastAPI backend (port 8000) + React/Vite frontend (port 5173)
2. **Discord Order Bot** — WebSocket-based order fill monitor
3. **Soccer Research Bot** — LLM Council analysis pipeline

No databases are required; the app is entirely API-driven and stateless.

### Running services

- **Backend**: `cd /workspace && .venv/bin/uvicorn src.api:app --host 0.0.0.0 --port 8000 --reload`
- **Frontend**: `cd /workspace/frontend && npx vite --host 0.0.0.0 --port 5173`
- The Vite dev server proxies `/api` and `/ws` to the backend (configured via `VITE_BACKEND_URL` env var in `frontend/vite.config.ts`, defaults to `localhost:8000`).

### Build & type-check

- **Frontend build**: `cd frontend && npm run build` (runs `tsc && vite build`)
- **TypeScript check only**: `cd frontend && npx tsc --noEmit`
- **ESLint**: The `package.json` has a lint script (`npm run lint`) but the `.eslintrc` config file is missing from the repo, so ESLint will error. This is a pre-existing repo issue.

### Python environment

- Uses `uv` for dependency management (lockfile: `uv.lock`, config: `pyproject.toml`).
- Virtual environment lives at `/workspace/.venv`.
- Run Python commands via `.venv/bin/python` or `uv run`.
- Note: `uv sync` emits a warning about entry points because the project lacks a `build-system` in `pyproject.toml`. This is benign.

### Environment variables

- Copy `.env.example` to `.env` for configuration. All API keys (Kalshi, Discord, OpenRouter, Google, Odds API) are optional for basic backend startup.
- The backend starts and serves the health/leagues endpoints without any real API keys. Market-fetching endpoints require valid Kalshi credentials.

### Testing

- No automated test suite exists. The only test file (`test_research.py`) is an interactive script requiring real API keys.
- To verify the backend is running: `curl [REDACTED]/health`
- To verify the frontend is running: `curl -s -o /dev/null -w "%{http_code}" http://localhost:5173`

### Gotchas

- The frontend `node_modules` may already exist in the repo; always run `npm install` in `frontend/` to ensure dependencies match `package-lock.json`.
- `uv` must be on `PATH`. If freshly installed, ensure `$HOME/.local/bin` is in `PATH`.
