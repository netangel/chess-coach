"""Build the static dashboard into dist/ (DESIGN.md §10).

Everything the page needs is assembled into one `dashboard.json`; Markdown (plan, journal)
is rendered to HTML here so the page has no runtime dependencies.
"""

from __future__ import annotations

import json
import shutil
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import markdown
import yaml

from .config import ROOT, Config
from .diagnose import DIAGNOSIS_PATH
from .fetch import GAMES_PATH, PUZZLES_PATH, iter_ndjson
from .metrics import METRICS_PATH, REVIEWS_PATH, to_date
from .mistakes import MISTAKES_PATH, load_mistakes
from .publish_study import study_url
from .state import State, iso_week

SITE = ROOT / "site"
DIST = ROOT / "dist"
PLAN_PATH = ROOT / "plan" / "current.md"
JOURNAL_DIR = ROOT / "journal"
STREAK_LOOKBACK = 120


def render_md(text: str) -> str:
    return markdown.markdown(text, extensions=["tables", "fenced_code", "sane_lists"])


def split_front_matter(text: str) -> tuple[dict, str]:
    if text.startswith("---"):
        _, fm, body = text.split("---", 2)
        return yaml.safe_load(fm) or {}, body.lstrip()
    return {}, text


def latest_journal(directory: Path = JOURNAL_DIR) -> Path | None:
    """Newest weekly journal (YYYY-Www.md); the baseline report until the first one exists."""
    weekly = sorted(directory.glob("[0-9][0-9][0-9][0-9]-W[0-9][0-9].md"))
    if weekly:
        return weekly[-1]
    baseline = directory / "baseline.md"
    return baseline if baseline.exists() else None


def activity(today: date) -> dict:
    """Active days (a game or a puzzle) → current streak, plus this week's counts."""
    days: set[date] = set()
    week = iso_week(today)
    games_week: dict[str, int] = {}
    for g in iter_ndjson(GAMES_PATH):
        d = to_date(g["createdAt"])
        days.add(d)
        if iso_week(d) == week:
            games_week[g["perf"]] = games_week.get(g["perf"], 0) + 1
    puzzles_week = puzzle_wins = 0
    for p in iter_ndjson(PUZZLES_PATH):
        d = to_date(p["date"])
        days.add(d)
        if iso_week(d) == week:
            puzzles_week += 1
            puzzle_wins += p["win"]
    reviews_week = [r for r in iter_ndjson(REVIEWS_PATH) if r.get("week") == week]
    streak = 0
    d = today if today in days else today - timedelta(days=1)  # today may still come
    while d in days and streak < STREAK_LOOKBACK:
        streak += 1
        d -= timedelta(days=1)
    return {
        "streak": streak,
        "activeToday": today in days,
        "week": week,
        "gamesByPerf": games_week,
        "puzzles": puzzles_week,
        "puzzleWins": puzzle_wins,
        "reviews": {
            "correct": sum(r["result"] == "correct" for r in reviews_week),
            "wrong": sum(r["result"] == "wrong" for r in reviews_week),
        },
    }


