"""Aggregates for the coach and the dashboard (DESIGN.md §7.4).

Everything here is a pure function of data/raw + data/analysis (+ mistakes/reviews state),
so derived files are reproducible. Every metric carries its sample size `n`.
"""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from collections.abc import Iterable
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from .analyze import ANALYSIS_DIR
from .config import Config
from .fetch import PUZZLES_PATH, RATINGS_PATH, SNAPSHOTS, iter_ndjson
from .state import DATA

DERIVED = DATA / "derived"
METRICS_PATH = DERIVED / "metrics.json"
WEEKLY_DIR = DERIVED / "weekly"
REVIEWS_PATH = DATA / "reviews.jsonl"

PHASES = ("opening", "middlegame", "endgame")
ERRORS = ("mistake", "blunder")
CLOCK_MOVES = (20, 30, 40)
WINNING, LOSING = 75.0, 25.0
OPENING_MIN_N = 3


# -- helpers --------------------------------------------------------------------


def to_date(ms: int) -> date:
    return datetime.fromtimestamp(ms / 1000, UTC).date()


def week_of(ms: int) -> str:
    y, w, _ = to_date(ms).isocalendar()
    return f"{y}-W{w:02d}"


def rate(k: int, n: int) -> dict:
    return {"value": round(k / n, 3) if n else None, "k": k, "n": n}


def mean(xs: list[float], digits: int = 2) -> dict:
    return {"value": round(sum(xs) / len(xs), digits) if xs else None, "n": len(xs)}


def load_analyses(directory: Path = ANALYSIS_DIR) -> list[dict]:
    out = []
    for f in sorted(directory.glob("*.json")):
        a = json.loads(f.read_text(encoding="utf-8"))
        a.pop("positions", None)  # not needed here; keeps memory small
        out.append(a)
    return sorted(out, key=lambda a: a["createdAt"])


def opening_family(a: dict) -> str | None:
    name = (a.get("opening") or {}).get("name")
    return name.split(":")[0].strip() if name else None


# -- games ----------------------------------------------------------------------


def game_metrics(analyses: list[dict]) -> dict:
    """Leading + lagging indicators for one set of games (one perf, one window)."""
    n = len(analyses)
    per_phase: dict[str, Counter] = {p: Counter() for p in PHASES}
    errors_total = errors_tp = errors_with_clock = 0
    clock_at: dict[int, list[float]] = {m: [] for m in CLOCK_MOVES}
    results = Counter()
    conv_n = conv_k = save_n = save_k = missed = 0
    acpl, acc = [], []
    openings: dict[tuple[str, str], Counter] = defaultdict(Counter)

    for a in analyses:
        color = a["playerColor"]
        s = a["summary"]
        results[s["result"]] += 1
        acpl.append(s["acpl"])
        if s["accuracy"] is not None:
            acc.append(s["accuracy"])
        missed += s["missedWins"]
        if s["maxAdvantageWin"] >= WINNING:
            conv_n += 1
            conv_k += s["result"] == "win"
        if s["minWin"] <= LOSING:
            save_n += 1
            save_k += s["result"] != "loss"
        has_clock = bool(a.get("clockInitial"))
        for p in a["plies"]:
            if not p["byPlayer"]:
                continue
            per_phase[p["phase"]][p["class"]] += 1
            if p["class"] in ERRORS:
                errors_total += 1
                if has_clock and p["clockLeft"] is not None:
                    errors_with_clock += 1
                    errors_tp += p["timePressure"]
        if has_clock:
            for move in CLOCK_MOVES:
                ply = 2 * move - 1 if color == "white" else 2 * move
                if ply <= len(a["plies"]):
                    left = a["plies"][ply - 1]["clockLeft"]
                    if left is not None:
                        clock_at[move].append(left / a["clockInitial"])
        fam = opening_family(a)
        if fam:
            openings[(fam, color)][s["result"]] += 1

    def per_game(counter_key: str) -> dict:
        return {ph: round(per_phase[ph][counter_key] / n, 2) if n else None for ph in PHASES} | {
            "total": round(sum(per_phase[ph][counter_key] for ph in PHASES) / n, 2) if n else None
        }

    by_opening = []
    for (fam, color), res in sorted(openings.items()):
        games = sum(res.values())
        if games >= OPENING_MIN_N:
            score = (res["win"] + 0.5 * res["draw"]) / games
            by_opening.append(
                {"family": fam, "color": color, "n": games, "score": round(score, 3), **res}
            )

    return {
        "n": n,
        "results": {"win": results["win"], "draw": results["draw"], "loss": results["loss"]},
        "score": rate(results["win"] * 2 + results["draw"], 2 * n),
        "blundersPerGame": per_game("blunder"),
        "mistakesPerGame": per_game("mistake"),
        "inaccuraciesPerGame": per_game("inaccuracy"),
        "errorsByPhase": {ph: sum(per_phase[ph][c] for c in ERRORS) for ph in PHASES},
        "timePressureErrorShare": rate(errors_tp, errors_with_clock),
        "clockShareAtMove": {str(m): mean(v, 3) for m, v in clock_at.items()},
        "conversionRate": rate(conv_k, conv_n),
        "saveRate": rate(save_k, save_n),
        "missedWins": {"value": missed, "n": n},
        "acpl": mean(acpl, 1),
        "accuracy": mean(acc, 1),
        "byOpening": by_opening,
    }


