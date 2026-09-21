from kalshi_bot.rem import goals_to_bust_under, over_settled, playbook_rem, remaining_goals


def test_remaining_goals_basic():
    assert remaining_goals(2.5, 1) == 1.5
    assert remaining_goals(3.5, 0) == 3.5
    assert remaining_goals(2.5, 3) == -0.5


def test_over_settled():
    assert over_settled(2.5, 3) is True
    assert over_settled(2.5, 2) is False


def test_goals_to_bust():
    assert goals_to_bust_under(2.5, 1) == 2
    assert goals_to_bust_under(2.5, 2) == 1
    assert goals_to_bust_under(2.5, 3) == 0


def test_playbook_integer_rem():
    assert playbook_rem(2.5, 0) == 3
    assert playbook_rem(2.5, 1) == 2
    assert playbook_rem(3.5, 0) == 4
    assert playbook_rem(3.5, 3) == 1
