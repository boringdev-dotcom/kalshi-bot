"""The soccer desk: name matching, Kalshi markets, the goals model, orders and settlement, the agent."""

from __future__ import annotations

import asyncio

from fastapi.testclient import TestClient

from courtside.agent.brain import Brain
from courtside.agent.engine import Engine
from courtside.api.app import create_app
from courtside.config import Config
from courtside.db import DB
from courtside.events import Hub
from courtside.soccer import model
from courtside.soccer.desk import SoccerDesk, SoccerTradeError, implied_line
from courtside.soccer.domain import Match, Side
from courtside.soccer.feed import apply_summary, assign_codes, build_markets, match_event, minute_of, ticker_date
from courtside.soccer.names import pair_score, split_title


def cfg() -> Config:
    return Config(_env_file=None, kalshi_api_key_id="", kalshi_private_key_pem="", anthropic_api_key="", odds_api_key="")


def market(ticker: str, title: str, yes_sub: str = "", strike=None, bid="0.50", ask="0.51") -> dict:
    nb, na = f"{1 - float(ask):.2f}", f"{1 - float(bid):.2f}"
    return {"ticker": ticker, "title": title, "yes_sub_title": yes_sub, "floor_strike": strike,
            "yes_bid_dollars": bid, "yes_ask_dollars": ask, "no_bid_dollars": nb, "no_ask_dollars": na, "volume_fp": "100"}


def a_match(**kw) -> Match:
    m = Match(
        id="soccer-1", league="bundesliga",
        home=Side(id="1", abbr="FCA", name="FC Augsburg", short="Augsburg"),
        away=Side(id="2", abbr="M05", name="Mainz", short="Mainz"),
        start_time="2026-11-22T14:30Z",
    )
    for k, v in kw.items():
        setattr(m, k, v)
    return m


def with_markets(m: Match) -> Match:
    game = {"event_ticker": "KXBUNDESLIGAGAME-26NOV22FCAM05", "title": "Augsburg vs Mainz", "markets": [
        market("KXBUNDESLIGAGAME-26NOV22FCAM05-FCA", "Augsburg wins", "Augsburg", bid="0.44", ask="0.45"),
        market("KXBUNDESLIGAGAME-26NOV22FCAM05-TIE", "Tie", "Tie", bid="0.26", ask="0.27"),
        market("KXBUNDESLIGAGAME-26NOV22FCAM05-M05", "Mainz wins", "Mainz", bid="0.29", ask="0.30"),
    ]}
    assign_codes(m, game)
    m.event_suffix = "26NOV22FCAM05"
    total = {"markets": [market(f"KXBUNDESLIGATOTAL-26NOV22FCAM05-{k}", "", strike=k - 0.5, bid=b, ask=a)
                         for k, b, a in ((1, "0.90", "0.91"), (2, "0.70", "0.71"), (3, "0.45", "0.46"), (4, "0.24", "0.25"))]}
    spread = {"markets": [
        market("KXBUNDESLIGASPREAD-26NOV22FCAM05-FCA2", "", strike=1.5, bid="0.18", ask="0.19"),
        market("KXBUNDESLIGASPREAD-26NOV22FCAM05-M052", "", strike=1.5, bid="0.10", ask="0.11"),
    ]}
    half = {"markets": [market(f"KXBUNDESLIGA1HTOTAL-26NOV22FCAM05-{k}", "", strike=k - 0.5, bid="0.40", ask="0.42") for k in (1, 2)]}
    m.markets = (build_markets(m, game, "match", "winner") + build_markets(m, total, "match", "total")
                 + build_markets(m, spread, "match", "spread") + build_markets(m, half, "1h", "total"))
    return m


