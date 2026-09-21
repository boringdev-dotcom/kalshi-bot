from kalshi_bot.playbook import (
    ENTRY_MAX_REM,
    ENTRY_MIN_MINUTE,
    evaluate_entry,
    evaluate_exit,
    size_for_tier,
)


def test_reject_early_and_high_rem():
    early = evaluate_entry(
        minute=ENTRY_MIN_MINUTE - 1,
        rem=0.5,
        no_ask=85,
        no_bid=83,
        league="premier_league",
        already_stopped=False,
        contracts_this_match=0,
        contracts_today=0,
    )
    assert early.allowed is False
    high_rem = evaluate_entry(
        minute=80,
        rem=ENTRY_MAX_REM + 0.5,
        no_ask=85,
        no_bid=83,
        league="premier_league",
        already_stopped=False,
        contracts_this_match=0,
        contracts_today=0,
    )
    assert high_rem.allowed is False


def test_accept_late_low_rem():
    decision = evaluate_entry(
        minute=78,
        rem=0.5,
        no_ask=86,
        no_bid=84,
        league="premier_league",
        already_stopped=False,
        contracts_this_match=0,
        contracts_today=0,
    )
    assert decision.allowed is True
    assert decision.action == "buy_no"
    assert decision.size == 3


def test_no_reentry_after_stop():
    decision = evaluate_entry(
        minute=80,
        rem=0.5,
        no_ask=86,
        no_bid=84,
        league="mls",
        already_stopped=True,
        contracts_this_match=0,
        contracts_today=0,
    )
    assert decision.allowed is False


def test_caps_and_tier_size():
    assert size_for_tier(1, 10, 10) == 3
    assert size_for_tier(3, 10, 10) == 1
    assert size_for_tier(1, 1, 10) == 1
    capped = evaluate_entry(
        minute=80,
        rem=0.5,
        no_ask=86,
        no_bid=84,
        league="premier_league",
        already_stopped=False,
        contracts_this_match=5,
        contracts_today=0,
    )
    assert capped.allowed is False


def test_flatten_on_goal_and_price_stop():
    goal = evaluate_exit(
        event_type="goal",
        rem=0.5,
        prior_rem=1.5,
        no_mid=80,
        entry_price=86,
        has_position=True,
    )
    assert goal.action == "flatten"
    drop = evaluate_exit(
        event_type="price",
        rem=0.5,
        prior_rem=0.5,
        no_mid=76,
        entry_price=86,
        has_position=True,
    )
    assert drop.action == "flatten"
