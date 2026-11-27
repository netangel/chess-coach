"""Validate plan/current.md against the coaching rules in CLAUDE.md (DESIGN.md §8.3)."""

from __future__ import annotations

import re
from pathlib import Path

from pydantic import BaseModel, Field, ValidationError, field_validator

from .config import ROOT, Config
from .site import split_front_matter
from .taxonomy import load_taxonomy

PLAN_PATH = ROOT / "plan" / "current.md"
WEEK = re.compile(r"^\d{4}-W\d{2}$")
MAX_FOCUS = 2


class Item(BaseModel):
    title: str
    minutes: int | None = None
    count: int | None = None
    url: str | None = None
    rule: str | None = None
    instead_of: str | None = None  # replaces that day's daily item with this title

    @field_validator("url")
    @classmethod
    def https(cls, v: str | None) -> str | None:
        if v is not None and not v.startswith("https://"):
            raise ValueError("url must start with https://")
        return v


class Plan(BaseModel):
    week: str
    focus: list[str]
    daily: list[Item]
    weekly: list[Item] = Field(default_factory=list)
    minimum_day: str


def check(text: str, cfg: Config) -> list[str]:
    """Return a list of problems (empty = plan is valid)."""
    fm, body = split_front_matter(text)
    if not fm:
        return ["missing YAML front matter"]
    try:
        plan = Plan.model_validate(fm)
    except ValidationError as e:
        return [f"{'.'.join(map(str, err['loc']))}: {err['msg']}" for err in e.errors()]
    problems = []
    if not WEEK.match(plan.week):
        problems.append(f"week {plan.week!r} is not an ISO week like 2026-W49")
    taxonomy = load_taxonomy()
    if not 1 <= len(plan.focus) <= MAX_FOCUS:
        problems.append(f"focus must have 1–{MAX_FOCUS} skills, has {len(plan.focus)}")
    problems += [f"focus {k!r} is not a taxonomy key" for k in plan.focus if k not in taxonomy]
    for item in plan.daily:
        if item.minutes is None:
            problems.append(f"daily item {item.title!r} has no minutes")
        if item.url is None:
            problems.append(f"daily item {item.title!r} has no url")
    daily_total = sum(i.minutes or 0 for i in plan.daily)
    budget = cfg.training.budget.daily_minutes
    if daily_total > budget:
        problems.append(f"daily items take {daily_total} min, budget is {budget}")
    daily_titles = {i.title for i in plan.daily}
    for item in plan.weekly:
        if item.minutes is None and item.count is None:
            problems.append(f"weekly item {item.title!r} needs minutes or count")
        if item.instead_of is not None and item.instead_of not in daily_titles:
            problems.append(
                f"weekly item {item.title!r}: instead_of {item.instead_of!r} is not a daily item"
            )
    # weekly load (games excluded: they have their own budget, games_per_week)
    extra = sum((i.minutes or 0) * (i.count or 1) for i in plan.weekly if i.instead_of is None)
    week_total = daily_total * 7 + extra
    week_budget = budget * 7 + cfg.training.budget.weekend_block_minutes
    if week_total > week_budget:
        problems.append(f"week takes {week_total} min, budget is {week_budget}")
    if not body.strip():
        problems.append("plan has no explanation below the front matter")
    return problems


def check_file(cfg: Config, path: Path = PLAN_PATH) -> list[str]:
    if not path.exists():
        return [f"{path} does not exist"]
    return check(path.read_text(encoding="utf-8"), cfg)
