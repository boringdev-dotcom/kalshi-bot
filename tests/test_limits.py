from kalshi_bot.agents.orchestrator import day_start_ts
from kalshi_bot.execution import flatten_position, submit_buy_no
from kalshi_bot.limits import enforce_loss_cap, get_limits, set_limits
from kalshi_bot.store import Store


def test_loss_cap_pauses_trading(tmp_path):
    store = Store(str(tmp_path / "limits.sqlite"))
    store.set_paper(True)
    set_limits(store, max_daily_loss_cents=200)
    submit_buy_no(
        store,
        None,
        game_id="G1",
        ticker="T-25",
        event_id=1,
        count=10,
        price=90,
        reason="entry",
        paper=True,
    )
    flatten_position(
        store,
        None,
        game_id="G1",
        ticker="T-25",
        event_id=1,
        reason="goal",
        paper=True,
        price=70,
    )
    result = enforce_loss_cap(store, day_start_ts())
    assert result["realized_cents"] == -200
    assert result["breached"] is True
    assert store.is_paused() is True
    assert "loss cap" in (store.pause_reason() or "")
    assert get_limits(store)["max_daily_loss_cents"] == 200
    store.close()