# ------------------------------------------------------------------ matching
def test_names_match_across_espn_and_kalshi():
    assert split_title("Manchester City vs Fulham: Total Goals") == ("Manchester City", "Fulham")
    for espn, kalshi in [
        (("Málaga", "Athletic Club"), ("Malaga", "Bilbao")),
        (("FC Cologne", "SV Elversberg"), ("FC Köln", "Elversberg")),
        (("Borussia Mönchengladbach", "Borussia Dortmund"), ("M´gladbach", "Dortmund")),
        (("Atalanta", "Internazionale"), ("Atalanta", "Inter")),
        (("Nice", "Paris Saint-Germain"), ("Nice", "PSG")),
        (("Strasbourg", "Brest"), ("Strasbourg Alsace", "Stade Brest 29")),
        (("Rayo Vallecano", "Valencia"), ("Vallecano", "Valencia")),
    ]:
        assert pair_score(*espn, *kalshi) >= 1.2, (espn, kalshi)
    # The two Manchester clubs are told apart by the other team in the pair.
    liv = a_match(home=Side("1", "LIV", "Liverpool", "Liverpool"), away=Side("2", "MAN", "Manchester United", "Man United"),
                  start_time="2026-11-22T16:30Z")
    events = [{"event_ticker": "KXEPLGAME-26NOV22MCIFUL", "title": "Manchester City vs Fulham"},
              {"event_ticker": "KXEPLGAME-26NOV22LFCMUN", "title": "Liverpool vs Manchester United"}]
    assert match_event(liv, events)["event_ticker"].endswith("LFCMUN")
    assert ticker_date("2026-11-22T16:30Z") == "26NOV22"
    assert minute_of("45'+2'", 1) == 47 and minute_of("67'", 2) == 67


def test_kalshi_markets_map_to_home_away_and_lines():
    m = with_markets(a_match())
    assert m.home.code == "FCA" and m.away.code == "M05"
    spreads = [x for x in m.markets if x.kind == "spread"]
    assert {(x.outcome, x.strike) for x in spreads} == {("home", 1.5), ("away", 1.5)}  # 'M052' is Mainz by 2+, not 'M0'
    winner = {x.outcome: x for x in m.markets if x.kind == "winner"}
    assert set(winner) == {"home", "tie", "away"} and winner["home"].yes_ask == 45
    assert winner["home"].label("yes", m) == "Augsburg to win" and winner["tie"].label("no", m) == "Not a draw"
    assert spreads[0].label("yes", m) == "Augsburg by 2+"
    full = [x for x in m.markets if x.segment == "match"]
    assert implied_line(full) == 2.32  # over 1.5 at 70.5c, over 2.5 at 45.5c: 50/50 sits at 2.32 goals


# --------------------------------------------------------------------- model
def test_goals_model_fits_the_bookmaker_and_moves_with_the_match():
    odds = {"overUnder": 3.5, "moneyline": {"home": {"close": {"odds": "-255"}}, "away": {"close": {"odds": "+600"}}, "draw": {"close": {"odds": "+425"}}},
            "total": {"over": {"close": {"odds": "+100"}}, "under": {"close": {"odds": "-125"}}}}
    lam_h, lam_a = model.prior_from_odds(odds)
    h, d, a = model.results(lam_h, lam_a)
    assert abs(h - 0.69) < 0.02 and abs(a - 0.14) < 0.02 and 3.3 < lam_h + lam_a < 3.7

    m = with_markets(a_match(lam_home=1.6, lam_away=1.1))
    model.price(m)
    pre = m.projection["match"]
    assert abs(m.projection["1h"]["total"] / pre["total"] - model.FIRST_HALF / model.FULL) < 0.01  # first half is ~46% of the goals

    # 2-0 up with ten minutes left: the home side nearly always wins, and few goals are left.
    m.state, m.period, m.minute, m.clock = "live", 2, 80.0, "80'"
    m.home.score, m.home.half_score, m.away.half_score = 2, 1, 0
    model.price(m)
    assert m.projection["match"]["p_home"] > 0.9 and m.projection["match"]["total"] < 2.6
    over_25 = next(x for x in m.markets if x.kind == "total" and x.strike == 2.5)
    over_15 = next(x for x in m.markets if x.kind == "total" and x.strike == 1.5)
    assert over_15.p_yes == 1.0 and 0.1 < over_25.p_yes < 0.4  # already over 1.5; a third goal in ten minutes is possible
    half = next(x for x in m.markets if x.segment == "1h" and x.strike == 0.5)
    assert half.p_yes == 1.0  # one goal in the first half: over 0.5 won at the break

    # A red card for the leaders makes their opponents likelier to score.
    before = m.projection["match"]["away_goals"]
    m.home.red_cards = 1
    model.price(m)
    assert m.projection["match"]["away_goals"] > before


