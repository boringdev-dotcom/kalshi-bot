import pytest

from kalshi_bot.learning.playbook_version import HARD_CAP_KEYS, active_rules, current_version_number, ensure_playbook_v1
from kalshi_bot.learning.proposals import (
    HardCapError,
    approve_proposal,
    assert_no_hard_caps,
    create_proposal,
    reject_proposal,
    shadow_proposal,
)
from kalshi_bot.playbook import ENTRY_MIN_MINUTE
from kalshi_bot.store import Store


def test_hard_caps_never_proposed(tmp_path):
    store = Store(str(tmp_path / "prop.sqlite"))
    ensure_playbook_v1(store)
    with pytest.raises(HardCapError):
        assert_no_hard_caps({"max_daily_loss_cents": 100})
    with pytest.raises(HardCapError):
        create_proposal(
            store,
            title="raise loss cap",
            motivation="no",
            diff={"max_contracts_per_match": 999},
        )
    for key in ("max_contracts_per_match", "max_contracts_per_day", "max_daily_loss_cents"):
        assert key in HARD_CAP_KEYS
    store.close()


def test_approve_rejects_and_versions(tmp_path):
    store = Store(str(tmp_path / "prop2.sqlite"))
    ensure_playbook_v1(store)
    assert current_version_number(store) == 1
    pending = create_proposal(
        store,
        title="Nudge minute to 68",
        motivation="late-game lift",
        diff={"entry_min_minute": 68},
    )
    assert pending["status"] == "pending"
    assert "entry_min_minute" in pending["diff"]
    assert "champion" in pending["backtest"]
    assert ENTRY_MIN_MINUTE == 60
    approved = approve_proposal(store, pending["id"])
    assert approved["proposal"]["status"] == "approved"
    assert approved["version"]["version"] == 2
    assert active_rules(store)["entry_min_minute"] == 68
    assert ENTRY_MIN_MINUTE == 60

    other = create_proposal(
        store,
        title="Widen price band",
        motivation="try shadow",
        diff={"entry_no_price_max": 90},
    )
    shadowed = shadow_proposal(store, other["id"])
    assert shadowed["status"] == "shadow"
    rejected = reject_proposal(store, other["id"])
    # reject after shadow still records a decision
    assert rejected["status"] == "rejected"
    store.close()
