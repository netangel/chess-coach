"""Pure evaluation math shared by analysis and metrics (DESIGN.md §7.2)."""

from __future__ import annotations

import math
from typing import Literal

MoveClass = Literal["good", "inaccuracy", "mistake", "blunder"]

CP_CLAMP = 1000
# Win% drop thresholds for (inaccuracy, mistake, blunder). 5/10/15 reproduces Lichess's own
# judgments (it uses 0.1/0.2/0.3 on the [-1, 1] winning-chances scale): 97% agreement on 953
# moves of our games, vs 81% for 10/20/30 (decision 2026-11-26).
DEFAULT_THRESHOLDS: tuple[float, float, float] = (5.0, 10.0, 15.0)


def win_pct(cp: int | None = None, mate: int | None = None) -> float:
    """Winning chances (0–100) for the side the score is relative to (Lichess formula).

    `mate` > 0 means that side mates; < 0 means it gets mated. Mate dominates cp.
    """
    if mate is not None:
        if mate == 0:
            raise ValueError("mate=0 is ambiguous; score terminal positions explicitly")
        return 100.0 if mate > 0 else 0.0
    if cp is None:
        raise ValueError("need cp or mate")
    cp = max(-CP_CLAMP, min(CP_CLAMP, cp))
    return 50 + 50 * (2 / (1 + math.exp(-0.00368208 * cp)) - 1)


def move_accuracy(win_drop: float) -> float:
    """Per-move accuracy from the mover's win% drop (Lichess formula incl. its +1 bonus)."""
    if win_drop <= 0:
        return 100.0
    raw = 103.1668100711649 * math.exp(-0.04354415386753951 * win_drop) - 3.166924740191411
    return max(0.0, min(100.0, raw + 1))


def classify(
    win_drop: float, thresholds: tuple[float, float, float] = DEFAULT_THRESHOLDS
) -> MoveClass:
    inaccuracy, mistake, blunder = thresholds
    if win_drop >= blunder:
        return "blunder"
    if win_drop >= mistake:
        return "mistake"
    if win_drop >= inaccuracy:
        return "inaccuracy"
    return "good"


def game_accuracy(win_white: list[float], color_is_white: bool, white_moves_first: bool = True):
    """Lichess game accuracy for one side.

    `win_white` is White's win% for every position, starting position included. Lichess averages
    a volatility-weighted mean (weights = std-dev of win% in a sliding window) with the harmonic
    mean of the per-move accuracies, which punishes single big errors far more than a plain mean.
    """
    n_moves = len(win_white) - 1
    if n_moves < 1:
        return None
    size = max(2, min(8, n_moves // 10))
    size = min(size, len(win_white))
    windows = [win_white[:size]] * max(0, size - 2) + [
        win_white[i : i + size] for i in range(len(win_white) - size + 1)
    ]
    accs: list[tuple[float, float]] = []
    for i in range(n_moves):
        mover_white = (i % 2 == 0) == white_moves_first
        if mover_white != color_is_white:
            continue
        before, after = win_white[i], win_white[i + 1]
        drop = before - after if mover_white else after - before
        weight = max(0.5, min(12.0, _pstdev(windows[i]))) if i < len(windows) else 0.5
        accs.append((move_accuracy(drop), weight))
    if not accs:
        return None
    weighted = sum(a * w for a, w in accs) / sum(w for _, w in accs)
    harmonic = len(accs) / sum(1 / max(a, 1.0) for a, _ in accs)
    return (weighted + harmonic) / 2


def _pstdev(xs: list[float]) -> float:
    mean = sum(xs) / len(xs)
    return math.sqrt(sum((x - mean) ** 2 for x in xs) / len(xs))


def in_time_pressure(
    clock_left_s: float | None, clock_initial_s: float | None, fraction: float
) -> bool:
    if clock_left_s is None or not clock_initial_s:
        return False
    return clock_left_s < fraction * clock_initial_s