def test_summary_gives_half_time_score_events_and_stats():
    m = a_match(state="live", period=2, minute=60.0)
    data = {
        "header": {"competitions": [{"competitors": [
            {"homeAway": "home", "team": {"id": "1"}, "linescores": [{"displayValue": "2"}, {"displayValue": "0"}]},
            {"homeAway": "away", "team": {"id": "2"}, "linescores": [{"displayValue": "1"}, {"displayValue": "0"}]},
        ]}]},
        "keyEvents": [
            {"type": {"text": "Goal"}, "text": "Goal! Augsburg 1, Mainz 0.", "period": {"number": 1}, "clock": {"displayValue": "12'"}, "team": {"id": "1"}, "scoringPlay": True},
            {"type": {"text": "Red Card"}, "text": "Sent off.", "period": {"number": 2}, "clock": {"displayValue": "55'"}, "team": {"id": "2"}},
            {"type": {"text": "Start Delay"}, "period": {"number": 1}, "clock": {"displayValue": "20'"}},
        ],
        "boxscore": {"teams": [
            {"team": {"id": "1"}, "statistics": [{"name": "totalShots", "displayValue": "11"}, {"name": "redCards", "displayValue": "0"}]},
            {"team": {"id": "2"}, "statistics": [{"name": "totalShots", "displayValue": "4"}, {"name": "redCards", "displayValue": "1"}]},
        ]},
        "commentary": [{"time": {"displayValue": "1'"}, "text": "First Half begins."}],
    }
    apply_summary(m, data)
    assert (m.home.half_score, m.away.half_score) == (2, 1)
    assert [e["type"] for e in m.events] == ["Goal", "Red Card"] and m.events[0]["team"] == "home" and m.events[0]["goal"]
    assert m.stats["Shots"] == {"home": 11, "away": 4} and m.away.red_cards == 1
    assert m.commentary == [{"minute": "1'", "text": "First Half begins."}]


# ---------------------------------------------------------------- the desk
def make_desk() -> tuple[SoccerDesk, Engine]:
    c = cfg()
    engine = Engine(c, DB(":memory:"), Hub())
    desk = SoccerDesk(c, engine.db, engine)
    return desk, engine


def test_paper_orders_settle_by_the_score_and_stay_apart_from_the_nba_book():
    desk, engine = make_desk()
    m = with_markets(a_match(lam_home=1.6, lam_away=1.1))
    model.price(m)
    desk.matches, desk.by_id = [m], {m.id: m}

    home_win = next(x for x in m.markets if x.kind == "winner" and x.outcome == "home")
    under_25 = next(x for x in m.markets if x.kind == "total" and x.strike == 2.5)
    first_half_over = next(x for x in m.markets if x.segment == "1h" and x.strike == 0.5)
    pos = asyncio.run(desk.order(home_win.ticker, "yes", 100, 47))
    assert pos["contracts"] == 100 and pos["entry_price"] == 45 and pos["label"] == "Augsburg to win"
    assert pos["cost"] == round(45 + 1.74, 2) and pos["max_profit"] == round(100 - pos["cost"], 2)  # cost includes Kalshi's fee
    asyncio.run(desk.order(under_25.ticker, "no", 50, 56))
    asyncio.run(desk.order(first_half_over.ticker, "yes", 20, 45))
    try:
        asyncio.run(desk.order(home_win.ticker, "yes", 100, 40))
        raise AssertionError("an order below the ask should not fill")
    except SoccerTradeError as exc:
        assert "45c" in str(exc)
    try:
        asyncio.run(desk.order(home_win.ticker, "yes", 1000, 47))  # $470 is over the $300 cap
        raise AssertionError("an order over the per-trade cap should be refused")
    except SoccerTradeError as exc:
        assert "limit per trade" in str(exc)

    assert len(desk.positions_api()) == 3
    assert engine.positions_api() == [] and engine.account()["open_positions"] == 0  # the NBA book never sees soccer

    # Half time at 0-0: the first-half over 0.5 loses; the full-match markets stay open.
    m.state, m.period, m.halftime = "live", 1, True
    m.home.half_score, m.away.half_score = 0, 0
    desk._settle()
    open_now = desk.positions_api()
    assert len(open_now) == 2 and desk.trades_api()[0]["exit_reason"] == "settled_loss"

    # Full time 2-1: Augsburg win (yes wins), 3 goals (the under 2.5 loses).
    m.state, m.halftime, m.period = "final", False, 2
    m.home.score, m.away.score = 2, 1
    desk._settle()
    trades = {t["label"]: t for t in desk.trades_api()}
    assert desk.positions_api() == []
    assert trades["Augsburg to win"]["exit_reason"] == "settled_win" and trades["Augsburg to win"]["exit_price"] == 100
    assert trades["Under 2.5 goals"]["exit_reason"] == "settled_loss"
    acct = desk.account()
    assert acct["wins"] == 1 and acct["losses"] == 2
    assert abs(acct["cash"] - (5000 + acct["pnl_total"])) < 0.01


