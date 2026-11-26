"""Leitner spaced-repetition scheduling (DESIGN.md §7.3).

Box index i is due `boxes_days[i]` days after the last review. New positions enter box 0.
Correct → next box (capped at the last); wrong → box 0; not attempted → same box, due again now.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Literal

from pydantic import BaseModel

Result = Literal["correct", "wrong", "skipped"]


class ReviewState(BaseModel):
    box: int = 0
    due: date
    attempts: int = 0
    lastResult: Result | None = None
    chapterId: str | None = None


def new_review(today: date, boxes_days: list[int]) -> ReviewState:
    return ReviewState(box=0, due=today + timedelta(days=boxes_days[0]))


def apply_result(
    rs: ReviewState, result: Result, today: date, boxes_days: list[int]
) -> ReviewState:
    if result == "skipped":
        return rs.model_copy(update={"due": today, "lastResult": "skipped"})
    box = min(rs.box + 1, len(boxes_days) - 1) if result == "correct" else 0
    return rs.model_copy(
        update={
            "box": box,
            "due": today + timedelta(days=boxes_days[box]),
            "attempts": rs.attempts + 1,
            "lastResult": result,
        }
    )


def select_due(
    items: list[tuple[str, ReviewState, float]],
    today: date,
    limit: int,
) -> list[str]:
    """Pick up to `limit` due item ids: most overdue first, then biggest win% drop."""
    due = [(rs.due, -drop, item_id) for item_id, rs, drop in items if rs.due <= today]
    due.sort()
    return [item_id for _, _, item_id in due[:limit]]
