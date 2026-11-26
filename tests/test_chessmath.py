import math

import pytest

from pipeline.chessmath import classify, game_accuracy, in_time_pressure, move_accuracy, win_pct


def test_win_pct_symmetry_and_anchors():
    assert win_pct(0) == pytest.approx(50.0)
    for cp in (35, 100, 300, 900):
        assert win_pct(cp) + win_pct(-cp) == pytest.approx(100.0)
    # Lichess: +100cp ≈ 59.1%
    assert win_pct(100) == pytest.approx(59.1, abs=0.1)


def test_win_pct_clamp_and_mate():
    assert win_pct(5000) == win_pct(1000)
    assert win_pct(mate=3) == 100.0
    assert win_pct(mate=-1) == 0.0
    assert win_pct(cp=-200, mate=2) == 100.0
    with pytest.raises(ValueError):
        win_pct()


def test_move_accuracy():
    assert move_accuracy(0) == pytest.approx(100.0, abs=0.01)
    assert move_accuracy(-5) == move_accuracy(0)
    assert move_accuracy(100) == 0.0
    assert move_accuracy(20) == pytest.approx(103.1668 * math.exp(-0.04354 * 20) - 3.1669)
    assert move_accuracy(10) > move_accuracy(20) > move_accuracy(30)


@pytest.mark.parametrize(
    ("drop", "cls"),
    [
        (0, "good"),
        (9.99, "good"),
        (10, "inaccuracy"),
        (19.9, "inaccuracy"),
        (20, "mistake"),
        (29.9, "mistake"),
        (30, "blunder"),
        (80, "blunder"),
    ],
)
def test_classify(drop, cls):
    assert classify(drop) == cls


def test_game_accuracy():
    assert game_accuracy([]) is None
    assert game_accuracy([0, 0]) == pytest.approx(100.0, abs=0.01)


def test_time_pressure():
    assert in_time_pressure(80, 900, 0.10)
    assert not in_time_pressure(90, 900, 0.10)
    assert not in_time_pressure(None, 900, 0.10)
    assert not in_time_pressure(5, 0, 0.10)