def test_selling_a_soccer_position_at_the_bid():
    desk, _ = make_desk()
    m = with_markets(a_match(lam_home=1.6, lam_away=1.1))
    model.price(m)
    desk.matches, desk.by_id = [m], {m.id: m}
    mainz = next(x for x in m.markets if x.kind == "winner" and x.outcome == "away")
    pos = asyncio.run(desk.order(mainz.ticker, "yes", 10, 30))
    trade = asyncio.run(desk.close(pos["id"]))
    assert trade["exit_price"] == 29 and trade["exit_reason"] == "sold" and trade["pnl"] < 0


def test_soccer_analysis_sends_the_briefing_and_commentary():
    desk, engine = make_desk()
    brain = Brain(engine.cfg, engine)
    brain.soccer = desk
    m = with_markets(a_match(lam_home=1.6, lam_away=1.1, state="live", period=1, minute=30.0, clock="30'"))
    m.commentary = [{"minute": "28'", "text": "Attempt saved. Augsburg header from the six yard box."}]
    model.price(m)
    desk.matches, desk.by_id = [m], {m.id: m}
    brief = desk.briefing(m)
    assert brief["markets"] and brief["model_projection"]["match"] and brief["score"] == {"Augsburg": 0, "Mainz": 0}

    sent: list = []

    class Final:
        stop_reason, content = "end_turn", []

    class Stream:
        def __init__(self, **kw):
            sent.append(kw["messages"][-1]["content"])

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        def __aiter__(self):
            async def gen():
                delta = type("D", (), {"type": "text_delta", "text": "Augsburg on top."})()
                yield type("E", (), {"type": "content_block_delta", "delta": delta})()
            return gen()

        async def get_final_message(self):
            return Final()

    brain.client = type("C", (), {"beta": type("B", (), {"messages": type("M", (), {"stream": lambda self, **kw: Stream(**kw)})()})()})()
    brain.cfg.anthropic_api_key = "test"

    async def ask() -> list[dict]:
        return [ev async for ev in brain.chat("Agent analysis: Augsburg vs Mainz", game_id=m.id, analysis=True)]

    events = asyncio.run(ask())
    assert events[-1]["type"] == "done"
    text = sent[0]
    assert "[soccer match briefing: Augsburg vs Mainz]" in text and "[commentary: Augsburg vs Mainz, all 1 lines" in text
    assert "Attempt saved" in text and "soccer match" in text and "[game briefing" not in text

    summary, out = asyncio.run(brain._t_get_soccer())
    assert out[0]["match"] == "Augsburg vs Mainz" and "winner_yes_asks" in out[0]
    summary, out = asyncio.run(brain._t_get_soccer("Mainz"))
    assert out["match"].startswith("FC Augsburg")


def test_soccer_api_routes(tmp_path, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "")
    app = create_app(db_path=str(tmp_path / "s.db"), start_engine=False)
    desk: SoccerDesk = app.state.soccer
    m = with_markets(a_match(lam_home=1.6, lam_away=1.1))
    model.price(m)
    desk.matches, desk.by_id = [m], {m.id: m}
    with TestClient(app) as client:
        board = client.get("/api/soccer").json()
        assert [lg["key"] for lg in board["leagues"]] == ["epl", "laliga", "seriea", "bundesliga", "ligue1", "ucl", "uel"]
        assert board["matches"][0]["winner"]["home"]["yes_ask"] == 45 and board["account"]["mode"] == "paper"
        detail = client.get(f"/api/soccer/matches/{m.id}").json()
        assert {"markets", "events", "stats", "commentary", "prior", "positions", "account"} <= set(detail)
        assert client.get("/api/soccer/matches/nope").status_code == 404
        ticker = detail["markets"][0]["ticker"]
        assert client.post("/api/soccer/orders", json={"ticker": ticker, "side": "over", "contracts": 1, "price": 50}).status_code == 422
        pos = client.post("/api/soccer/orders", json={"ticker": ticker, "side": "yes", "contracts": 5, "price": 50}).json()
        assert pos["contracts"] == 5
        assert client.post(f"/api/soccer/positions/{pos['id']}/close").status_code == 200
        assert client.get("/api/soccer/trades").json()[0]["exit_reason"] == "sold"


