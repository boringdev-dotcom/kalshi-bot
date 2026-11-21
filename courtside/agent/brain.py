"""Claude as the agent's reasoning layer.

Three jobs, three different speeds:

* review_entry  - a fast second opinion before an order goes out (fast model,
                  structured verdict, hard timeout so the loop never waits long)
* reflect       - turn a notable result into a lesson worth remembering
* chat          - talk with the user: answer questions from the desk's real
                  data, take guidance, and change the playbook when told to

The numeric model and the rules stay in charge of speed-critical exits. Claude
adds judgement on top; if it is unavailable everything still runs.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, AsyncIterator, Optional

import anthropic

from ..config import Config
from ..domain import Game, now_iso
from ..feeds.patterns import pattern_keys, pattern_texts, play_lines
from ..model.quarters import implied_margin, implied_quarter_total
from ..model.totals import implied_total
from .playbook import Q4_UNDER, STRATEGIES

log = logging.getLogger(__name__)

FALLBACK_BETA = "server-side-fallback-2026-07-01"
MAX_TOOL_ROUNDS = 8

CHAT_SYSTEM = """You are the reasoning layer of Courtside, a personal trading desk one person built to trade NBA total-points markets on Kalshi. You are talking with that person: the owner and only user. They are an experienced bettor; talk to them like a sharp colleague on the desk, not like a support bot.

How the desk works
- A numeric model projects each game's final total from score, clock, margin and the live FanDuel line, and prices every Kalshi strike (YES = over, NO = under).
- The owner's core play is the fourth-quarter under: late in the game, buy the under on a strike well above the live betting line (line 240, buy under 250 or 252) at roughly 90-96 cents, risking about $300 to make about $20. The danger is a late scoring burst, a foul-fest in a close game, or overtime (20-plus extra points), so the agent sells for a small loss when risk rises rather than riding to a full loss.
- A playbook holds the tunable parameters for that play. An automated loop applies them every second or two: it enters, monitors, exits and settles without you.
- A learner tracks results by situation (cushion, time left, how close the game is) and by exit style, and shifts behaviour toward what has actually made money.
- Memory holds the owner's standing guidance, lessons from past trades, and a record of each trade.
- Each game also carries what is happening on the floor, read from ESPN's play-by-play (made-up players in practice games): who is on the court, team fouls and who is in the bonus, players in foul trouble, hot shooters, runs, scoring bursts and droughts, benches in, and who is out tonight. get_games has the headline notes; get_players has the full box; get_plays has every play of a game, live or finished (finished real games are archived with their play-by-play and box score, so you can go back to them). Every trade, the owner's and the agent's, saves the patterns that were showing when it was placed, and get_learning groups results by pattern. The owner trades partly so the agent can learn from their reads: when they ask what to make of a pattern, answer from that record and the game in front of them.
- Quarter markets (total and spread for each of Q1-Q4; Q4 excludes overtime) are the owner's to trade by hand. The automated loop places no orders there. It keeps a shadow book instead: early in each quarter and again with about six minutes left it records what every quarter market cost and what the model thought, then scores them when the quarter ends. get_learning returns that book and the owner's own quarter record. If they ask whether to let the agent trade quarters, answer from those numbers and say plainly when there are too few to judge. In market data "over" always means the YES side and "under" the NO side; for a spread, YES is the named team winning the quarter by more than the line. Use the labels the tools give you.

Your tools read and change that real system. Use them: never state a position, price, result or setting from memory of this conversation when a tool can tell you the current truth. The desk snapshot at the top of each message is fresh as of that message.

When the owner gives a standing instruction ("be more careful in one-possession games", "never trade back-to-backs", "size down on Fridays"):
1. Save it with save_guidance, close to their own words, with tags that will match the situations it applies to.
2. If it maps onto playbook parameters, change them with update_playbook and tell them exactly what moved (old value to new value) and what that does in practice.
3. If no parameter captures it, say so plainly: it will be weighed in the pre-trade review, which is a judgement call rather than a hard rule. Do not claim a guarantee the system cannot make.

When they ask why something happened, look at the decisions and trades and explain from those records, with the numbers. If the records do not explain it, say what is missing.

You can place and close orders when asked. Check the trading mode first: in live mode these are real-money orders, so confirm ticker, side and size back to the owner in your reply. Orders are capped by their risk limits.

Be direct and concrete. Lead with the answer. Use the actual numbers. Say when the sample is too small to conclude anything; a handful of trades proves nothing either way, and simulated results say nothing about real markets. Keep replies short unless they ask for depth. Plain text with light markdown; no headers for short answers."""

ANALYSIS_ASK = """The owner pressed "Agent analysis" on this game. Be their thinking partner, not a signal service. Use the game briefing and the full play-by-play above (fresh as of now); call tools only if something is missing. Read the plays, not just the summary numbers: who is getting the ball, how the scoring is coming (threes, free throws, the paint), turnovers, how each team has answered runs, who has been subbed in and why. Patterns the summary does not name are often the useful ones.

