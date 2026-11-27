"""Rule-based, transparent weakness scoring per taxonomy skill (DESIGN.md §7.5).

Each rule turns one observable signal into a score in [0, 1] for one skill, with its sample
size and a plain-language evidence line. Scores of the same skill are combined with a noisy-OR
(1 - Π(1 - s)), so independent signals reinforce each other without exceeding 1.
The diagnosis proposes; the coach (Claude) decides the plan.
"""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta

from .config import Config
from .fetch import PUZZLES_PATH, iter_ndjson
from .metrics import DERIVED, game_metrics, load_analyses, puzzle_metrics, to_date
from .mistakes import MISTAKES_PATH
from .state import iso_week
from .taxonomy import load_taxonomy

DIAGNOSIS_PATH = DERIVED / "diagnosis.json"

OTB_WINDOW_DAYS = 365
PUZZLE_WINDOW_DAYS = 365
MIN_OTB_GAMES = 5
MIN_PUZZLES_THEME = 10  # below this a theme is ignored; below 30 it is low confidence
MIN_SCORE = 0.15
LEGACY_PERFS = {"correspondence"}
TAG_WEIGHT = {"tactics.other": 0.5}  # unspecific tag: weaker evidence
DESCRIPTIVE_TAGS = {"endgame.pawn", "endgame.rook", "endgame.minor-piece", "endgame.queen"}


@dataclass
class Signal:
    skill: str
    score: float
    n: int
    kind: str  # games | puzzles
    evidence: str


def clamp(x: float) -> float:
    return max(0.0, min(1.0, x))


def confidence(kind: str, n: int, legacy: bool) -> str:
    if kind == "puzzles":
        level = "low" if n < 30 else "medium" if n < 100 else "high"
    else:
        level = "low" if n < 5 else "medium" if n < 15 else "high"
    return "low" if legacy else level


# -- rules ----------------------------------------------------------------------


def puzzle_signals(pm: dict, theme_to_skill: dict[str, str]) -> list[Signal]:
    overall = pm["winRate"]["value"]
    if overall is None:
        return []
    out = []
    for theme, r in pm["themes"].items():
        skill = theme_to_skill.get(theme)
        if skill is None or r["n"] < MIN_PUZZLES_THEME:
            continue
        gap = overall - r["value"]
        score = clamp(gap / 0.25)
        if score > 0:
            out.append(
                Signal(
                    skill,
                    score,
                    r["n"],
                    "puzzles",
                    f"puzzle win rate {r['value']:.0%} on '{theme}' vs {overall:.0%} "
                    f"overall (n={r['n']})",
                )
            )
    return out


def tag_signals(mistakes: list[dict], n_games: int) -> list[Signal]:
    if not n_games:
        return []
    counts = Counter(t for m in mistakes for t in m["tags"] if t not in DESCRIPTIVE_TAGS)
    games_with = Counter()
    for t in counts:
        games_with[t] = len({m["gameId"] for m in mistakes if t in m["tags"]})
    out = []
    for tag, k in counts.items():
        # share of games affected, not raw count: one bad game must not dominate
        score = clamp(games_with[tag] / n_games) * TAG_WEIGHT.get(tag, 1.0)
        out.append(
            Signal(
                tag,
                score,
                n_games,
                "games",
                f"{k} critical positions tagged {tag} in {games_with[tag]} of {n_games} games",
            )
        )
    return out


def game_signals(gm: dict) -> list[Signal]:
    n = gm["n"]
    out = []
    conv = gm["conversionRate"]
    if conv["n"] >= 3:
        out.append(
            Signal(
                "middlegame.conversion",
                clamp(1 - conv["value"]),
                conv["n"],
                "games",
                f"converted {conv['k']} of {conv['n']} games with a winning position (≥75%)",
            )
        )
    tp = gm["timePressureErrorShare"]
    if tp["n"] >= 5:
        out.append(
            Signal(
                "middlegame.time-management",
                clamp(tp["value"] / 0.5),
                tp["n"],
                "games",
                f"{tp['value']:.0%} of mistakes/blunders under time pressure (n={tp['n']})",
            )
        )
    clock30 = gm["clockShareAtMove"]["30"]
    if clock30["n"] >= 5 and clock30["value"] is not None:
        out.append(
            Signal(
                "middlegame.time-management",
                clamp((0.4 - clock30["value"]) / 0.3),
                clock30["n"],
                "games",
                f"avg clock left at move 30: {clock30['value']:.0%} (n={clock30['n']})",
            )
        )
    if n:
        opening_rate = gm["errorsByPhase"]["opening"] / n
        out.append(
            Signal(
                "opening.early-deviations",
                clamp(opening_rate / 2),
                n,
                "games",
                f"{opening_rate:.1f} mistakes+blunders per game in the opening phase (n={n})",
            )
        )
        missed = gm["missedWins"]["value"]
        if missed:
            out.append(
                Signal(
                    "calculation.candidate-moves",
                    clamp(missed / n),
                    n,
                    "games",
                    f"{missed} missed wins (opponent's error not punished) in {n} games",
                )
            )
    return out


