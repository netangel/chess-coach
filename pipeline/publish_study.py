"""Due review positions → one private Lichess study (DESIGN.md §7.3).

The study holds the positions due within the coming week (≤ max_due_per_day × 7, capped at
max_chapters). Each chapter is an interactive gamebook: the engine's best line is the main line
(the move to find) and the move played in the game is a commented side line. The study is only
rewritten when the selected set changes, so most nightly runs make no API writes.
"""

from __future__ import annotations

import io
import logging
import re
from datetime import date, timedelta

import chess
import chess.pgn

from .config import ROOT, Config
from .lichess_client import LichessClient
from .mistakes import MISTAKES_PATH, load_mistakes
from .models import Mistake
from .review import select_due
from .state import State, now_ms

log = logging.getLogger(__name__)

WEEK_DAYS = 7
SOLUTION_PLIES = 3
STUDY_NAME = "chess-coach: разбор своих ошибок"
CLASS_RU = {"blunder": "зевок", "mistake": "ошибка", "inaccuracy": "неточность"}
COLOR_RU = {"white": "белые", "black": "чёрные"}
COLOR_ACC = {"white": "белых", "black": "чёрных"}
CHAPTER_URL = re.compile(r'\[ChapterURL "https://lichess\.org/study/\w+/(\w+)"\]')


# -- selection --------------------------------------------------------------------


def select_week(mistakes: dict[str, Mistake], cfg: Config, today: date) -> list[Mistake]:
    limit = min(cfg.review.max_due_per_day * WEEK_DAYS, cfg.review.max_chapters)
    horizon = today + timedelta(days=WEEK_DAYS - 1)
    items = [(m.id, m.review, m.winDrop) for m in mistakes.values()]
    return [mistakes[i] for i in select_due(items, horizon, limit)]


# -- PGN ------------------------------------------------------------------------


def move_label(m: Mistake) -> str:
    board = chess.Board(m.fen)
    dots = "." if board.turn == chess.WHITE else "..."
    return f"{board.fullmove_number}{dots}"


def chapter_name(m: Mistake) -> str:
    board = chess.Board(m.fen)
    return (
        f"Ход {board.fullmove_number}, {COLOR_RU[m.playerColor]} "
        f"({CLASS_RU.get(m.cls, m.cls)}) · {m.gameId}"
    )[:100]


def chapter_pgn(m: Mistake) -> str:
    board = chess.Board(m.fen)
    game = chess.pgn.Game()
    game.setup(board)
    game.headers["Event"] = chapter_name(m)
    game.headers["Site"] = m.url
    game.headers["Annotator"] = "chess-coach"
    game.comment = (
        f"Найдите лучший ход за {COLOR_ACC[m.playerColor]}. "
        f"Позиция из вашей партии {m.url} — там было сыграно {move_label(m)} {m.played}."
    )
    node = game
    b = board.copy()
    played = b.parse_san(m.played)
    for i, san in enumerate(m.pv[:SOLUTION_PLIES]):
        move = b.parse_san(san)
        child = node.add_main_variation(move)
        if i == 0:
            if played != move:
                side = node.add_variation(played)
                side.comment = (
                    f"Так было в партии: {CLASS_RU.get(m.cls, m.cls)}, "
                    f"−{m.winDrop:.0f}% шансов. Лучше {san}."
                )
            child.comment = "Верно!" if len(m.pv) > 1 else "Верно! Это лучший ход."
        b.push(move)
        node = child
    exporter = chess.pgn.StringExporter(headers=True, variations=True, comments=True)
    return game.accept(exporter)


def build_pgns(selected: list[Mistake]) -> list[tuple[Mistake, str, str]]:
    """(mistake, chapter name, PGN) in selection order."""
    return [(m, chapter_name(m), chapter_pgn(m)) for m in selected]


# -- Lichess --------------------------------------------------------------------


def list_chapter_ids(client: LichessClient, study_id: str) -> list[str]:
    pgn = client.get_text(f"/api/study/{study_id}.pgn", {"clocks": False, "comments": False})
    return CHAPTER_URL.findall(pgn)


