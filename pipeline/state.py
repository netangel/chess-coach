"""Sync cursors and bookkeeping persisted in data/state.json."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from pathlib import Path

from pydantic import BaseModel, Field

from .config import ROOT

DATA = ROOT / "data"
STATE_PATH = DATA / "state.json"


class GamesState(BaseModel):
    lastCreatedAt: int | None = None  # ms, createdAt of newest stored game
    count: int = 0


class PuzzlesState(BaseModel):
    lastDate: int | None = None  # ms, date of newest stored puzzle attempt
    count: int = 0


class TokenState(BaseModel):
    expiresAt: int | None = None  # ms; filled in M4 via token introspection
    scopes: list[str] = Field(default_factory=list)


class State(BaseModel):
    schemaVersion: int = 1
    games: GamesState = Field(default_factory=GamesState)
    puzzles: PuzzlesState = Field(default_factory=PuzzlesState)
    ratingsFetchedAt: int | None = None
    lastSyncAt: int | None = None
    token: TokenState = Field(default_factory=TokenState)


def load_state(path: Path = STATE_PATH) -> State:
    if path.exists():
        return State.model_validate_json(path.read_text(encoding="utf-8"))
    return State()


def save_state(state: State, path: Path = STATE_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(state.model_dump(), indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def now_ms() -> int:
    return int(datetime.now(UTC).timestamp() * 1000)


def iso_week(d: date | None = None) -> str:
    """ISO week id like 2026-W48."""
    d = d or datetime.now(UTC).date()
    year, week, _ = d.isocalendar()
    return f"{year}-W{week:02d}"
