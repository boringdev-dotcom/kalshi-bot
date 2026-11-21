# Courtside API

Backend runs on `http://localhost:8000`. The Vite dev server proxies `/api` and `/ws` to it.
All shapes are defined in [`frontend/src/types.ts`](../frontend/src/types.ts).

## REST

| Method | Path | Body | Returns |
|---|---|---|---|
| GET | `/api/state` | | `AppState` |
| PUT | `/api/settings` | `Partial<Settings>` | `AppState` |
| POST | `/api/agent/start` | | `AppState` |
| POST | `/api/agent/pause` | | `AppState` |
| GET | `/api/games` | | `Game[]` (live first, then pre, then final) |
| GET | `/api/games/{id}` | | `GameDetail` (includes quarter totals and spreads, the game chart `timeline`, per-quarter `quarter_timelines`, and `players`: every player's line with who is on the floor) |
| GET | `/api/positions` | | `Position[]` |
| POST | `/api/positions/{id}/close` | | `Trade` |
| GET | `/api/trades?limit=100` | | `Trade[]` (newest first) |
| GET | `/api/decisions?limit=100&game_id=` | | `Decision[]` (newest first) |
| POST | `/api/orders` | `OrderRequest` (any ticker: game total, quarter total or quarter spread) | `Position` |
| GET | `/api/playbook` | | `Strategy[]` |
| PUT | `/api/playbook/{id}` | `{ enabled?: boolean, params?: Record<string, number> }` | `Strategy` |
| GET | `/api/memory?kind=&q=` | | `Memory[]` (pinned first, then newest) |
| POST | `/api/memory` | `{ text: string }` (adds guidance) | `Memory` |
| PATCH | `/api/memory/{id}` | `{ pinned?: boolean, text?: string, importance?: number }` | `Memory` |
| DELETE | `/api/memory/{id}` | | `{ ok: true }` |
| GET | `/api/learning` | | `LearningState` |
| POST | `/api/sim/train` | `{ episodes: number }` | `TrainResult` |
| POST | `/api/sim/reset` | | `AppState` (new slate of simulated games) |
| GET | `/api/soccer` | | `{ leagues, matches: SoccerMatch[], account, positions, feeds, updated_at }` |
| GET | `/api/soccer/matches/{id}` | | `{ match, markets, first_half_line, events, stats, commentary, prior, positions, account }` |
| POST | `/api/soccer/orders` | `{ ticker, side: "yes" \| "no", contracts, price }` | `SoccerPosition` (paper or live, by the site's trading mode) |
| POST | `/api/soccer/positions/{id}/close` | | `SoccerTrade` (sold at the bid) |
| GET | `/api/soccer/trades?limit=50` | | `SoccerTrade[]` (newest first) |
| POST | `/api/favs` | `{ game_id }` (an NBA game id or a soccer match id) | `{ game, generated_at, summary, picks: [{ ticker, side, label, where, ask, confidence, model_p, edge, reason }], candidates, dropped }`: picks are 0.85-0.90 confidence with ask below it |
| GET | `/api/chat/history` | | `ChatMessage[]` (oldest first) |
| POST | `/api/chat` | `{ message: string, game_id?: string, analysis?: boolean }` (with `game_id`, a fresh briefing on that game and its full play-by-play go to Claude with the message; a soccer match id (`soccer-…`) sends the match briefing and its commentary instead; `analysis` asks for a full read) | SSE stream of `ChatEvent` |
| DELETE | `/api/chat/history` | | `{ ok: true }` |

Errors are `{ "detail": string }` with a 4xx/5xx status.

Switching `trading_mode` to `live` is rejected (400) unless Kalshi keys are present and `data_source` is `live`.

## WebSocket `/ws`

On connect the server sends `state`, `games` and `positions`. After that:

- `games` every tick (about once a second in sim, every few seconds live)
- `positions` and `account` whenever marks move
- `decision`, `trade`, `memory` when one is created
- `state` when settings, health or agent status change
- `toast` for things the user should notice (fills, exits, limit hits)