1. Lead with your read in one or two sentences: where the full-game total, and the quarter in play, look to be heading against the line, and how sure you are.
2. What on the floor matters right now and which way it pushes scoring: the bonus, foul trouble, who is on or off, runs, pace, a close finish. Say plainly what you know and what you are inferring.
3. If they hold positions in this game, how each one looks now and what would make you want out.
4. Where prices look off to you against the model and what is happening on the floor, if anywhere, with the numbers, and the best case against your view. If nothing looks off, say so.
5. What to watch over the next few minutes that would change the read.

Keep it tight: short paragraphs or a few bullets, real numbers, no boilerplate caveats. End with one question back to them if their read would sharpen yours. Do not place or close any orders unless they ask."""

REVIEW_SYSTEM = """You review one proposed trade for an automated NBA totals desk before the order is sent. The trade already passed the numeric rules; your job is to catch what the rules cannot see and to apply the owner's standing guidance and past lessons.

The play: in the fourth quarter, buy the under on a total well above the live line. It wins small most of the time and loses big rarely; the killers are late fouling in close games, a pace that is still accelerating, and overtime.

`on_the_floor` lists what is happening in the game right now in plain sentences: who is in the bonus, players in foul trouble, hot shooters, runs, scoring bursts or droughts, benches in. A team in the bonus early in the fourth means more free throws, which pushes the total up.

Approve unless you see a specific, stated reason not to: guidance or a lesson that clearly applies to this situation, or a concrete risk in the numbers the rules underweighted. Do not veto on general caution; the rules already require an edge. If the trade is fine but a memory suggests caution, approve with a smaller size_multiplier (0.25 to 1). Give the reason in one or two plain sentences that name the specific factor."""

REFLECT_SYSTEM = """You write the lessons an NBA totals trading agent keeps in long-term memory. You are given one finished trade with its context and what happened. Write a single lesson the agent can act on next time it sees a similar spot.