def test_favs_keep_only_85_to_90_confidence_priced_below_it():
    import json

    desk, engine = make_desk()
    brain = Brain(engine.cfg, engine)
    brain.soccer = desk
    m = with_markets(a_match(lam_home=1.6, lam_away=1.1, state="live", period=1, minute=20.0, clock="20'"))
    m.commentary = [{"minute": "18'", "text": "Corner, Augsburg."}]
    model.price(m)
    desk.matches, desk.by_id = [m], {m.id: m}

    _, context, candidates = brain._fav_candidates(m.id)
    assert candidates and all(55 <= c["ask"] <= 93 and 0.72 <= c["model_p"] <= 0.97 for c in candidates)
    assert "[commentary:" in context and "Corner, Augsburg." in context
    cheap = next(c for c in candidates if c["ask"] <= 86)
    dear = next(c for c in candidates if c["ask"] >= 89)

    reply = {"summary": "Augsburg pressing.", "picks": [
        {"candidate_id": cheap["id"], "confidence": 0.88, "reason": "Fits."},
        {"candidate_id": cheap["id"], "confidence": 0.87, "reason": "Duplicate."},
        {"candidate_id": dear["id"], "confidence": 0.88, "reason": "Priced above the confidence: no profit."},
        {"candidate_id": candidates[-1]["id"], "confidence": 0.95, "reason": "Too sure: outside the band."},
        {"candidate_id": candidates[0]["id"], "confidence": 0.80, "reason": "Not sure enough."},
    ]}
    sent: dict = {}

    class Final:
        stop_reason = "end_turn"
        content = [type("T", (), {"type": "text", "text": json.dumps(reply)})()]

    class Stream:
        def __init__(self, **kw):
            sent.update(kw)

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get_final_message(self):
            return Final()

    brain.client = type("C", (), {"beta": type("B", (), {"messages": type("M", (), {"stream": lambda self, **kw: Stream(**kw)})()})()})()
    brain.cfg.anthropic_api_key = "test"
    out = asyncio.run(brain.favs(m.id))

    fmt = sent["output_config"]["format"]
    assert fmt["type"] == "json_schema"
    assert fmt["schema"]["properties"]["picks"]["items"]["properties"]["candidate_id"]["enum"] == [c["id"] for c in candidates]
    assert "85% and 90%" in sent["messages"][0]["content"]
    assert [p["ticker"] for p in out["picks"]] == [cheap["ticker"]] and out["dropped"] == 4
    pick = out["picks"][0]
    assert pick["confidence"] == 0.88 and pick["side"] == cheap["side"] and pick["edge"] == round(0.88 - cheap["ask"] / 100, 3)
    assert out["summary"] == "Augsburg pressing."
    # Kept for the page to show again after the phone leaves and comes back.
    assert brain.favs_state(m.id) == {"result": out, "picking": False}
    assert brain.favs_state("other") == {"result": None, "picking": False}

    # Two asks at once share one pick, and it is shown as running meanwhile.
    calls = []
    gate = asyncio.Event()

    async def slow(game_id):
        calls.append(game_id)
        await gate.wait()
        return {"picks": [], "summary": "later"}

    async def both():
        brain._pick_favs = slow
        a = asyncio.create_task(brain.favs(m.id))
        b = asyncio.create_task(brain.favs(m.id))
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        assert brain.favs_state(m.id)["picking"] is True
        gate.set()
        return await a, await b

    ra, rb = asyncio.run(both())
    assert calls == [m.id] and ra == rb and brain.favs_state(m.id) == {"result": ra, "picking": False}
    del brain._pick_favs

    brain.cfg.anthropic_api_key = ""
    brain.client = None
    try:
        asyncio.run(brain.favs(m.id))
        raise AssertionError("favs without Claude should say so")
    except ValueError as exc:
        assert "Claude" in str(exc)


class FakeKalshi:
    """What Kalshi reports holding and filling, for the live position sync."""

    def __init__(self, held: dict, fills: list):
        self.held, self._fills = held, fills

    async def positions(self):
        return self.held

    async def fills(self, ticker, limit=100):
        return [f for f in self._fills if f.get("ticker", ticker) == ticker]


def live_row(desk: SoccerDesk, ticker: str, side: str, contracts: int, price: int, opened_at: str) -> int:
    cost = round(contracts * price / 100 + 1.0, 2)
    return desk.db.insert("soccer_positions", {
        "match_id": "soccer-1", "match_label": "Nice vs PSG", "league": "ligue1", "ticker": ticker, "segment": "match",
        "kind": "spread", "outcome": "away", "strike": 2.5, "side": side, "label": "PSG not by 3+", "contracts": contracts,
        "entry_price": price, "cost": cost, "fees": 1.0, "mode": "live", "status": "open", "opened_at": opened_at,
    })


