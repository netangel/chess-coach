"""Incremental sync of games, puzzles, ratings and weekly snapshots (DESIGN.md §7.1).

Raw files are append-only and hold lines exactly as Lichess returned them.
Every append is de-duplicated, so an interrupted run can simply be re-run.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

from .config import Config
from .lichess_client import LichessClient
from .state import DATA, State, iso_week, now_ms

log = logging.getLogger(__name__)

RAW = DATA / "raw"
GAMES_PATH = RAW / "games.ndjson"
PUZZLES_PATH = RAW / "puzzles.ndjson"
RATINGS_PATH = RAW / "ratings.json"
SNAPSHOTS = RAW / "snapshots"

GAME_EXPORT_FLAGS = {
    "sort": "dateAsc",  # oldest first => appending keeps the file chronological
    "moves": True,
    "clocks": True,
    "evals": True,  # only present if Lichess analysis already exists; kept as cross-check
    "opening": True,
    "accuracy": True,
    "division": True,
    "finished": True,
}
PUZZLE_PAGE = 500


@dataclass
class SyncResult:
    source: str
    added: int
    skipped: str | None = None

    def __str__(self) -> str:
        if self.skipped:
            return f"{self.source}: skipped ({self.skipped})"
        return f"{self.source}: +{self.added}"


def iter_ndjson(path: Path) -> Iterator[dict]:
    if not path.exists():
        return
    with path.open(encoding="utf-8") as f:
        for line in f:
            if line.strip():
                yield json.loads(line)


# -- games -------------------------------------------------------------------


def sync_games(
    client: LichessClient, cfg: Config, state: State, path: Path = GAMES_PATH
) -> SyncResult:
    known = {g["id"] for g in iter_ndjson(path)}
    since = state.games.lastCreatedAt + 1 if state.games.lastCreatedAt else None
    params = {**GAME_EXPORT_FLAGS, "since": since}
    added = 0
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as out:
        for line in client.stream_ndjson_lines(f"/api/games/user/{cfg.lichess.username}", params):
            game = json.loads(line)
            if game["id"] not in known:
                out.write(line + "\n")
                out.flush()
                known.add(game["id"])
                added += 1
                if added % 200 == 0:
                    log.info("games: %d downloaded…", added)
            # advance the cursor only once the game is safely on disk
            created = game["createdAt"]
            if state.games.lastCreatedAt is None or created > state.games.lastCreatedAt:
                state.games.lastCreatedAt = created
    state.games.count = len(known)
    return SyncResult("games", added)


# -- puzzles -----------------------------------------------------------------


def _puzzle_key(p: dict) -> tuple[str, int]:
    return (p["puzzle"]["id"], p["date"])


def sync_puzzles(
    client: LichessClient, state: State, path: Path = PUZZLES_PATH, page: int = PUZZLE_PAGE
) -> SyncResult:
    """Page backwards with `before` until we reach what we already have."""
    if not client.has_token:
        return SyncResult("puzzles", 0, skipped="no LICHESS_TOKEN with puzzle:read")
    known = {_puzzle_key(p) for p in iter_ndjson(path)}
    last = state.puzzles.lastDate
    new_lines: list[tuple[int, str]] = []
    before: int | None = None
    while True:
        params = {"max": page, "before": before, "since": last + 1 if last else None}
        batch = list(client.stream_ndjson_lines("/api/puzzle/activity", params))
        if not batch:
            break
        reached_known = False
        oldest = None
        for line in batch:
            p = json.loads(line)
            oldest = p["date"] if oldest is None else min(oldest, p["date"])
            if (last is not None and p["date"] <= last) or _puzzle_key(p) in known:
                reached_known = True
                continue
            new_lines.append((p["date"], line))
            known.add(_puzzle_key(p))
        log.info("puzzles: %d fetched so far…", len(new_lines))
        if reached_known or len(batch) < page or oldest is None:
            break
        before = oldest
    new_lines.sort(key=lambda t: t[0])  # chronological on disk
    if new_lines:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as out:
            out.writelines(line + "\n" for _, line in new_lines)
        state.puzzles.lastDate = max(state.puzzles.lastDate or 0, new_lines[-1][0])
    state.puzzles.count = len(known)
    return SyncResult("puzzles", len(new_lines))


# -- ratings & snapshots ------------------------------------------------------


def sync_ratings(
    client: LichessClient, cfg: Config, state: State, path: Path = RATINGS_PATH
) -> SyncResult:
    history = client.get_json(f"/api/user/{cfg.lichess.username}/rating-history")
    if not history and not client.has_token:
        # unauthenticated requests may get an empty cached copy; keep the old file
        return SyncResult("ratings", 0, skipped="empty response without token")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(history, indent=1) + "\n", encoding="utf-8")
    state.ratingsFetchedAt = now_ms()
    return SyncResult("ratings", sum(len(p["points"]) for p in history))


def snapshot(client: LichessClient, cfg: Config, directory: Path = SNAPSHOTS) -> SyncResult:
    """Weekly: 30-day puzzle dashboard + storm dashboard → raw/snapshots/YYYY-Www.json."""
    week = iso_week()
    snap: dict = {"week": week, "takenAt": now_ms()}
    snap["storm"] = client.get_json(f"/api/storm/dashboard/{cfg.lichess.username}", {"days": 30})
    if client.has_token:
        snap["puzzleDashboard"] = client.get_json("/api/puzzle/dashboard/30")
    else:
        log.warning("snapshot: no token, puzzle dashboard skipped")
    directory.mkdir(parents=True, exist_ok=True)
    (directory / f"{week}.json").write_text(json.dumps(snap, indent=1) + "\n", encoding="utf-8")
    return SyncResult("snapshot", 1)
