from datetime import date

import pytest

from pipeline import diagnose, metrics
from pipeline.config import Config

CFG = Config.model_validate({"lichess": {"username": "me"}})
DAY = 86_400_000
TODAY = date(2026, 11, 27)
NOW_MS = 1_795_737_600_000  # 2026-11-27 UTC


def ply(n, by, cls="good", phase="middlegame", clock=None, tp=False):
    return {
        "ply": n,
        "byPlayer": by,
        "class": cls,
        "phase": phase,
        "clockLeft": clock,
        "timePressure": tp,
    }


def game(
    gid,
    *,
    perf="rapid",
    days_ago=1,
    result="loss",
    max_win=60.0,
    min_win=40.0,
    plies=None,
    clock=900,
    opening="Sicilian Defense: Najdorf",
    missed=0,
):
    return {
        "gameId": gid,
        "perf": perf,
        "playerColor": "white",
        "createdAt": NOW_MS - days_ago * DAY,
        "clockInitial": clock,
        "opening": {"name": opening},
        "plies": plies or [ply(1, True), ply(2, False)],
        "summary": {
            "acpl": 50,
            "accuracy": 80.0,
            "result": result,
            "maxAdvantageWin": max_win,
            "minWin": min_win,
            "missedWins": missed,
        },
    }


def test_game_metrics_counts_rates_and_clock():
    plies = [ply(i, i % 2 == 1, clock=900 - 10 * i) for i in range(1, 80)]
    plies[58] = ply(59, True, "blunder", "endgame", clock=60, tp=True)  # move 30 for White
    plies[10] = ply(11, True, "mistake", "opening", clock=800)
    gs = [
        game("a", plies=plies, result="loss", max_win=80),  # failed conversion
        game("b", result="win", max_win=90),
        game("c", result="draw", min_win=20),  # saved
    ]
    m = metrics.game_metrics(gs)
    assert m["n"] == 3 and m["results"] == {"win": 1, "draw": 1, "loss": 1}
    assert m["score"]["value"] == 0.5
    assert m["blundersPerGame"]["endgame"] == pytest.approx(0.33, abs=0.01)
    assert m["errorsByPhase"] == {"opening": 1, "middlegame": 0, "endgame": 1}
    assert m["timePressureErrorShare"] == {"value": 0.5, "k": 1, "n": 2}
    assert m["clockShareAtMove"]["30"] == {"value": round(60 / 900, 3), "n": 1}
    assert m["conversionRate"] == {"value": 0.5, "k": 1, "n": 2}
    assert m["saveRate"] == {"value": 1.0, "k": 1, "n": 1}
    assert m["byOpening"][0]["family"] == "Sicilian Defense" and m["byOpening"][0]["n"] == 3


def test_game_metrics_empty_and_no_clock():
    assert metrics.game_metrics([])["blundersPerGame"]["total"] is None
    m = metrics.game_metrics([game("x", clock=None)])
    assert m["timePressureErrorShare"]["n"] == 0 and m["clockShareAtMove"]["20"]["n"] == 0


def test_puzzle_metrics_and_ratings():
    ps = [
        {"date": 1, "win": i % 2 == 0, "puzzle": {"rating": 1500, "themes": ["fork"]}}
        for i in range(4)
    ]
    pm = metrics.puzzle_metrics(ps)
    assert pm["winRate"]["value"] == 0.5 and pm["themes"]["fork"]["n"] == 4
    series = metrics.rating_series(
        [{"name": "Puzzle", "points": [[2025, 0, 22, 1696]]}, {"name": "Rapid", "points": []}]
    )
    assert series == {"puzzle": [["2025-01-22", 1696]]}


def test_build_windows_and_weekly():
    analyses = [game("old", days_ago=400), game("new", days_ago=3)]
    m, weekly = metrics.build(CFG, TODAY, analyses, [], [], [], {"n": 0})
    assert m["games"]["rapid"]["last4Weeks"]["n"] == 1
    assert m["games"]["rapid"]["allTime"]["n"] == 2
    assert len(weekly) == 2 and all(w["games"]["rapid"]["n"] == 1 for w in weekly.values())


def test_diagnosis_falls_back_to_legacy_and_caps_confidence():
    analyses = [game(f"g{i}", perf="correspondence", result="loss", max_win=90) for i in range(6)]
    mistakes = [{"gameId": f"g{i}", "tags": ["middlegame.conversion"]} for i in range(3)]
    d = diagnose.build(CFG, TODAY, analyses, [], mistakes)
    assert "legacy" in d["basis"]["games"]
    top = d["weaknesses"][0]
    assert top["skill"] == "middlegame.conversion"
    assert top["score"] == pytest.approx(1.0)  # 0 of 6 converted, noisy-OR with the tag share
    assert all(w["confidence"] == "low" for w in d["weaknesses"])


def test_diagnosis_prefers_recent_otb_and_uses_puzzle_gaps():
    analyses = [game(f"r{i}", perf="rapid") for i in range(5)]
    analyses.append(game("c0", perf="correspondence", result="loss", max_win=95))
    puzzles = [
        {"date": NOW_MS, "win": True, "puzzle": {"themes": ["mateIn2"]}} for _ in range(40)
    ] + [{"date": NOW_MS, "win": i < 3, "puzzle": {"themes": ["fork"]}} for i in range(12)]
    d = diagnose.build(CFG, TODAY, analyses, puzzles, [])
    assert d["basis"]["perfs"] == ["rapid"] and d["sampleSize"]["games"] == 5
    fork = next(w for w in d["weaknesses"] if w["skill"] == "tactics.fork")
    assert fork["confidence"] == "low"  # n=12 < 30
    assert fork["url"] == "https://lichess.org/training/fork"
    assert not any(w["skill"] == "tactics.mateIn2" for w in d["weaknesses"])


def test_signals_ignore_small_puzzle_themes_and_combine():
    pm = {"winRate": {"value": 0.8}, "themes": {"fork": {"value": 0.2, "k": 1, "n": 5}}}
    assert diagnose.puzzle_signals(pm, {"fork": "tactics.fork"}) == []
    sigs = [
        diagnose.Signal("tactics.fork", 0.5, 10, "games", "a"),
        diagnose.Signal("tactics.fork", 0.5, 40, "puzzles", "b"),
    ]
    (w,) = diagnose.combine(sigs, legacy=False)
    assert w["score"] == 0.75 and w["confidence"] == "medium"