def test_live_positions_sold_on_kalshi_close_at_the_kalshi_fill_price():
    desk, engine = make_desk()
    t = "KXLIGUE1SPREAD-26NOV21NICPSG-PSG3"
    pid = live_row(desk, t, "no", 120, 82, "2026-11-21T17:41:13+00:00")
    engine.kalshi = FakeKalshi({}, [
        # The user's sell on Kalshi (two fills of one order), then the desk's own entry just before opened_at.
        {"count": 119, "yes_price": 16, "no_price": 84, "fee": 1.1195, "created_time": "2026-11-21T17:47:26.126778Z"},
        {"count": 1, "yes_price": 16, "no_price": 84, "fee": 0.0095, "created_time": "2026-11-21T17:47:26.126778Z"},
        {"count": 120, "yes_price": 18, "no_price": 82, "fee": 1.24, "created_time": "2026-11-21T17:41:12.840844Z"},
    ])
    engine.settings["trading_mode"] = "live"
    closed = asyncio.run(desk.sync_with_kalshi())
    assert [c["id"] for c in closed] == [pid]
    trade = closed[0]
    assert trade["exit_price"] == 84 and trade["exit_reason"] == "sold_on_kalshi"
    assert trade["pnl"] == round(120 * 0.84 - (120 * 0.82 + 1.0) - 1.13, 2)
    assert desk.positions_api() == []


def test_partial_sale_on_kalshi_splits_the_position():
    desk, engine = make_desk()
    t = "KXEPLTOTAL-26NOV22ABCDEF-3"
    pid = live_row(desk, t, "yes", 100, 40, "2026-11-21T10:00:00+00:00")
    engine.kalshi = FakeKalshi({t: 60.0}, [{"count": 40, "yes_price": 55, "no_price": 45, "fee": 0.4, "created_time": "2026-11-21T10:05:00Z"}])
    engine.settings["trading_mode"] = "live"
    closed = asyncio.run(desk.sync_with_kalshi())
    assert len(closed) == 1 and closed[0]["contracts"] == 40 and closed[0]["exit_price"] == 55
    left = desk.db.one("SELECT * FROM soccer_positions WHERE id=?", [pid])
    assert left["status"] == "open" and left["contracts"] == 60 and abs(left["cost"] + closed[0]["cost"] - 41.0) < 0.011


def test_sync_leaves_settled_held_and_fresh_positions_alone():
    desk, engine = make_desk()
    engine.settings["trading_mode"] = "live"
    # Gone from Kalshi with no sale on record: settled, so settlement handles it.
    live_row(desk, "KXA-1", "no", 10, 80, "2026-11-21T10:00:00+00:00")
    # Still held on Kalshi (as NO, i.e. a negative count).
    live_row(desk, "KXB-1", "no", 10, 80, "2026-11-21T10:00:00+00:00")
    # Bought seconds ago: Kalshi may not list it yet.
    from courtside.domain import now_iso
    live_row(desk, "KXC-1", "yes", 10, 50, now_iso())
    engine.kalshi = FakeKalshi({"KXB-1": -10.0}, [{"ticker": "KXA-1", "count": 10, "yes_price": 20, "no_price": 80, "fee": 0.1,
                                                   "created_time": "2026-11-21T09:59:59Z"}])
    assert asyncio.run(desk.sync_with_kalshi()) == []
    assert len(desk.positions_api()) == 3


