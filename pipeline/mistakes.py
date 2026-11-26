"""Critical-moment extraction into data/mistakes.jsonl (DESIGN.md §6.2, §7.2).

mistakes.jsonl is state, not raw data: it is rewritten in a stable order, keeps each
position's review state and first-seen `createdAt`, and is only written when it changes.
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from pathlib import Path

from .analyze import ANALYSIS_DIR, replay
from .config import Config
from .fetch import GAMES_PATH, iter_ndjson
from .models import Mistake
from .review import new_review
from .state import DATA, now_ms
from .tags import Moment, tag_moment
from .taxonomy import load_taxonomy

MISTAKES_PATH = DATA / "mistakes.jsonl"
# Skip moments that teach little: already lost before, or still clearly winning after.
LOST_BEFORE = 15.0
STILL_WINNING_AFTER = 80.0


def is_critical(ply: dict) -> bool:
    if not ply["byPlayer"]:
        return False
    if not (ply["class"] in ("mistake", "blunder") or ply.get("missedWin")):
        return False
    return ply["winBefore"] > LOST_BEFORE and ply["winAfter"] < STILL_WINNING_AFTER


def extract_game(
    game: dict, analysis: dict, today: date, created: int, boxes_days: list[int]
) -> list[Mistake]:
    start, moves = replay(game)
    positions = analysis["positions"]
    taxonomy = load_taxonomy()
    out = []
    board = start.copy()
    for i, (move, ply) in enumerate(zip(moves, analysis["plies"], strict=True)):
        if is_critical(ply):
            fen = board.fen()
            moment = Moment(
                fen=fen,
                played=move.uci(),
                best_pv=positions[i]["pv"],
                reply_pv=positions[i + 1]["pv"],
                mate_before=ply["mateBefore"],
                mate_after=ply["mateAfter"],
                win_before=ply["winBefore"],
                phase=ply["phase"],
                time_pressure=ply["timePressure"],
                result=analysis["summary"]["result"],
                move_class=ply["class"],
            )
            tags = tag_moment(moment)
            unknown = [t for t in tags if t not in taxonomy]
            if unknown:
                raise ValueError(f"tags not in taxonomy.yaml: {unknown}")
            out.append(
                Mistake(
                    id=f"{game['id']}-{ply['ply']}",
                    gameId=game["id"],
                    perf=analysis["perf"],
                    ply=ply["ply"],
                    url=f"https://lichess.org/{game['id']}/{analysis['playerColor']}#{ply['ply']}",
                    fen=fen,
                    playerColor=analysis["playerColor"],
                    played=ply["san"],
                    best=ply["bestSan"],
                    pv=ply["pvSan"],
                    cls=ply["class"],
                    winBefore=ply["winBefore"],
                    winDrop=ply["winDrop"],
                    phase=ply["phase"],
                    timePressure=ply["timePressure"],
                    missedWin=ply.get("missedWin", False),
                    tags=tags,
                    gameCreatedAt=game["createdAt"],
                    createdAt=created,
                    review=new_review(today, boxes_days),
                )
            )
        board.push(move)
    return out


def load_mistakes(path: Path = MISTAKES_PATH) -> dict[str, Mistake]:
    return {m["id"]: Mistake.model_validate(m) for m in iter_ndjson(path)}


def dump_line(m: Mistake) -> str:
    return json.dumps(m.model_dump(mode="json", by_alias=True), ensure_ascii=False)


def run(
    cfg: Config,
    *,
    games_path: Path = GAMES_PATH,
    analysis_dir: Path = ANALYSIS_DIR,
    path: Path = MISTAKES_PATH,
    today: date | None = None,
) -> dict[str, int]:
    today = today or datetime.now(UTC).date()
    created = now_ms()
    games = {g["id"]: g for g in iter_ndjson(games_path)}
    existing = load_mistakes(path)
    result: dict[str, Mistake] = {}
    for file in sorted(analysis_dir.glob("*.json")):
        analysis = json.loads(file.read_text(encoding="utf-8"))
        game = games.get(analysis["gameId"])
        if game is None:
            continue
        for m in extract_game(game, analysis, today, created, cfg.review.boxes_days):
            old = existing.get(m.id)
            if old is not None:
                m = m.model_copy(update={"review": old.review, "createdAt": old.createdAt})
            result[m.id] = m
    # keep positions that dropped out of the critical set only if they were already reviewed
    kept = {k: v for k, v in existing.items() if k not in result and v.review.attempts > 0}
    result.update(kept)
    ordered = sorted(result.values(), key=lambda m: (m.gameCreatedAt, m.ply))
    text = "".join(dump_line(m) + "\n" for m in ordered)
    changed = not path.exists() or path.read_text(encoding="utf-8") != text
    if changed:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return {
        "positions": len(ordered),
        "new": sum(1 for k in result if k not in existing),
        "written": int(changed),
    }