def latest_game(cfg: Config, state: State, mistakes: dict) -> dict | None:
    """The most recent game with its result and critical moments (study chapter links)."""
    from .analyze import analysis_path, player_color
    from .publish_study import chapter_name

    games = [
        g for g in iter_ndjson(GAMES_PATH) if player_color(g, cfg.lichess.username) is not None
    ]
    if not games:
        return None
    g = max(games, key=lambda x: x["createdAt"])
    color = "white" if player_color(g, cfg.lichess.username) else "black"
    opp_side = g["players"]["black" if color == "white" else "white"]
    opponent = (opp_side.get("user") or {}).get("name") or (
        f"Stockfish {opp_side['aiLevel']}" if "aiLevel" in opp_side else "анонима"
    )
    winner = g.get("winner")
    result = "draw" if winner is None else ("win" if winner == color else "loss")
    clock = g.get("clock") or {}
    study_id = state.study.studyId or cfg.lichess.review_study_id
    summary = None
    apath = analysis_path(g["id"])
    if apath.exists():
        s = json.loads(apath.read_text(encoding="utf-8"))["summary"]
        summary = {k: s[k] for k in ("accuracy", "blunders", "mistakes", "inaccuracies")}
    not_analysed = None
    if summary is None:
        if g["perf"] not in cfg.analysis.only_perfs:
            not_analysed = "perf"
        elif len(g.get("moves", "").split()) < cfg.analysis.min_plies:
            not_analysed = "short"
        else:
            not_analysed = "pending"  # analysed by the next nightly run
    moments = []
    for m in sorted((m for m in mistakes.values() if m.gameId == g["id"]), key=lambda m: m.ply):
        chapter = state.study.chapters.get(m.id)
        moments.append(
            {
                "label": chapter_name(m).split(" · ")[0],
                "played": m.played,
                "winDrop": m.winDrop,
                "url": study_url(study_id, chapter) if (study_id and chapter) else m.url,
                "inStudy": bool(chapter),
            }
        )
    return {
        "id": g["id"],
        "url": f"https://lichess.org/{g['id']}/{color}",
        "date": to_date(g["createdAt"]).isoformat(),
        "perf": g["perf"],
        "rated": g.get("rated", False),
        "clock": f"{clock['initial'] // 60}+{clock['increment']}" if clock else None,
        "color": color,
        "opponent": opponent,
        "opponentRating": opp_side.get("rating"),
        "result": result,
        "status": g.get("status"),
        "analysed": summary is not None,
        "notAnalysed": not_analysed,
        "summary": summary,
        "moments": moments,
    }


def build_dashboard(cfg: Config, state: State, today: date) -> dict:
    metrics = json.loads(METRICS_PATH.read_text()) if METRICS_PATH.exists() else {}
    diagnosis = json.loads(DIAGNOSIS_PATH.read_text()) if DIAGNOSIS_PATH.exists() else None

    plan = None
    if PLAN_PATH.exists():
        fm, body = split_front_matter(PLAN_PATH.read_text(encoding="utf-8"))
        plan = {**fm, "html": render_md(body)}

    journal = None
    if (jpath := latest_journal()) is not None:
        journal = {"name": jpath.stem, "html": render_md(jpath.read_text(encoding="utf-8"))}

    mistakes = load_mistakes(MISTAKES_PATH)
    study_id = state.study.studyId or cfg.lichess.review_study_id
    due_today = sum(1 for m in mistakes.values() if m.review.due <= today)

    main = cfg.training.main_perf
    return {
        "generatedAt": datetime.now(UTC).isoformat(timespec="minutes"),
        "today": today.isoformat(),
        "username": cfg.lichess.username,
        "mainPerf": main,
        "budget": cfg.training.budget.model_dump(),
        "plan": plan,
        "study": {
            "url": study_url(study_id) if study_id else None,
            "chapters": len(state.study.chapters),
            "dueToday": due_today,
            "perDay": cfg.review.max_due_per_day,
        },
        "activity": activity(today),
        "latestGame": latest_game(cfg, state, mistakes),
        "games": metrics.get("games", {}),
        "puzzles": metrics.get("puzzles", {}),
        "ratings": metrics.get("ratings", {}),
        "storm": metrics.get("storm", {}),
        "weeklySeries": metrics.get("weeklySeries", []),
        "diagnosis": diagnosis,
        "journal": journal,
        "sync": {
            "lastSyncAt": state.lastSyncAt,
            "tokenExpiresAt": state.token.expiresAt,
        },
    }


def build(cfg: Config, state: State, today: date | None = None, out: Path = DIST) -> Path:
    today = today or datetime.now(UTC).date()
    if out.exists():
        shutil.rmtree(out)
    shutil.copytree(SITE, out)
    data = build_dashboard(cfg, state, today)
    (out / "dashboard.json").write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    (out / ".nojekyll").write_text("")
    return out