def test_summary_gives_the_agent_lineups_players_form_table_and_run_of_play():
    from courtside.soccer.context import run_of_play

    aug, mai = {"id": "1", "displayName": "FC Augsburg"}, {"id": "2", "displayName": "Mainz"}
    stat = lambda **kw: [{"name": k, "displayValue": str(v)} for k, v in kw.items()]  # noqa: E731
    player = lambda name, pos, starter=True, sub_in=False, sub_out=False, **kw: {  # noqa: E731
        "athlete": {"displayName": name}, "position": {"abbreviation": pos}, "starter": starter,
        "subbedIn": sub_in, "subbedOut": sub_out, "stats": stat(**kw)}
    data = {
        "header": {"competitions": [{"competitors": [{"homeAway": "home", "team": aug}, {"homeAway": "away", "team": mai}]}]},
        "rosters": [
            {"homeAway": "home", "team": aug, "formation": "4-3-3", "roster": [
                player("Keeper A", "G", saves=3, totalGoals=0), player("Striker A", "F", sub_out=True, totalShots=4, shotsOnTarget=2, totalGoals=1),
                player("Quiet A", "CD"), player("Sub A", "F", starter=False, sub_in=True), player("Bench A", "D", starter=False)]},
            {"homeAway": "away", "team": mai, "formation": "3-5-2", "roster": [player("Defender M", "CD", foulsCommitted=3, yellowCards=1)]},
        ],
        "lastFiveGames": [{"team": aug, "events": [
            {"gameDate": "2026-11-01T14:30Z", "homeTeamId": "1", "homeTeamScore": "2", "awayTeamScore": "0", "gameResult": "W", "opponent": {"displayName": "Bochum"}, "leagueName": "Bundesliga"},
            {"gameDate": "2026-11-08T14:30Z", "homeTeamId": "9", "homeTeamScore": "3", "awayTeamScore": "1", "gameResult": "L", "opponent": {"displayName": "Leipzig"}, "leagueName": "Bundesliga"},
        ]}],
        "standings": {"groups": [{"standings": {"entries": [
            {"id": "2", "team": "Mainz", "stats": stat(rank=4, gamesPlayed=11, wins=6, ties=3, losses=2, pointDifferential="+8", points=21)},
            {"id": "1", "team": "FC Augsburg", "stats": stat(rank=12, gamesPlayed=11, wins=3, ties=3, losses=5, pointDifferential="-4", points=12)},
            {"id": "7", "team": "Someone Else", "stats": stat(rank=1)},
        ]}}]},
        "seasonseries": [{"type": "head-to-head", "summary": "Mainz lead 2-1", "events": [{"date": "2026-03-01T14:30Z", "competitors": [
            {"homeAway": "home", "score": "1", "team": {"abbreviation": "M05"}}, {"homeAway": "away", "score": "1", "team": {"abbreviation": "FCA"}}]}]}],
        "boxscore": {"teams": [{"team": aug, "statistics": stat(totalShots=9, passPct=0.8)}]},
        "commentary": [
            {"time": {"displayValue": "20'"}, "text": "Attempt saved. Striker A (FC Augsburg) right footed shot is saved."},
            {"time": {"displayValue": "45'+2'"}, "text": "Corner, FC Augsburg. Conceded by Defender M."},
            {"time": {"displayValue": "50'"}, "text": "Attempt missed. Mid M (Mainz) header misses to the left."},
            {"time": {"displayValue": "55'"}, "text": "Attempt saved. Mid M (Mainz) left footed shot is saved."},
            {"time": {"displayValue": "56'"}, "text": "Corner, Mainz. Conceded by Keeper A."},
            {"time": {"displayValue": "57'"}, "text": "Foul by Quiet A (FC Augsburg)."},
            {"time": {"displayValue": "58'"}, "text": "Defender M (Mainz) is shown the yellow card for a bad foul."},
            {"time": {"displayValue": "59'"}, "text": "Delay in match because of an injury."},
        ],
    }

    pre = a_match(state="pre")
    apply_summary(pre, data)
    assert pre.stats == {}  # no all-zero stat bars before kickoff
    assert pre.lineups["home"]["formation"] == "4-3-3" and run_of_play(pre) is None

    m = a_match(state="live", period=2, minute=60.0, clock="60'")
    apply_summary(m, data)
    home = m.lineups["home"]
    assert home["starting_xi"] == ["Keeper A (G)", "Striker A (F)", "Quiet A (CD)"]
    assert home["came_on"] == ["Sub A"] and home["went_off"] == ["Striker A"]
    # Only players who did something, zeros left out; the unused sub is not there.
    assert m.players["home"] == [
        {"name": "Keeper A", "pos": "G", "saves": 3},
        {"name": "Striker A", "pos": "F", "went_off": True, "shots": 4, "on_target": 2, "goals": 1},
        {"name": "Sub A", "pos": "F", "came_on": True},
    ]
    assert m.players["away"] == [{"name": "Defender M", "pos": "CD", "fouls": 3, "yellow": 1}]
    assert m.form["home"] == ["L 1-3 at Leipzig (Bundesliga, 2026-11-08)", "W 2-0 vs Bochum (Bundesliga, 2026-11-01)"]
    assert m.table["home"]["position"] == "12" and m.table["away"]["points"] == "21" and m.table["home"]["of"] == 3
    assert m.head_to_head == {"summary": "Mainz lead 2-1", "games": ["2026-03-01 M05 1-1 FCA"]}
    assert m.stats["Pass accuracy"]["home"] == 0.8

    trend = run_of_play(m)
    assert trend["window"] == "45'-60'"
    assert trend["last_window"]["Mainz"] == {"shots": 2, "on_target": 1, "corners": 1, "fouls": 0, "cards": 1, "offsides": 0, "goals": 0}
    assert trend["last_window"]["Augsburg"]["fouls"] == 1
    # The window before is 30'-45': first-half stoppage (45'+2', counted as 45') is in it, 20' is too early.
    assert trend["window_before"]["Augsburg"] == {"shots": 0, "on_target": 0, "corners": 1, "fouls": 0, "cards": 0, "offsides": 0, "goals": 0}

    desk, _ = make_desk()
    b = desk.briefing(m)
    assert b["lineups"]["Augsburg"]["formation"] == "4-3-3" and b["league_table"]["Mainz"]["position"] == "4"
    assert b["run_of_play"]["last_window"]["Mainz"]["shots"] == 2
    assert list(b["form_last_5"]) == ["Augsburg"] and b["players_who_did_something"]["Mainz"][0]["yellow"] == 1