# -- puzzles --------------------------------------------------------------------


def puzzle_metrics(puzzles: list[dict], min_theme_n: int = 1) -> dict:
    wins = sum(p["win"] for p in puzzles)
    themes: dict[str, Counter] = defaultdict(Counter)
    for p in puzzles:
        for t in p["puzzle"].get("themes", []):
            themes[t]["n"] += 1
            themes[t]["win"] += p["win"]
    ratings = [p["puzzle"]["rating"] for p in puzzles if "rating" in p["puzzle"]]
    return {
        "n": len(puzzles),
        "winRate": rate(wins, len(puzzles)),
        "avgPuzzleRating": mean(ratings, 0),
        "themes": {
            t: rate(c["win"], c["n"])
            for t, c in sorted(themes.items(), key=lambda kv: -kv[1]["n"])
            if c["n"] >= min_theme_n
        },
    }


# -- ratings, storm, reviews -----------------------------------------------------


def rating_series(history: list[dict]) -> dict[str, list[list]]:
    """Lichess rating history → {perf: [[YYYY-MM-DD, rating], ...]} (month is 0-based there)."""
    out = {}
    for entry in history:
        if entry["points"]:
            out[entry["name"].lower()] = [
                [date(y, m + 1, d).isoformat(), r] for y, m, d, r in entry["points"]
            ]
    return out


def storm_metrics(snapshot_dir: Path = SNAPSHOTS) -> dict:
    latest = sorted(snapshot_dir.glob("*.json"))
    if not latest:
        return {"n": 0}
    snap = json.loads(latest[-1].read_text(encoding="utf-8"))
    storm = snap.get("storm") or {}
    days = storm.get("days") or []
    # day entries look like {"_id": "2026/11/27", "score": .., "runs": .., ...}; unverified
    # against real data so far (account has no Storm runs), hence the tolerant lookup
    scores = [d.get("score", d.get("highest")) for d in days]
    scores = [x for x in scores if x is not None]
    return {
        "week": snap.get("week"),
        "high": (storm.get("high") or {}).get("allTime") or None,
        "runs30d": sum(d.get("runs", 0) for d in days),
        "best30d": max(scores) if scores else None,
        "avgDailyBest30d": mean(scores, 1),
        "n": len(scores),
    }


def review_metrics(reviews: list[dict]) -> dict:
    attempted = [r for r in reviews if r.get("result") in ("correct", "wrong")]
    return {"successRate": rate(sum(r["result"] == "correct" for r in attempted), len(attempted))}


# -- windows & orchestration ------------------------------------------------------


def _in_window(ms: int, start: date, end: date) -> bool:
    return start <= to_date(ms) <= end


def windows(today: date) -> dict[str, tuple[date, date]]:
    return {
        "last4Weeks": (today - timedelta(days=27), today),
        "last12Months": (today - timedelta(days=365), today),
        "allTime": (date(2000, 1, 1), today),
    }