# -- orchestration ----------------------------------------------------------------


def combine(signals: list[Signal], legacy: bool) -> list[dict]:
    by_skill: dict[str, list[Signal]] = {}
    for s in signals:
        if s.score > 0:
            by_skill.setdefault(s.skill, []).append(s)
    taxonomy = load_taxonomy()
    out = []
    for skill, sigs in by_skill.items():
        if skill not in taxonomy:
            raise ValueError(f"diagnosis produced unknown skill {skill}")
        rest = 1.0
        for s in sigs:
            rest *= 1 - s.score
        score = round(1 - rest, 3)
        if score < MIN_SCORE:
            continue
        strongest = max(sigs, key=lambda s: s.score)
        out.append(
            {
                "skill": skill,
                "score": score,
                "confidence": confidence(strongest.kind, strongest.n, legacy),
                "evidence": [s.evidence for s in sorted(sigs, key=lambda s: -s.score)],
                "url": taxonomy[skill].url,
            }
        )
    return sorted(out, key=lambda w: (-w["score"], w["skill"]))


def build(
    cfg: Config, today: date, analyses: list[dict], puzzles: list[dict], mistakes: list[dict]
) -> dict:
    since = today - timedelta(days=OTB_WINDOW_DAYS)
    otb = [
        a for a in analyses if a["perf"] not in LEGACY_PERFS and to_date(a["createdAt"]) >= since
    ]
    if len(otb) >= MIN_OTB_GAMES:
        games, legacy = otb, False
        basis = f"non-correspondence games of the last {OTB_WINDOW_DAYS} days"
    else:
        games, legacy = analyses, any(a["perf"] in LEGACY_PERFS for a in analyses)
        basis = (
            f"all analysed games (fewer than {MIN_OTB_GAMES} recent non-correspondence games); "
            "includes legacy correspondence games, so confidence is capped at low"
            if legacy
            else "all analysed games"
        )
    ids = {a["gameId"] for a in games}
    game_mistakes = [m for m in mistakes if m["gameId"] in ids]

    p_since = today - timedelta(days=PUZZLE_WINDOW_DAYS)
    recent_puzzles = [p for p in puzzles if to_date(p["date"]) >= p_since]
    puzzle_set = recent_puzzles if len(recent_puzzles) >= 30 else puzzles
    pm = puzzle_metrics(puzzle_set)
    theme_to_skill = {s.lichess_theme: key for key, s in load_taxonomy().items() if s.lichess_theme}

    gm = game_metrics(games)
    signals = (
        tag_signals(game_mistakes, len(games))
        + game_signals(gm)
        + puzzle_signals(pm, theme_to_skill)
    )
    return {
        "week": iso_week(today),
        "asOf": today.isoformat(),
        "basis": {
            "games": basis,
            "perfs": sorted({a["perf"] for a in games}),
            "puzzles": "last 365 days" if puzzle_set is recent_puzzles else "all time",
        },
        "sampleSize": {
            "games": len(games),
            "criticalPositions": len(game_mistakes),
            "puzzles": pm["n"],
        },
        "weaknesses": combine(signals, legacy),
    }


def run(cfg: Config, today: date | None = None) -> dict:
    today = today or datetime.now(UTC).date()
    diagnosis = build(
        cfg,
        today,
        load_analyses(),
        list(iter_ndjson(PUZZLES_PATH)),
        list(iter_ndjson(MISTAKES_PATH)),
    )
    DIAGNOSIS_PATH.parent.mkdir(parents=True, exist_ok=True)
    DIAGNOSIS_PATH.write_text(
        json.dumps(diagnosis, indent=1, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return diagnosis
