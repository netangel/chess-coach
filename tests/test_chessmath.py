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
    with pytest.raises(ValueError):
        win_pct(mate=0)


def test_move_accuracy():
    assert move_accuracy(0) == 100.0
    assert move_accuracy(-5) == 100.0
    assert move_accuracy(100) == 0.0
    expected = 103.1668100711649 * math.exp(-0.04354415386753951 * 20) - 3.166924740191411 + 1
    assert move_accuracy(20) == pytest.approx(expected)
    assert move_accuracy(10) > move_accuracy(20) > move_accuracy(30)


@pytest.mark.parametrize(
    ("drop", "cls"),
    [
        (0, "good"),
        (4.99, "good"),
        (5, "inaccuracy"),
        (9.9, "inaccuracy"),
        (10, "mistake"),
        (14.9, "mistake"),
        (15, "blunder"),
        (80, "blunder"),
    ],
)
def test_classify(drop, cls):
    assert classify(drop) == cls


def test_classify_custom_thresholds():
    assert classify(12, (10, 20, 30)) == "inaccuracy"


def test_game_accuracy():
    assert game_accuracy([50.0], True) is None
    flat = [50.0] * 21
    assert game_accuracy(flat, True) == pytest.approx(100.0)
    # one White blunder (50 -> 10) drags White down far more than a plain mean would
    one_blunder = [50.0] * 11 + [10.0] * 10  # ply 11 (White) drops 40
    white = game_accuracy(one_blunder, True)
    black = game_accuracy(one_blunder, False)
    assert black == pytest.approx(100.0)
    plain_mean = (9 * 100 + move_accuracy(40)) / 10
    assert white < plain_mean


def test_time_pressure():
    assert in_time_pressure(80, 900, 0.10)
    assert not in_time_pressure(90, 900, 0.10)
    assert not in_time_pressure(None, 900, 0.10)
    assert not in_time_pressure(5, 0, 0.10)
