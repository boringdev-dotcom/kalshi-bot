from kalshi_bot.execution import flatten_position, submit_buy_no
from kalshi_bot.store import Store


def test_idempotent_paper_orders(tmp_path):
    store = Store(str(tmp_path / "exec.sqlite"))
    first = submit_buy_no(
        store,
        None,
        game_id="G1",
        ticker="T-25",
        event_id=7,
        count=2,
        price=85,
        reason="entry",
        paper=True,
    )
    second = submit_buy_no(
        store,
        None,
        game_id="G1",
        ticker="T-25",
        event_id=7,
        count=9,
        price=10,
        reason="should skip",
        paper=True,
    )
    assert first["idempotency_key"] == second["idempotency_key"]
    assert store.get_position("T-25")["count"] == 2
    flat = flatten_position(
        store,
        None,
        game_id="G1",
        ticker="T-25",
        event_id=7,
        reason="goal",
        paper=True,
    )
    again = flatten_position(
        store,
        None,
        game_id="G1",
        ticker="T-25",
        event_id=7,
        reason="goal again",
        paper=True,
    )
    assert flat["id"] == again["id"]
    assert store.get_position("T-25")["count"] == 0
    assert store.get_position("T-25")["stopped"] == 1
    store.close()
