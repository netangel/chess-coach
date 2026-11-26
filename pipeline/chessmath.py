"""Pure evaluation math shared by analysis and metrics (DESIGN.md §7.2)."""

from __future__ import annotations

import math
from typing import Literal

MoveClass = Literal["good", "inaccuracy", "mistake", "blunder"]

CP_CLAMP = 1000
INACCURACY, MISTAKE, BLUNDER = 10.0, 20.0, 30.0


def win_pct(cp: int | None = None, mate: int | None = None) -> float:
    """Winning chances (0–100) for the side the score is relative to (Lichess formula).

    `mate` > 0 means that side mates; < 0 means it gets mated. Mate dominates cp.
    """
    if mate is not None:
        return 100.0 if mate > 0 else 0.0
    if cp is None:
        raise ValueError("need cp or mate")
    cp = max(-CP_CLAMP, min(CP_CLAMP, cp))
    return 50 + 50 * (2 / (1 + math.exp(-0.00368208 * cp)) - 1)


def move_accuracy(win_drop: float) -> float:
    """Per-move accuracy from the mover's win% drop (negative drops count as 0)."""
    drop = max(0.0, win_drop)
    return max(0.0, min(100.0, 103.1668 * math.exp(-0.04354 * drop) - 3.1669))


def classify(win_drop: float) -> MoveClass:
    if win_drop >= BLUNDER:
        return "blunder"
    if win_drop >= MISTAKE:
        return "mistake"
    if win_drop >= INACCURACY:
        return "inaccuracy"
    return "good"


def game_accuracy(win_drops: list[float]) -> float | None:
    if not win_drops:
        return None
    return sum(move_accuracy(d) for d in win_drops) / len(win_drops)


def in_time_pressure(
    clock_left_s: float | None, clock_initial_s: float | None, fraction: float
) -> bool:
    if clock_left_s is None or not clock_initial_s:
        return False
    return clock_left_s < fraction * clock_initial_s
