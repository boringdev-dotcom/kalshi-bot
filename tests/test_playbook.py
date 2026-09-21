from kalshi_bot.playbook import (
    ENTRY_MAX_MINUTE,
    ENTRY_MAX_REM,
    ENTRY_MIN_MINUTE,
    MAX_CONTRACTS_PER_MATCH,
    STOP_PRICE_DROP_CENTS,
    evaluate_entry,
    evaluate_exit,
    size_for_tier,
)


def _entry(**kwargs):
    base = dict(
        no_ask=86,
        no_bid=84,
        league="premier_league",
        already_stopped=False,
        contracts_this_match=0,
        contracts_today=0,
        minute=78,
        rem=0.5,
    )
    base.update(kwargs)
    return evaluate_entry(**base)


def test_reject_early_late_and_high_rem():
    assert _entry(minute=ENTRY_MIN_MINUTE - 1).allowed is False
    assert _entry(minute=ENTRY_MAX_MINUTE + 1).allowed is False
    assert _entry(rem=ENTRY_MAX_REM + 0.5).allowed is False


def test_accept_late_low_rem():
    decision = _entry()
    assert decision.allowed is True
    assert decision.action == "buy_no"
    assert decision.size == 100


def test_no_reentry_after_stop():
    assert _entry(already_stopped=True, league="mls").allowed is False


def test_tier_3_rejected():
    assert _entry(league="nwsl").allowed is False


def test_caps_and_tier_size():
    assert size_for_tier(1, 10, 10) == 10
    assert size_for_tier(3, 10, 10) == 0
    assert size_for_tier(1, 1, 10) == 1
    assert _entry(contracts_this_match=MAX_CONTRACTS_PER_MATCH).allowed is False


def test_flatten_on_goal_rem_and_price_stop():
    goal = evaluate_exit(
        event_type="goal",
        rem=1.5,
        prior_rem=2.5,
        no_mid=80,
        entry_price=86,
        has_position=True,
    )
    assert goal.action == "flatten"
    rem_stop = evaluate_exit(
        event_type="price",
        rem=0.5,
        prior_rem=1.5,
        no_mid=86,
        entry_price=86,
        has_position=True,
    )
    assert rem_stop.action == "flatten"
    drop = evaluate_exit(
        event_type="price",
        rem=1.5,
        prior_rem=1.5,
        no_mid=86 - STOP_PRICE_DROP_CENTS,
        entry_price=86,
        has_position=True,
    )
    assert drop.action == "flatten"
    hold = evaluate_exit(
        event_type="price",
        rem=1.5,
        prior_rem=1.5,
        no_mid=80,
        entry_price=86,
        has_position=True,
    )
    assert hold.action == "hold"
