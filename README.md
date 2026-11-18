# Courtside

A trading desk for live NBA total-points markets on Kalshi, with an agent that trades a playbook you set, manages risk on open positions, remembers what happened, and learns from its results.

It runs out of the box on simulated games with paper money. Point it at live data to paper-trade real Kalshi prices, and arm live trading when you trust it.

## Run it

```bash
uv sync
uv run courtside            # API + engine on http://localhost:8000
```

```bash
cd frontend
npm install
npm run dev                 # UI on http://localhost:5173
```

After `npm run build`, the API serves the built UI itself at `http://localhost:8000`.

```bash
uv run pytest               # 18 tests: model, rules, learner, memory, engine, feeds, API, sign-in
```

## Configuration

Copy `.env.example` to `.env`. Everything is optional; each key unlocks one thing.

| Key | Unlocks |
|---|---|
| `KALSHI_API_KEY_ID`, `KALSHI_PRIVATE_KEY_PEM`, `KALSHI_ENV` | Live trading. Market data is public and needs no key. |
| `ANTHROPIC_API_KEY` | Chat with the agent, plain-language guidance that changes the playbook, a pre-trade review, post-trade reflection. |
| `ODDS_API_KEY` | FanDuel totals, spreads and moneylines via [The Odds API](https://the-odds-api.com). Without it the desk shows ESPN's pregame consensus line and measures the cushion from the Kalshi ladder's own 50/50 point. |

## Hosting (Render)

The repo deploys as two services from one branch:

| Service | What it runs | Notes |
|---|---|---|
| API (Python) | `uv sync --frozen`, then `uv run python -m src.main` | The engine and API. `src/main.py` is a thin shim into `courtside`. |
| UI (Docker, root `frontend/`) | `frontend/Dockerfile` | nginx serves the built app and proxies `/api` and `/ws` to the API, so the browser sees one origin. Set `BACKEND_URL` and `BACKEND_HOST` if the API's address changes. |

Set these on the **API** service:

- `APP_PASSWORD` — required. The desk holds your Kalshi keys and can place orders, so a hosted copy refuses to serve anything until a password is set, then asks for it at sign-in.
- `KALSHI_API_KEY_ID`, `KALSHI_PRIVATE_KEY_PEM`, `KALSHI_ENV`, `ANTHROPIC_API_KEY`, `ODDS_API_KEY` as above.
- `DB_PATH` pointing at a persistent disk (for example `/var/data/courtside.db`). Without a disk the database lives on the instance's temporary filesystem and **every deploy or restart wipes memory, learning, trade history and settings**.

The Odds API bills one credit per market per request. The feed asks for the full board hourly while idle, totals only every three minutes while games are live, and every 20 seconds once a game reaches the end of Q3. Expect a few hundred credits on a full NBA night; the remaining balance shows under Settings.

## The four pages

- **Desk** — live games, the selected game's scorebug, projection chart and Kalshi totals ladder (price, model probability, edge), a one-click order ticket, and the agent's decision feed and chat.
- **Portfolio** — account, open positions with live win probability and risk flags, closed trades with what holding would have paid.
- **Brain** — the playbook sliders, guidance and memory, and what the learner has concluded, plus a training gym.
- **Settings** — paper/live, simulated/live data, risk limits, connection health.

## How the agent works

**The play.** In the fourth quarter, buy the under on a strike well above the live betting line (line 240, buy under 250 or 252) at roughly 90-96c: risk about $300 to make about $20. Sell for a small loss if the game starts threatening the number.

**The model** (`courtside/model/totals.py`). Projects the final total from score, clock, margin, the pregame total and the live FanDuel line, as a mixture of three outcomes: the game stays calm, it turns into a close late foul game, or it goes to overtime. Every Kalshi strike gets a fair probability from that; an open position gets a live win probability.

**The rules** (`agent/policy.py`, tuned in `agent/playbook.py`). Entry: time window, cushion above the line, price band, a model veto for clear overpays, skip tight late games. Exit: win probability under a floor, a stop below entry, an overtime guard, a take-profit near 99c.

**The learner** (`agent/learner.py`). A contextual bandit. Each situation (cushion x time left x how close the game is) starts from the model's expected return and is pulled toward realised results; a spot that keeps losing gets vetoed, but only once it has at least eight trades behind it. Exit style (tight / balanced / patient) is chosen by Thompson sampling on realised return. Every early exit is graded against what holding would have paid once the game is final.

**Memory** (`agent/memory.py`). Guidance from you, lessons from results, and a record of each trade. Relevant memories are recalled before each entry and are credited or debited by how the trade turns out.

**Claude** (`agent/brain.py`). Optional. Chats over the desk's real data with tools, turns guidance into playbook changes, gives a fast second opinion before each real-market entry, and writes lessons after notable real-market results. It is not called for simulated games, and exits never wait on it.

## Safety

- Paper mode is the default. Live needs Kalshi keys and live data, and switching to it pauses the agent so arming real money never also starts it trading.
- Hard caps in Settings: stake per trade, open positions, total exposure, daily loss.
- Positions you open by hand are never auto-exited.
- The agent takes at most one position per game and does not re-enter a game it exited.

## Things to know

- **The simulator is a sandbox, not evidence.** Its games, market and biases are invented (see the docstring in `feeds/sim.py`). What the agent learns there stays there: real-market decisions use real results only.
- **The model's constants are league-level starting points**, not fitted to historical data. The learner corrects for where they are off, which takes real trades.
- **Live order placement is written to Kalshi's V2 order API** (`POST /portfolio/events/orders`) and the request translation is unit-tested, but it has not sent a real order. Make the first live trade a small one and check it on Kalshi.
- Kalshi fees are modelled with the standard taker formula; check your actual fills.
