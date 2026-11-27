"""Weekly review check-in via a GitHub issue (DESIGN.md §7.3).

`render` writes the issue body: one item per position in the review study with two
checkboxes ("solved" / "missed"). `apply` parses a closed issue back into reviews.jsonl and
moves positions between Leitner boxes. Neither box ticked = not attempted (stays due).
Applying the same issue twice is a no-op.
"""

from __future__ import annotations

import json
import re
from datetime import date, timedelta
from pathlib import Path

import chess

from .config import Config
from .fetch import iter_ndjson
from .metrics import REVIEWS_PATH
from .mistakes import MISTAKES_PATH, dump_line, load_mistakes
from .publish_study import COLOR_ACC, study_url
from .review import apply_result
from .state import State, iso_week, now_ms

ITEM = re.compile(r"^- \*\*\d+\.\s+`(?P<id>[A-Za-z0-9]{8}-\d+)`")
BOX = re.compile(r"^\s+- \[(?P<mark>[ xX])\]\s+(?P<label>.+)$")
SOLVED, MISSED = "решил верно", "ошибся"


def render(cfg: Config, state: State, today: date, mistakes_path: Path = MISTAKES_PATH) -> str:
    mistakes = load_mistakes(mistakes_path)
    study_id = state.study.studyId or cfg.lichess.review_study_id
    week = iso_week(today + timedelta(days=1))  # issued on Sunday for the coming week
    study_link = study_url(study_id) if study_id else "#"
    lines = [
        f"Позиции недели **{week}** из [учебного разбора]({study_link}).",
        "",
        f"Отметьте для каждой позиции «{SOLVED}» или «{MISSED}» и закройте issue.",
        "Если ничего не отмечено — позиция считается непросмотренной и вернётся снова.",
        "",
        f"<!-- chess-coach checkin week={week} -->",
        "",
    ]
    for i, (mid, chapter_id) in enumerate(state.study.chapters.items(), 1):
        m = mistakes.get(mid)
        if m is None:
            continue
        link = study_url(study_id, chapter_id) if study_id else m.url
        lines += [
            f"- **{i}. `{m.id}`** — ход {chess.Board(m.fen).fullmove_number} за "
            f"{COLOR_ACC[m.playerColor]} · "
            f"[позиция]({link}) · [партия]({m.url})",
            f"  - [ ] {SOLVED}",
            f"  - [ ] {MISSED}",
        ]
    if not state.study.chapters:
        lines.append("_На этой неделе в разборе нет позиций._")
    return "\n".join(lines) + "\n"


def parse(body: str) -> dict[str, str]:
    """Issue body → {mistake id: correct | wrong | skipped}."""
    results: dict[str, str] = {}
    current = None
    marks: dict[str, set[str]] = {}
    for line in body.splitlines():
        if m := ITEM.match(line):
            current = m["id"]
            marks[current] = set()
            continue
        if current and (b := BOX.match(line)) and b["mark"].lower() == "x":
            marks[current].add(b["label"].strip())
    for mid, ticked in marks.items():
        if MISSED in ticked:
            results[mid] = "wrong"  # both ticked counts as wrong: be conservative
        elif SOLVED in ticked:
            results[mid] = "correct"
        else:
            results[mid] = "skipped"
    return results


def week_from_body(body: str) -> str | None:
    m = re.search(r"chess-coach checkin week=(\d{4}-W\d{2})", body)
    return m[1] if m else None


def apply(
    body: str,
    issue: int,
    cfg: Config,
    today: date,
    *,
    mistakes_path: Path = MISTAKES_PATH,
    reviews_path: Path = REVIEWS_PATH,
) -> dict[str, int]:
    done = {(r["issue"], r["id"]) for r in iter_ndjson(reviews_path)}
    results = parse(body)
    week = week_from_body(body) or iso_week(today)
    mistakes = load_mistakes(mistakes_path)
    rows = []
    for mid, result in results.items():
        if (issue, mid) in done or mid not in mistakes:
            continue
        m = mistakes[mid]
        mistakes[mid] = m.model_copy(
            update={"review": apply_result(m.review, result, today, cfg.review.boxes_days)}
        )
        rows.append({"id": mid, "result": result, "week": week, "issue": issue, "at": now_ms()})
    if rows:
        reviews_path.parent.mkdir(parents=True, exist_ok=True)
        with reviews_path.open("a", encoding="utf-8") as f:
            f.writelines(json.dumps(r, ensure_ascii=False) + "\n" for r in rows)
        ordered = sorted(mistakes.values(), key=lambda m: (m.gameCreatedAt, m.ply))
        mistakes_path.write_text("".join(dump_line(m) + "\n" for m in ordered), encoding="utf-8")
    counts = {"correct": 0, "wrong": 0, "skipped": 0}
    for r in rows:
        counts[r["result"]] += 1
    return {"recorded": len(rows), **counts}