A good lesson names the situation (cushion, clock, margin, pace, and what was happening on the floor when it matters: bonus, foul trouble, a run), says what happened, and says what to do differently or keep doing. It is specific and falsifiable. One trade is weak evidence: phrase it as a pattern to watch, not a law. Two or three sentences. Tags should be short lowercase situation words that will match similar future spots. Importance is 0-1: full losses and clear saves high, routine noise low."""

REVIEW_SCHEMA = {
    "type": "object",
    "properties": {
        "approve": {"type": "boolean"},
        "size_multiplier": {"type": "number"},
        "reason": {"type": "string"},
    },
    "required": ["approve", "size_multiplier", "reason"],
    "additionalProperties": False,
}

REFLECT_SCHEMA = {
    "type": "object",
    "properties": {
        "lesson": {"type": "string"},
        "tags": {"type": "array", "items": {"type": "string"}},
        "importance": {"type": "number"},
    },
    "required": ["lesson", "tags", "importance"],
    "additionalProperties": False,
}


def _tool(name: str, description: str, properties: Optional[dict[str, Any]] = None, required: Optional[list[str]] = None) -> dict[str, Any]:
    return {
        "name": name,
        "description": description,
        "eager_input_streaming": True,
        "input_schema": {
            "type": "object",
            "properties": properties or {},
            "required": required or [],
            "additionalProperties": False,
        },
    }


_PARAM_KEYS = ", ".join(s.key for s in STRATEGIES[Q4_UNDER]["specs"])

TOOLS = [
    _tool("get_games", "Current games: score, clock, projection, FanDuel line, risk flags, and the Kalshi under prices nearest the action."),
    _tool("get_quarter_markets", "Tradable quarter totals and spreads for one game: every line with both sides' labels, prices and the model's probability.",
          {"game": {"type": "string", "description": "Team abbreviation or game label, e.g. 'CLE' or 'MEM @ CLE'"},
           "quarter": {"type": "integer", "enum": [1, 2, 3, 4]}},
          ["game", "quarter"]),
    _tool("get_players", "Who is on the floor for one game and every player's line so far: minutes, points, shooting, fouls, plus-minus, plus team fouls this quarter and who is in the bonus.",
          {"game": {"type": "string", "description": "Team abbreviation or game label, e.g. 'CLE' or 'MEM @ CLE'"}},
          ["game"]),
    _tool("get_plays", "Every play of one game, oldest first, one per line with quarter, clock, team and the away-home score after the play. Works for games on the board and for finished real games in the archive (the most recent game matching).",
          {"game": {"type": "string", "description": "Team abbreviation or game label, e.g. 'CLE' or 'MEM @ CLE'"},
           "quarter": {"type": "integer", "description": "Optional: only this period (5 = first overtime)"}},
          ["game"]),
    _tool("get_positions", "Open positions with live mark, P&L, current win probability and risk flags."),
    _tool("get_trades", "Closed trades, newest first, with exit reason and (for early exits on finished games) whether selling beat holding.",
          {"limit": {"type": "integer", "description": "How many, default 20"}}),
    _tool("get_decisions", "The agent's decision log, newest first: entries, skips, holds and exits, each with its reasoning and numbers.",
          {"limit": {"type": "integer", "description": "How many, default 20"}, "game": {"type": "string", "description": "Optional team abbreviation or game label to filter by"}}),
    _tool("search_memory", "Search long-term memory (guidance, lessons, trade episodes) by words or tags.",
          {"query": {"type": "string"}}, ["query"]),
    _tool("save_guidance", "Save a standing instruction from the owner so it is recalled before future trades.",
          {"text": {"type": "string", "description": "The instruction, close to the owner's words"},
           "tags": {"type": "array", "items": {"type": "string"}, "description": "Situation tags it applies to, e.g. close_game, ot_risk, late, hot_pace, blowout, a team abbreviation, or a floor pattern: pattern:bonus_early, pattern:bonus, pattern:foul_trouble, pattern:hot_hand, pattern:run, pattern:scoring_hot, pattern:scoring_cold, pattern:bench_in. Leave empty for guidance that always applies."},
           "pinned": {"type": "boolean", "description": "Pin so it is always recalled"}},
          ["text"]),
    _tool("forget_memory", "Delete a memory by id.", {"memory_id": {"type": "integer"}}, ["memory_id"]),
    _tool("get_playbook", "The strategy parameters as currently set, with ranges and what each one does."),
    _tool("update_playbook", f"Change strategy parameters and/or turn the strategy on or off. Valid keys: {_PARAM_KEYS}. Values are clamped to each parameter's range.",
          {"changes": {"type": "array", "items": {"type": "object", "properties": {"key": {"type": "string"}, "value": {"type": "number"}}, "required": ["key", "value"], "additionalProperties": False}},
           "enabled": {"type": "boolean"}}),
    _tool("get_learning", "What the learner has concluded: results by situation, exit-style performance, calibration, overall record."),
    _tool("set_agent", "Start or pause the automated trading loop.", {"enabled": {"type": "boolean"}}, ["enabled"]),
    _tool("close_position", "Sell an open position at the current bid.", {"position_id": {"type": "integer"}}, ["position_id"]),
    _tool("place_order", "Buy one side of any Kalshi market on the desk (game total, quarter total or quarter spread) at the current ask, on the owner's instruction. Capped by the max stake per trade.",
          {"ticker": {"type": "string"}, "side": {"type": "string", "enum": ["under", "over"], "description": "'over' buys the YES side, 'under' the NO side"}, "stake": {"type": "number", "description": "Dollars to put down"}},
          ["ticker", "side", "stake"]),
]

_TYPES = {"string": str, "integer": int, "number": (int, float), "boolean": bool, "array": list, "object": dict}


def validate(schema: dict[str, Any], value: Any) -> Optional[str]:
    """Minimal JSON-schema check for tool inputs. Returns an error string or None.

    Tool inputs are streamed eagerly, so the API does not validate them for us.
    """
    expected = _TYPES.get(schema.get("type", ""), object)
    if not isinstance(value, expected) or (schema.get("type") in ("integer", "number") and isinstance(value, bool)):
        return f"expected {schema.get('type')}"
    if "enum" in schema and value not in schema["enum"]:
        return f"must be one of {schema['enum']}"
    if schema.get("type") == "object":
        for key in schema.get("required", []):
            if key not in value:
                return f"missing '{key}'"
        for key, item in value.items():
            sub = schema.get("properties", {}).get(key)
            if sub is None:
                return f"unknown field '{key}'"
            err = validate(sub, item)
            if err:
                return f"{key}: {err}"
    if schema.get("type") == "array":
        for item in value:
            err = validate(schema.get("items", {}), item)
            if err:
                return err
    return None


class Brain:
    def __init__(self, cfg: Config, engine: Any):
        self.cfg = cfg
        self.engine = engine
        self.client: Optional[anthropic.AsyncAnthropic] = None
        if cfg.has_claude:
            self.client = anthropic.AsyncAnthropic(
                api_key=cfg.anthropic_api_key or None, auth_token=cfg.anthropic_auth_token or None
            )
        self._chat_lock = asyncio.Lock()

    @property
    def available(self) -> bool:
        return self.client is not None

    # ---------------------------------------------------------- pre-trade review
    async def review_entry(self, game: Game, plan: dict[str, Any], playbook: str) -> Optional[dict[str, Any]]:
        """A fast yes/no on a proposed entry. None means 'no opinion' and the rules decide."""
        cand, view = plan["cand"], plan["view"]
        proposal = {
            "game": game.label,
            "state": {"clock": f"Q{game.period} {game.clock}", "total": game.total, "margin": game.margin,
                      "projection": game.projection.mean if game.projection else None,
                      "ot_chance": game.projection.p_ot if game.projection else None,
                      "pace_per_48": game.projection.pace if game.projection else None,
                      "pregame_total": game.pregame_total, "risk_flags": game.risk.flags,
                      "on_the_floor": pattern_texts(game)},
            "trade": {"buy": f"under {cand.rung.strike:g}", "price_cents": cand.price, "line": cand.reference,
                      "line_source": cand.reference_source, "cushion_pts": round(cand.buffer, 1),
                      "model_win_prob": round(cand.p_model, 4), "edge": round(cand.edge, 4),
                      "stake": plan["cost"], "exit_profile": plan["profile"]},
            "own_record_in_this_spot": {"trades": round(view["n"], 1), "mean_return": round(view["mean_return"], 4),
                                        "blended_expected_return": round(view["ev"], 4)},
            "playbook": playbook,
            "recalled_memories": [
                {"kind": m["kind"], "text": m["text"], "confidence": m["confidence"], "from_user": m["source"] == "user",
                 "simulated": m["simulated"]}
                for m in plan["memories"]
            ],
        }
        try:
            resp = await asyncio.wait_for(
                self.client.messages.create(
                    model=self.cfg.claude_fast_model,
                    max_tokens=2000,
                    system=REVIEW_SYSTEM,
                    output_config={"effort": "low", "format": {"type": "json_schema", "schema": REVIEW_SCHEMA}},
                    messages=[{"role": "user", "content": json.dumps(proposal)}],
                ),
                timeout=12,
            )
            if resp.stop_reason != "end_turn":
                return None
            verdict = json.loads(next(b.text for b in resp.content if b.type == "text"))
            return verdict if validate(REVIEW_SCHEMA, verdict) is None else None
        except (asyncio.TimeoutError, anthropic.APIError, StopIteration, json.JSONDecodeError) as exc:
            log.warning("entry review unavailable (%s); rules decide", type(exc).__name__)
            return None

    # ---------------------------------------------------------------- reflection
    async def reflect(self, row: dict[str, Any], facts: str) -> dict[str, Any]:
        similar = self.engine.memory.recall(self.engine._tags_for(row), text=facts, k=4, touch=False)
        payload = {
            "facts": facts,
            "trade": {k: row.get(k) for k in ("game_label", "side", "strike", "entry_price", "exit_price", "contracts",
                                              "cost", "pnl", "exit_reason", "exit_profile", "p_win_entry",
                                              "counterfactual_pnl", "exit_verdict", "final_total", "simulated")},
            "context_at_entry": row.get("context"),
            "playbook": self.engine.playbook.describe(),
            "existing_related_memories": [m["text"] for m in similar],
        }
        resp = await self.client.beta.messages.create(
            model=self.cfg.claude_model,
            max_tokens=4000,
            betas=[FALLBACK_BETA],
            fallbacks="default",
            system=REFLECT_SYSTEM,
            output_config={"effort": "medium", "format": {"type": "json_schema", "schema": REFLECT_SCHEMA}},
            messages=[{"role": "user", "content": json.dumps(payload, default=str)}],
        )
        if resp.stop_reason != "end_turn":
            raise RuntimeError(f"reflection stopped: {resp.stop_reason}")
        out = json.loads(next(b.text for b in resp.content if b.type == "text"))
        err = validate(REFLECT_SCHEMA, out)
        if err:
            raise ValueError(err)
        out["importance"] = min(max(float(out["importance"]), 0.0), 1.0)
        out["tags"] = [t.lower().strip() for t in out["tags"][:8]]
        return out

    # ---------------------------------------------------------------------- chat
    def history(self) -> list[dict[str, Any]]:
        return self.engine.db.query("SELECT id, role, text, ts, tools FROM chat ORDER BY id")

    def _snapshot(self) -> str:
        e = self.engine
        acct, s = e.account(), e.settings
        live = [g for g in e.games if g.state == "live"]
        lines = [
            f"mode={s['trading_mode']} data={s['data_source']} agent={'on' if s['agent_enabled'] else 'paused'} "
            f"equity=${acct['equity']:,.2f} today={acct['pnl_today']:+,.2f} record={acct['wins']}-{acct['losses']} "
            f"open={acct['open_positions']} exposure=${acct['exposure']:,.0f}",
            f"limits: stake<=${s['max_stake_per_trade']:g} positions<={s['max_open_positions']} "
            f"daily_loss<=${s['max_daily_loss']:g} exposure<=${s['max_total_exposure']:g}",
            f"playbook: {e.playbook.describe()}",
            "live games: " + ("; ".join(f"{g.label} Q{g.period} {g.clock} total {g.total} margin {g.margin}" for g in live[:8]) or "none"),
        ]
        return "[desk snapshot " + now_iso() + "]\n" + "\n".join(lines)

    def game_briefing(self, game: Game) -> dict[str, Any]:
        """Everything about one game in one place, for an analysis or a follow-up about it."""
        e = self.engine
        fd = game.fanduel
        ctx = game.context or {}
        ladder = sorted(game.ladder, key=lambda r: r.strike)
        anchor = (fd.total_line if fd and fd.total_line else None) or implied_total(ladder) or game.pregame_total or 0
        near = [r for r in ladder if abs(r.strike - anchor) <= 25 and (r.no_ask or r.yes_ask)][:16]
        quarters = []
        for view in game.quarter_view:
            markets = game.quarter_markets.get(view["segment"], {})
            quarters.append({
                **{k: view[k] for k in ("label", "status", "home_points", "away_points", "seconds_remaining", "projection")},
                "kalshi_total_line": implied_quarter_total(markets.get("total", [])),
                "kalshi_margin_line_home": implied_margin(markets.get("spread", []), game.home.abbr),
            })
        q_now = f"q{min(max(game.period, 1), 4)}"
        q_markets = game.quarter_markets.get(q_now, {})

        def rung_rows(rungs: list[Any], limit: int) -> list[dict[str, Any]]:
            rows = [r for r in rungs if r.yes_ask or r.no_ask]
            return [{"yes": r.label("over"), "yes_ask": r.yes_ask, "no": r.label("under"), "no_ask": r.no_ask,
                     "model_p_yes": round(1 - r.p_under, 3)} for r in rows[:limit]]

        players = [
            {k: p[k] for k in ("name", "team", "on_court", "starter", "points", "fgm", "fga", "tpm", "tpa", "ftm", "fta", "fouls", "plus_minus")}
            | {"minutes": round(p["minutes"])}
            for p in ctx.get("players", []) if p["minutes"] > 0 or p["on_court"]
        ]
        recalled = e.memory.recall(
            [game.home.abbr.lower(), game.away.abbr.lower()] + [f"pattern:{k}" for k in pattern_keys(game)],
            text=f"{game.label} {' '.join(pattern_texts(game))}", k=5, touch=False,
        )
        return {
            "game": game.label, "home": game.home.abbr, "away": game.away.abbr, "state": game.state,
            "clock": f"Q{game.period} {game.clock}" if 1 <= game.period <= 4 else ("OT " + game.clock if game.period > 4 else "pre-game"),
            "score": {game.away.abbr: game.away.score, game.home.abbr: game.home.score},
            "by_quarter": {game.away.abbr: game.away.quarters, game.home.abbr: game.home.quarters},
            "simulated": game.simulated,
            "pregame_total": game.pregame_total,
            "sportsbook": fd.__dict__ if fd else None,
            "kalshi_total_line": implied_total(ladder),
            "projection": game.projection.__dict__ if game.projection else None,
            "risk": {"level": game.risk.level, "flags": game.risk.flags},
            "on_the_floor": [{"text": n["text"], "pushes_scoring": n["lean"]} for n in ctx.get("notes", [])],
            "team_fouls_this_period": [{"team": t["abbr"], "fouls": t["fouls"], "next_foul_is_free_throws": t["penalty"],
                                         "points_last_5_min": t["last5"], "starters_on_floor": t["starters_on"]} for t in ctx.get("teams", [])],
            "out_tonight": ctx.get("out", []),
            "players": players,
            "full_game_ladder_near_line": [{"strike": r.strike, "under_ask": r.no_ask, "under_bid": r.no_bid, "over_ask": r.yes_ask,
                                            "over_bid": r.yes_bid, "model_p_under": round(r.p_under, 3)} for r in near],
            "quarters": quarters,
            f"{q_now}_markets": {"totals": rung_rows(q_markets.get("total", []), 12), "spreads": rung_rows(q_markets.get("spread", []), 12)},
            "my_positions_here": [
                {k: p[k] for k in ("label", "contracts", "entry_price", "mark_price", "cost", "pnl", "p_win", "p_win_entry", "opened_by")}
                for p in e.positions_api() if p["game_id"] == game.id
            ],
            "record_by_pattern": e._pattern_record(),
            "recalled_memories": [{"kind": m["kind"], "text": m["text"], "from_owner": m["source"] == "user"} for m in recalled],
        }

    async def chat(self, message: str, game_id: Optional[str] = None, analysis: bool = False) -> AsyncIterator[dict[str, Any]]:
        """Run one user turn. Yields ChatEvent dicts; persists both sides of the turn.

        With `game_id`, a fresh briefing on that game rides along with the message (it is not
        stored in the transcript). With `analysis`, the turn asks for a full read of the game.
        """
        db = self.engine.db
        if not self.available:
            yield {"type": "error", "message": "Claude is not connected. Add ANTHROPIC_API_KEY to .env and restart to chat with the agent."}
            return
        async with self._chat_lock:
            prior = self.history()[-16:]
            db.insert("chat", {"role": "user", "text": message, "ts": now_iso(), "tools": []})
            messages: list[dict[str, Any]] = [{"role": m["role"], "content": m["text"]} for m in prior if m["text"]]
            game = self.engine.by_id.get(game_id) if game_id else None
            parts = [self._snapshot()]
            if game is not None:
                parts.append(f"[game briefing: {game.label}]\n{json.dumps(self.game_briefing(game), default=str)}")
                if game.plays:
                    parts.append(
                        f"[play-by-play: {game.label}, all {len(game.plays)} plays so far, oldest first; "
                        f"score after each play is {game.away.abbr}-{game.home.abbr}]\n{play_lines(game.plays)}"
                    )
            if game is not None and analysis:
                parts.append(ANALYSIS_ASK)
            parts.append(message)
            messages.append({"role": "user", "content": "\n\n".join(parts)})
            text_parts: list[str] = []
            used: list[dict[str, str]] = []
            try:
                for _ in range(MAX_TOOL_ROUNDS):
                    async with self.client.beta.messages.stream(
                        model=self.cfg.claude_model,
                        max_tokens=16000,
                        betas=[FALLBACK_BETA],
                        fallbacks="default",
                        system=[{"type": "text", "text": CHAT_SYSTEM, "cache_control": {"type": "ephemeral"}}],
                        tools=TOOLS,
                        output_config={"effort": "medium"},
                        messages=messages,
                    ) as stream:
                        async for event in stream:
                            if event.type == "content_block_delta" and event.delta.type == "text_delta":
                                text_parts.append(event.delta.text)
                                yield {"type": "text", "delta": event.delta.text}
                        response = await stream.get_final_message()

                    if response.stop_reason == "refusal":
                        note = "\n\nI can't help with that request."
                        text_parts.append(note)
                        yield {"type": "text", "delta": note}
                        break
                    if response.stop_reason == "pause_turn":
                        messages.append({"role": "assistant", "content": response.content})
                        continue
                    calls = [b for b in response.content if b.type == "tool_use"]
                    if not calls:
                        break
                    if response.stop_reason == "max_tokens":
                        # A truncated tool input can parse as a valid partial object. Do not run it.
                        note = "\n\n(That reply was cut off before I could finish; please ask again.)"
                        text_parts.append(note)
                        yield {"type": "text", "delta": note}
                        break
                    results = []
                    for call in calls:
                        summary, content, is_error = await self._run_tool(call.name, call.input)
                        used.append({"name": call.name, "summary": summary})
                        yield {"type": "tool", "name": call.name, "summary": summary}
                        results.append({"type": "tool_result", "tool_use_id": call.id, "content": content, "is_error": is_error})
                    messages.append({"role": "assistant", "content": response.content})
                    messages.append({"role": "user", "content": results})
                    if text_parts and not text_parts[-1].endswith("\n"):
                        text_parts.append("\n\n")
                        yield {"type": "text", "delta": "\n\n"}
            except anthropic.AuthenticationError:
                yield {"type": "error", "message": "Claude rejected the API key. Check ANTHROPIC_API_KEY in .env."}
                return
            except anthropic.RateLimitError:
                yield {"type": "error", "message": "Claude is rate limited right now. Try again in a moment."}
                return
            except anthropic.APIStatusError as exc:
                yield {"type": "error", "message": f"Claude API error {exc.status_code}: {exc.message}"}
                return
            except anthropic.APIConnectionError:
                yield {"type": "error", "message": "Could not reach Claude. Check your connection."}
                return
            except ValueError as exc:  # tool input the SDK could not parse at all
                yield {"type": "error", "message": f"Claude sent a malformed tool call ({exc}). Please try again."}
                return

            text = "".join(text_parts).strip() or "(no reply)"
            row = {"role": "assistant", "text": text, "ts": now_iso(), "tools": used}
            row["id"] = db.insert("chat", row)
            yield {"type": "done", "message": row}

    async def interpret_guidance(self, text: str, memory_id: int) -> None:
        """Let Claude act on guidance typed into the memory box (not the chat)."""
        prompt = (
            f"New standing guidance from me: \"{text}\"\n\nIt is already saved as memory #{memory_id}, so do not save it "
            "again. If it implies playbook changes, make them. Reply in one or two sentences saying what you changed, "
            "or how it will be applied if no parameter fits."
        )
        reply = ""
        async for event in self.chat(prompt):
            if event["type"] == "done":
                reply = event["message"]["text"]
            elif event["type"] == "error":
                reply = ""
                break
        if reply:
            self.engine.decide("note", "Took your guidance on board", reply, source="claude", confidence=0.9, memory_ids=[memory_id])

    # --------------------------------------------------------------------- tools
    async def _run_tool(self, name: str, args: Any) -> tuple[str, str, bool]:
        """Returns (one-line summary for the UI, result content for Claude, is_error)."""
        spec = next((t for t in TOOLS if t["name"] == name), None)
        if spec is None:
            return f"unknown tool {name}", f"Unknown tool '{name}'", True
        err = validate(spec["input_schema"], args)
        if err:
            return f"{name}: invalid input", json.dumps({"INVALID_JSON": json.dumps(args, default=str), "error": err}), True
        try:
            summary, result = await getattr(self, f"_t_{name}")(**args)
            return summary, json.dumps(result, default=str), False
        except Exception as exc:  # report the failure to Claude rather than dropping the result
            return f"{name} failed", f"{type(exc).__name__}: {exc}", True

    async def _t_get_games(self) -> tuple[str, Any]:
        out = []
        for g in self.engine.games:
            ref = g.fanduel.total_line if g.fanduel else None
            near = [r for r in g.ladder if r.no_ask and ref and 4 <= r.strike - ref <= 20][:8]
            out.append({
                "game": g.label, "state": g.state, "period": g.period, "clock": g.clock, "total": g.total,
                "margin": g.margin, "pregame_total": g.pregame_total, "simulated": g.simulated,
                "projection": g.projection.__dict__ if g.projection else None,
                "fanduel": {"total_line": ref, "live": g.fanduel.live, "source": g.fanduel.source} if g.fanduel else None,
                "risk": {"level": g.risk.level, "flags": g.risk.flags},
                "on_the_floor": pattern_texts(g),
                "unders": [{"ticker": r.ticker, "strike": r.strike, "ask": r.no_ask, "bid": r.no_bid,
                            "model_p": round(r.p_under, 3), "edge": r.edge_under} for r in near],
                "quarters": [{k: v[k] for k in ("label", "status", "home_points", "away_points", "seconds_remaining", "projection")}
                             for v in g.quarter_view],
            })
        return f"looked at {len(out)} games", out

    async def _t_get_quarter_markets(self, game: str, quarter: int) -> tuple[str, Any]:
        found = next((g for g in self.engine.games if game.lower() in g.label.lower()), None)
        if found is None:
            raise ValueError(f"No game matching '{game}'")
        markets = found.quarter_markets.get(f"q{quarter}", {})
        view = found.quarter_view[quarter - 1] if len(found.quarter_view) >= quarter else {}

        def rows(kind: str) -> list[dict[str, Any]]:
            return [{"ticker": r.ticker, "yes": r.label("over"), "yes_ask": r.yes_ask, "no": r.label("under"), "no_ask": r.no_ask,
                     "model_p_yes": round(1 - r.p_under, 3)} for r in markets.get(kind, [])]

        return f"looked at Q{quarter} markets for {found.label}", {"game": found.label, "quarter": view, "totals": rows("total"), "spreads": rows("spread")}

    async def _t_get_players(self, game: str) -> tuple[str, Any]:
        found = next((g for g in self.engine.games if game.lower() in g.label.lower()), None)
        if found is None:
            raise ValueError(f"No game matching '{game}'")
        ctx = found.context or {}
        if not ctx:
            return f"no player data yet for {found.label}", {"game": found.label, "players": []}
        keep = ("name", "team", "on_court", "starter", "minutes", "points", "fgm", "fga", "tpm", "tpa", "ftm", "fta", "fouls", "plus_minus")
        players = [{k: p[k] for k in keep} for p in ctx.get("players", [])]
        return f"looked at the players in {found.label}", {
            "game": found.label, "teams": ctx.get("teams"), "notes": [n["text"] for n in ctx.get("notes", [])],
            "out_tonight": ctx.get("out"), "players": players,
        }

    async def _t_get_plays(self, game: str, quarter: Optional[int] = None) -> tuple[str, Any]:
        found = next((g for g in self.engine.games if game.lower() in g.label.lower()), None)
        if found is not None and found.plays:
            label, away, home, plays, source = found.label, found.away.abbr, found.home.abbr, found.plays, "live board"
        else:
            row = self.engine.archived_game(game)
            if row is None:
                if found is not None:
                    return f"no plays yet for {found.label}", {"game": found.label, "plays": ""}
                raise ValueError(f"No game matching '{game}' on the board or in the archive")
            label, away, home, plays, source = row["label"], row["away"], row["home"], row["plays"], f"archive ({row['start_time'][:10]})"
        text = play_lines(plays, quarter)
        n = text.count("\n") + 1 if text else 0
        where = f"Q{quarter}" if quarter and quarter <= 4 else f"OT{quarter - 4}" if quarter else "the game"
        return f"read {n} plays from {where} in {label}", {"game": label, "source": source, "score_order": f"{away}-{home}", "plays": text}

    async def _t_get_positions(self) -> tuple[str, Any]:
        rows = self.engine.positions_api()
        return f"checked {len(rows)} open positions", rows

    async def _t_get_trades(self, limit: int = 20) -> tuple[str, Any]:
        rows = self.engine.trades_api(min(max(limit, 1), 100))
        return f"read {len(rows)} closed trades", rows

    async def _t_get_decisions(self, limit: int = 20, game: str = "") -> tuple[str, Any]:
        rows = self.engine.db.query("SELECT * FROM decisions ORDER BY id DESC LIMIT 300")
        if game:
            rows = [r for r in rows if game.lower() in (r["game_label"] or "").lower()]
        rows = rows[: min(max(limit, 1), 100)]
        return f"read {len(rows)} decisions", rows

    async def _t_search_memory(self, query: str) -> tuple[str, Any]:
        rows = self.engine.memory.list(q=query, limit=400)[:15] or self.engine.memory.recall([], text=query, k=10, touch=False)
        return f"searched memory for \"{query[:40]}\"", rows

    async def _t_save_guidance(self, text: str, tags: Optional[list[str]] = None, pinned: bool = False) -> tuple[str, Any]:
        mem = self.engine.memory.add("guidance", text, tags=[t.lower() for t in (tags or [])], importance=0.85, source="user", pinned=pinned)
        self.engine.hub.emit("memory", mem)
        return "saved guidance to memory", mem

    async def _t_forget_memory(self, memory_id: int) -> tuple[str, Any]:
        self.engine.memory.delete(memory_id)
        return f"deleted memory #{memory_id}", {"ok": True}

    async def _t_get_playbook(self) -> tuple[str, Any]:
        return "read the playbook", self.engine.playbook.to_api()

    async def _t_update_playbook(self, changes: Optional[list[dict[str, Any]]] = None, enabled: Optional[bool] = None) -> tuple[str, Any]:
        changed = self.engine.playbook.update(Q4_UNDER, enabled=enabled, params={c["key"]: c["value"] for c in (changes or [])})
        pretty = ", ".join(f"{k} {old:g} to {new:g}" for k, (old, new) in changed.items())
        if enabled is not None:
            pretty = (pretty + ", " if pretty else "") + ("strategy on" if enabled else "strategy off")
        if pretty:
            self.engine.decide("note", "Playbook updated", pretty, source="claude", confidence=1.0)
        return f"changed playbook: {pretty or 'nothing'}", {"changed": {k: {"old": o, "new": n} for k, (o, n) in changed.items()}, "enabled": self.engine.playbook.enabled(Q4_UNDER)}

    async def _t_get_learning(self) -> tuple[str, Any]:
        state = self.engine.learning_state()
        state["arms"] = [a for a in state["arms"] if a["n"] or a["sim_n"]]
        state["quarters"]["cells"] = [c for c in state["quarters"]["cells"] if c["n"] >= 10]
        state.pop("equity_curve")
        return "read what the learner has concluded", state

    async def _t_set_agent(self, enabled: bool) -> tuple[str, Any]:
        await self.engine.update_settings({"agent_enabled": enabled})
        return "started the agent" if enabled else "paused the agent", {"agent_enabled": enabled}

    async def _t_close_position(self, position_id: int) -> tuple[str, Any]:
        trade = await self.engine.close_position(position_id, reason="manual")
        return f"closed position #{position_id} for {trade['pnl']:+.2f}", trade

    async def _t_place_order(self, ticker: str, side: str, stake: float) -> tuple[str, Any]:
        from .policy import size_order

        game = next((g for g in self.engine.games if g.rung(ticker)), None)
        if game is None:
            raise ValueError(f"No market with ticker {ticker}")
        ask = game.rung(ticker).ask(side)
        if ask is None:
            raise ValueError("No offer on that side right now")
        stake = min(float(stake), float(self.engine.settings["max_stake_per_trade"]))
        contracts, _, _ = size_order(stake, ask)
        pos = await self.engine.manual_order(ticker, side, contracts, ask)
        return f"bought {pos['contracts']} {side} {pos['strike']:g} at {pos['entry_price']}c", pos