def build(
    cfg: Config,
    today: date,
    analyses: list[dict],
    puzzles: list[dict],
    ratings: list[dict],
    reviews: list[dict],
    storm: dict,
) -> tuple[dict, dict[str, dict]]:
    perfs = sorted(
        {a["perf"] for a in analyses},
        key=lambda p: (
            cfg.training.tracked_perfs.index(p) if p in cfg.training.tracked_perfs else 99
        ),
    )
    win = windows(today)
    games: dict[str, dict] = {}
    for perf in perfs:
        mine = [a for a in analyses if a["perf"] == perf]
        games[perf] = {
            name: game_metrics([a for a in mine if _in_window(a["createdAt"], s, e)])
            for name, (s, e) in win.items()
        }
    puzzle_windows = {
        name: puzzle_metrics([p for p in puzzles if _in_window(p["date"], s, e)])
        for name, (s, e) in win.items()
    }

    # weekly aggregates (only weeks with activity)
    by_week_games: dict[str, list[dict]] = defaultdict(list)
    for a in analyses:
        by_week_games[week_of(a["createdAt"])].append(a)
    by_week_puzzles: dict[str, list[dict]] = defaultdict(list)
    for p in puzzles:
        by_week_puzzles[week_of(p["date"])].append(p)
    by_week_reviews: dict[str, list[dict]] = defaultdict(list)
    for r in reviews:
        by_week_reviews[r.get("week") or week_of(r["at"])].append(r)

    weekly: dict[str, dict] = {}
    for wk in sorted(set(by_week_games) | set(by_week_puzzles) | set(by_week_reviews)):
        wg = by_week_games.get(wk, [])
        weekly[wk] = {
            "week": wk,
            "games": {
                perf: game_metrics([a for a in wg if a["perf"] == perf])
                for perf in perfs
                if any(a["perf"] == perf for a in wg)
            },
            "puzzles": puzzle_metrics(by_week_puzzles.get(wk, [])),
            "reviews": review_metrics(by_week_reviews.get(wk, [])),
        }

    series = [
        {
            "week": wk,
            **{
                f"{perf}.{k}": v
                for perf, gm in w["games"].items()
                for k, v in (
                    ("games", gm["n"]),
                    ("blundersPerGame", gm["blundersPerGame"]["total"]),
                    ("timePressureErrorShare", gm["timePressureErrorShare"]["value"]),
                    ("accuracy", gm["accuracy"]["value"]),
                )
            },
            "puzzles.n": w["puzzles"]["n"],
            "puzzles.winRate": w["puzzles"]["winRate"]["value"],
        }
        for wk, w in weekly.items()
    ]

    latest_data = max([a["createdAt"] for a in analyses] + [p["date"] for p in puzzles] + [0])
    metrics = {
        "asOf": today.isoformat(),
        "latestDataAt": latest_data,
        "mainPerf": cfg.training.main_perf,
        "games": games,
        "puzzles": puzzle_windows,
        "ratings": rating_series(ratings),
        "storm": storm,
        "reviews": review_metrics(reviews),
        "weeklySeries": series,
    }
    return metrics, weekly


def _write_json_if_changed(path: Path, obj: dict) -> bool:
    text = json.dumps(obj, indent=1, ensure_ascii=False) + "\n"
    if path.exists() and path.read_text(encoding="utf-8") == text:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return True


def run(cfg: Config, today: date | None = None) -> dict[str, int]:
    today = today or datetime.now(UTC).date()
    ratings = json.loads(RATINGS_PATH.read_text()) if RATINGS_PATH.exists() else []
    metrics, weekly = build(
        cfg,
        today,
        load_analyses(),
        list(iter_ndjson(PUZZLES_PATH)),
        ratings,
        list(iter_ndjson(REVIEWS_PATH)),
        storm_metrics(),
    )
    written = int(_write_json_if_changed(METRICS_PATH, metrics))
    for wk, w in weekly.items():
        written += _write_json_if_changed(WEEKLY_DIR / f"{wk}.json", w)
    return {"weeks": len(weekly), "written": written}


def iter_perf_analyses(analyses: Iterable[dict], perfs: Iterable[str]) -> list[dict]:
    keep = set(perfs)
    return [a for a in analyses if a["perf"] in keep]