def test_cups_are_on_the_board_and_knockouts_settle_on_90_minutes():
    from courtside.soccer.domain import LEAGUE_BY_KEY
    from courtside.soccer.feed import regulation_goals

    assert (LEAGUE_BY_KEY["ucl"].espn, LEAGUE_BY_KEY["ucl"].kalshi) == ("uefa.champions", "KXUCL")
    assert (LEAGUE_BY_KEY["uel"].espn, LEAGUE_BY_KEY["uel"].kalshi) == ("uefa.europa", "KXUEL")

    desk, _ = make_desk()
    m = with_markets(a_match(league="ucl", lam_home=1.6, lam_away=1.1))
    model.price(m)
    desk.matches, desk.by_id = [m], {m.id: m}
    home = next(x for x in m.markets if x.kind == "winner" and x.outcome == "home")
    draw = next(x for x in m.markets if x.kind == "winner" and x.outcome == "tie")
    over = next(x for x in m.markets if x.kind == "total" and x.strike == 2.5)
    for mk in (home, draw, over):
        asyncio.run(desk.order(mk.ticker, "yes", 10, 60))

    # 1-1 after 90 minutes, then Augsburg score twice in extra time.
    m.state, m.period, m.halftime = "live", 3, False
    m.home.half_score, m.away.half_score = 0, 1
    assert not m.segment_done("match")  # extra time, but the score at 90 is not known yet
    m.home.reg_score, m.away.reg_score = regulation_goals([{"value": 0}, {"value": 1}]), regulation_goals([{"value": 1}, {"value": 0}])
    m.home.score, m.away.score = 3, 1
    desk._settle()
    trades = {t["label"]: t for t in desk.trades_api()}
    assert trades["Draw"]["exit_reason"] == "settled_win"  # 1-1 at 90 is what Kalshi pays on
    assert trades["Augsburg to win"]["exit_reason"] == "settled_loss"
    assert trades["Over 2.5 goals"]["exit_reason"] == "settled_loss"
    assert regulation_goals([{"value": 2}]) is None and regulation_goals(None) is None


def test_kalshi_prices_are_fetched_a_couple_of_leagues_at_a_time_and_refusals_retry_soon():
    from courtside.soccer.domain import LEAGUES
    from courtside.soccer.feed import LEAGUES_PER_ROUND, RETRY_S, SoccerFeed

    class Kalshi:
        calls: list[str] = []

        async def events(self, ticker):
            self.calls.append(ticker)
            if ticker.startswith("KXEPL"):
                raise RuntimeError("429 too many requests")
            return []

    k = Kalshi()
    feed = SoccerFeed(k)
    for i, lg in enumerate(LEAGUES):
        m = a_match(league=lg.key)
        m.id = f"soccer-{i}"
        feed.matches[m.id] = m

    asyncio.run(feed._refresh_kalshi(1000.0))
    leagues = {next(lg.key for lg in LEAGUES if t.startswith(lg.kalshi) and t[len(lg.kalshi):] in {"GAME", "TOTAL", "SPREAD", "1H", "1HTOTAL", "1HSPREAD"}) for t in k.calls}
    assert len(leagues) == LEAGUES_PER_ROUND and "epl" in leagues
    assert feed._next_kalshi["epl"] == 1000.0 + RETRY_S  # turned away: back soon
    assert all(v == 1060.0 for key, v in feed._next_kalshi.items() if key != "epl")

    k.calls.clear()
    asyncio.run(feed._refresh_kalshi(1002.0))  # the next round takes the next leagues
    assert k.calls and not any(t.startswith("KXEPL") for t in k.calls)
    asyncio.run(feed.aclose())
