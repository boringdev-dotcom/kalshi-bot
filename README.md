# Kalshi Soccer Under-No Bot

Event-driven soccer trading system. A **non-agentic Python watcher** discovers Kalshi totals for the next 6 hours, polls live games every 15 seconds, and wakes two Grok agents (**Pundit** and **Kalshi**) only on goal, half-time, second-half start, red card, or full-time.

Paper mode is the default. No periodic LLM loops.

## Layout

```
kalshi_bot/
  kalshi/          RSA auth, REST (orders/positions), WS tickers
  feeds/           FotMob, ESPN, fixture matcher, pre-match stats
  watcher/         6h discovery, 15s pollers, event detector
  agents/          Pundit + Kalshi on xAI Grok, shared SQLite memory
  notify/          Telegram alerts and /games /held /status /pause /resume
  api/             FastAPI read API + WebSocket
  playbook.py      Conservative placeholder thresholds
  store.py         SQLite journal
frontend/          Vite + React + TypeScript dashboard
scripts/import_history.py
```

## Setup

```bash
uv venv && uv sync --extra dev
cp .env.example .env
```

Required for live discovery and orders: `KALSHI_API_KEY_ID`, `KALSHI_PRIVATE_KEY_PEM`.  
Required for agents: `XAI_API_KEY`.  
Optional: `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`.

```bash
uv run kalshi-bot run-all          # API + watcher
uv run kalshi-bot run-worker       # watcher only
uv run kalshi-bot run-api          # dashboard API only
uv run pytest
uv run python scripts/import_history.py
```

Dashboard:

```bash
cd frontend && npm install && npm run dev
```

Vite proxies `/api` and `/ws` to `http://127.0.0.1:8000`.

## Playbook

Playbook is seeded from `docs/pattern-report.md`: buy No only, minute 60–92, rem ≤ 2 (rem=3 only on Over ≥ 4.5 tier 1), No ask 80–92¢, flatten on goal / rem→1 / −12¢, 150 contracts/match and 600/day, tier 1–2 only, 1H totals off, paper default. Portfolio GETs are signed path-only.

## Render

`render.yaml` defines a background worker, a FastAPI web service (`0.0.0.0:$PORT`), and a static SPA. SQLite is per-instance; use `run-all` or a single disk until you move the journal.

## Telegram

`/games` `/held` `/status` `/pause` `/resume`
