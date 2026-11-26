import json
import shutil

import chess
import pytest

from pipeline import analyze, mistakes
from pipeline.config import Config
from pipeline.models import EngineInfo, PositionEval

CFG = Config.model_validate(
    {
        "lichess": {"username": "Me"},
        "analysis": {"only_perfs": ["rapid"], "min_plies": 4},
    }
)
ENGINE = EngineInfo(name="Stockfish", version="test", nodes=1)

# Scholar's mate: Black ("me") blunders with 3...Nf6?? and gets mated.
GAME = {
    "id": "scholar1",
    "variant": "standard",
    "perf": "rapid",
    "createdAt": 1700000000000,
    "status": "mate",
    "winner": "white",
    "moves": "e4 e5 Bc4 Nc6 Qh5 Nf6 Qxf7#",
    "clock": {"initial": 900, "increment": 10, "totalTime": 1300},
    # centiseconds left after each ply; Black's 3...Nf6 is played with 60 s (< 10% of 900)
    "clocks": [90000, 90000, 89000, 88000, 87000, 6000, 86000],
    "players": {"white": {"aiLevel": 3}, "black": {"user": {"id": "me", "name": "Me"}}},
}
# White-POV evals for positions 0..6 (position 7 is checkmate, scored without engine)
EVALS = [
    PositionEval(cp=20, best="e2e4", pv=["e2e4"]),
    PositionEval(cp=25, best="e7e5", pv=["e7e5"]),
    PositionEval(cp=20, best="g1f3", pv=["g1f3"]),
    PositionEval(cp=30, best="g8f6", pv=["g8f6"]),
    PositionEval(cp=-20, best="g1f3", pv=["g1f3"]),
    PositionEval(cp=-10, best="g7g6", pv=["g7g6", "h5f3"]),
    PositionEval(mate=1, best="h5f7", pv=["h5f7"]),
]


def build():
    board = chess.Board()
    for san in GAME["moves"].split():
        board.push_san(san)
    return analyze.build_analysis(GAME, [*EVALS, analyze.terminal_eval(board)], ENGINE, CFG)


def test_player_color_and_eligibility():
    assert analyze.player_color(GAME, "me") == chess.BLACK
    assert analyze.player_color(GAME, "someone") is None
    assert analyze.eligible(GAME, CFG)
    assert not analyze.eligible({**GAME, "perf": "blitz"}, CFG)
    assert not analyze.eligible({**GAME, "moves": "e4 e5"}, CFG)


def test_terminal_evals():
    mated = chess.Board("6k1/5ppp/8/8/8/8/8/R5K1 w - - 0 1")
    mated.push_san("Ra8#")
    assert analyze.terminal_eval(mated).win_white() == 100.0
    assert analyze.terminal_eval(chess.Board("7k/5Q2/6K1/8/8/8/8/8 b - - 0 1")).terminal == "draw"
    assert analyze.terminal_eval(chess.Board()) is None


def test_build_analysis_classes_clock_and_summary():
    a = build()
    assert a.playerColor == "black" and a.summary.result == "loss"
    nf6 = a.plies[5]
    assert nf6.san == "Nf6" and nf6.byPlayer
    assert nf6.cls == "blunder" and nf6.winDrop > 40
    assert nf6.bestSan == "g6" and nf6.pvSan == ["g6", "Qf3"]
    assert nf6.mateAfter == -1  # mover POV: opponent mates in 1
    assert nf6.clockLeft == 60.0 and nf6.timePressure
    assert not a.plies[3].timePressure
    assert a.plies[6].winAfter == 100.0  # White's mating move scored without the engine
    assert a.summary.blunders == 1 and a.summary.minWin == 0.0
    assert a.summary.accuracy < 70
    assert a.crossCheck is None


def test_no_clock_is_never_time_pressure():
    game = {**GAME, "clock": None, "clocks": None}
    board = chess.Board()
    for san in GAME["moves"].split():
        board.push_san(san)
    a = analyze.build_analysis(game, [*EVALS, analyze.terminal_eval(board)], ENGINE, CFG)
    assert all(p.clockLeft is None and not p.timePressure for p in a.plies)


def test_write_if_changed_is_idempotent(tmp_path):
    path = tmp_path / "scholar1.json"
    assert analyze.write_if_changed(path, build())
    assert not analyze.write_if_changed(path, build())


def test_mistakes_extraction_keeps_review_state(tmp_path):
    games = tmp_path / "games.ndjson"
    games.write_text(json.dumps(GAME) + "\n")
    adir = tmp_path / "analysis"
    analyze.write_if_changed(adir / "scholar1.json", build())
    out = tmp_path / "mistakes.jsonl"

    first = mistakes.run(CFG, games_path=games, analysis_dir=adir, path=out)
    assert first == {"positions": 1, "new": 1, "written": 1}
    row = json.loads(out.read_text())
    assert row["id"] == "scholar1-6" and row["played"] == "Nf6" and row["best"] == "g6"
    assert "tactics.mateIn1" in row["tags"] and "middlegame.time-management" in row["tags"]
    assert row["url"] == "https://lichess.org/scholar1/black#6"
    assert row["review"]["box"] == 0

    row["review"].update(box=2, attempts=2, lastResult="correct")
    out.write_text(json.dumps(row) + "\n")
    second = mistakes.run(CFG, games_path=games, analysis_dir=adir, path=out)
    assert second["new"] == 0
    assert json.loads(out.read_text())["review"]["box"] == 2
    assert mistakes.run(CFG, games_path=games, analysis_dir=adir, path=out)["written"] == 0


@pytest.mark.skipif(shutil.which("stockfish") is None, reason="stockfish not installed")
def test_engine_finds_scholar_blunder(tmp_path):
    games = tmp_path / "games.ndjson"
    games.write_text(json.dumps(GAME) + "\n")
    cfg = CFG.model_copy(deep=True)
    cfg.engine.nodes_per_position = 20000
    cfg.engine.threads = 1
    stats = analyze.run(cfg, games_path=games, directory=tmp_path)
    assert stats["analysed"] == 1
    a = json.loads((tmp_path / "scholar1.json").read_text())
    assert a["plies"][5]["class"] == "blunder"
    assert analyze.run(cfg, games_path=games, directory=tmp_path)["cached"] == 1

    # a cache made by another engine version must be re-analysed, never mixed in
    path = tmp_path / "scholar1.json"
    stale = json.loads(path.read_text())
    stale["engine"]["version"] = "old"
    path.write_text(json.dumps(stale))
    assert analyze.run(cfg, games_path=games, directory=tmp_path)["analysed"] == 1
    assert json.loads(path.read_text())["engine"]["version"] != "old"