def create_study(client: LichessClient) -> str:
    resp = client.post_form(
        "/api/study",
        {
            "name": STUDY_NAME,
            "visibility": "private",
            "computer": "owner",
            "explorer": "owner",
            "cloneable": "nobody",
            "shareable": "owner",  # "nobody" also blocks the owner's own PGN export
            "chat": "nobody",
            "sticky": False,
        },
    )
    return resp["id"]


def save_study_id(study_id: str, path=ROOT / "config.yaml") -> None:
    text = path.read_text(encoding="utf-8")
    new, n = re.subn(r"(review_study_id:\s*)null", rf"\g<1>{study_id}", text, count=1)
    if n != 1:
        raise RuntimeError("could not find `review_study_id: null` in config.yaml")
    path.write_text(new, encoding="utf-8")


def publish(
    client: LichessClient,
    cfg: Config,
    state: State,
    today: date,
    *,
    dry_run: bool = False,
    force: bool = False,
    mistakes_path=MISTAKES_PATH,
) -> dict:
    mistakes = load_mistakes(mistakes_path)
    selected = select_week(mistakes, cfg, today)
    chapters_pgn = build_pgns(selected)
    if dry_run:
        for m, name, pgn in chapters_pgn:
            print(f"--- {name} (orientation={m.playerColor})\n{pgn}\n")
        return {"selected": len(selected), "dryRun": True}

    study_id = cfg.lichess.review_study_id
    if not study_id:
        raise RuntimeError("lichess.review_study_id is not set (run `study --init`)")
    wanted = [m.id for m in selected]
    same_study = state.study.studyId == study_id
    if not force and same_study and set(state.study.chapters) == set(wanted):
        return {"selected": len(selected), "changed": False}

    # Incremental: positions that stay keep their chapter (links in the open check-in issue
    # keep working); removed ones are deleted, new ones imported.
    existing = list_chapter_ids(client, study_id)
    tracked = (
        {mid: cid for mid, cid in state.study.chapters.items() if cid in existing}
        if same_study and not force
        else {}
    )
    keep = {mid: tracked[mid] for mid in wanted if mid in tracked}
    remove = [cid for cid in existing if cid not in keep.values()]
    # a study can never be empty: if nothing is kept, delete the last old chapter at the end
    held_back = remove[-1:] if not keep else []
    for cid in remove:
        if cid not in held_back:
            client.delete(f"/api/study/{study_id}/{cid}")
    chapters = dict(keep)
    by_id = {m.id: (m, name, pgn) for m, name, pgn in chapters_pgn}
    added = 0
    for mid in wanted:
        if mid in chapters:
            continue
        m, name, pgn = by_id[mid]
        resp = client.post_form(
            f"/api/study/{study_id}/import-pgn",
            {"pgn": pgn, "name": name, "orientation": m.playerColor, "mode": "gamebook"},
        )
        created = (resp or {}).get("chapters") or []
        if (resp or {}).get("error") or len(created) != 1:
            raise RuntimeError(f"import of {m.id} failed: {resp}")
        chapters[mid] = created[0]["id"]
        added += 1
    if chapters:
        for cid in held_back:
            client.delete(f"/api/study/{study_id}/{cid}")

    state.study.studyId = study_id
    state.study.chapters = {mid: chapters[mid] for mid in wanted}
    state.study.publishedAt = now_ms()
    return {
        "selected": len(selected),
        "changed": True,
        "added": added,
        "deleted": len(remove) if chapters else len(remove) - len(held_back),
    }


def study_url(study_id: str, chapter_id: str | None = None) -> str:
    return f"https://lichess.org/study/{study_id}" + (f"/{chapter_id}" if chapter_id else "")


def _pgn_games(text: str) -> list[chess.pgn.Game]:  # used by tests
    stream = io.StringIO(text)
    games = []
    while (g := chess.pgn.read_game(stream)) is not None:
        games.append(g)
    return games
