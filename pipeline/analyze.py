"""Own Stockfish analysis of every eligible game, cached per game (DESIGN.md §7.2).

Engine output (one `PositionEval` per position) is the expensive part and is cached in
`data/analysis/{gameId}.json` together with the engine signature. Everything derived from it
(win%, classes, phases, summary) is rebuilt cheaply on every run, so changing thresholds never
needs the engine. Files are only rewritten when their content actually changes.
"""

from __future__ import annotations

import json
import logging
import re
import shutil
import time
from collections import Counter
from collections.abc import Iterable
from pathlib import Path

import chess
import chess.engine

from .chessmath import classify, game_accuracy, in_time_pressure
from .config import Config, EngineCfg
from .fetch import GAMES_PATH, iter_ndjson
from .models import CrossCheck, EngineInfo, GameAnalysis, Ply, PositionEval, Summary
from .state import DATA

log = logging.getLogger(__name__)

ANALYSIS_DIR = DATA / "analysis"
PV_LEN = 8
OPENING_PLIES = 20  # fallback phase heuristic when Lichess gives no division
ENDGAME_MATERIAL = 26  # total non-pawn material (both sides, N/B=3 R=5 Q=9) at or below → endgame
MISSED_WIN = {"prev_below": 60.0, "gain": 20.0, "now_at_least": 65.0, "after_below": 60.0}

MATERIAL = {chess.PAWN: 1, chess.KNIGHT: 3, chess.BISHOP: 3, chess.ROOK: 5, chess.QUEEN: 9}


# -- game selection ------------------------------------------------------------


def player_color(game: dict, username: str) -> chess.Color | None:
    for name, color in (("white", chess.WHITE), ("black", chess.BLACK)):
        user = game["players"][name].get("user") or {}
        if user.get("id") == username.lower():
            return color
    return None


def eligible(game: dict, cfg: Config) -> bool:
    a = cfg.analysis
    return (
        game.get("variant") in ("standard", "fromPosition")
        and game.get("perf") in a.only_perfs
        and len(game.get("moves", "").split()) >= a.min_plies
        and (a.since is None or game["createdAt"] >= a.since)
        and player_color(game, cfg.lichess.username) is not None
    )


def replay(game: dict) -> tuple[chess.Board, list[chess.Move]]:
    """Return the starting board and the move list."""
    start = chess.Board(game.get("initialFen") or chess.STARTING_FEN)
    board = start.copy()
    moves = []
    for san in game["moves"].split():
        move = board.parse_san(san)
        moves.append(move)
        board.push(move)
    return start, moves


# -- engine --------------------------------------------------------------------


class Engine:
    def __init__(self, cfg: EngineCfg) -> None:
        path = shutil.which(cfg.binary) or cfg.binary
        self._engine = chess.engine.SimpleEngine.popen_uci(path)
        self._engine.configure({"Threads": cfg.threads, "Hash": cfg.hash_mb})
        name = self._engine.id.get("name", "unknown")
        m = re.match(r"(\S+)\s+(\S+)", name)
        detected = m.group(2) if m else name
        if cfg.version != "auto" and cfg.version != detected:
            self._engine.quit()
            raise RuntimeError(f"config pins engine version {cfg.version}, binary is {name}")
        self.info = EngineInfo(
            name=m.group(1) if m else name, version=detected, nodes=cfg.nodes_per_position
        )

    def close(self) -> None:
        self._engine.quit()

    def __enter__(self) -> Engine:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def evaluate(self, board: chess.Board, game_key: object) -> PositionEval:
        terminal = terminal_eval(board)
        if terminal:
            return terminal
        info = self._engine.analyse(board, chess.engine.Limit(nodes=self.info.nodes), game=game_key)
        score = info["score"].white()
        pv = [m.uci() for m in info.get("pv", [])[:PV_LEN]]
        return PositionEval(
            cp=score.score(),
            mate=score.mate(),
            best=pv[0] if pv else None,
            pv=pv,
        )


def terminal_eval(board: chess.Board) -> PositionEval | None:
    if board.is_checkmate():
        return PositionEval(terminal="black_won" if board.turn == chess.WHITE else "white_won")
    if board.is_stalemate() or board.is_insufficient_material() or board.is_seventyfive_moves():
        return PositionEval(terminal="draw")
    if board.is_fivefold_repetition():
        return PositionEval(terminal="draw")
    return None


def evaluate_game(engine: Engine, game: dict) -> list[PositionEval]:
    start, moves = replay(game)
    board = start.copy()
    key = game["id"]
    evals = [engine.evaluate(board, key)]
    for move in moves:
        board.push(move)
        evals.append(engine.evaluate(board, key))
    return evals


# -- derived analysis (pure) ---------------------------------------------------


def _phase(ply: int, board_after: chess.Board, division: dict | None) -> str:
    if division and ("middle" in division or "end" in division):
        if division.get("end") and ply >= division["end"]:
            return "endgame"
        if division.get("middle") and ply >= division["middle"]:
            return "middlegame"
        return "opening"
    non_pawn = sum(
        MATERIAL[p.piece_type]
        for p in board_after.piece_map().values()
        if p.piece_type not in (chess.PAWN, chess.KING)
    )
    if non_pawn <= ENDGAME_MATERIAL:
        return "endgame"
    return "opening" if ply <= OPENING_PLIES else "middlegame"


def _pov(white_value: float, color: chess.Color) -> float:
    return white_value if color == chess.WHITE else 100.0 - white_value


def _pov_int(v: int | None, color: chess.Color) -> int | None:
    return None if v is None else (v if color == chess.WHITE else -v)


def _result(game: dict, color: chess.Color) -> str:
    winner = game.get("winner")
    if winner is None:
        return "draw"
    return "win" if (winner == "white") == (color == chess.WHITE) else "loss"


def _san_line(board: chess.Board, ucis: Iterable[str]) -> list[str]:
    b = board.copy()
    out = []
    for u in ucis:
        try:
            move = chess.Move.from_uci(u)
            if move not in b.legal_moves:
                break
            out.append(b.san(move))
            b.push(move)
        except ValueError:
            break
    return out


def build_analysis(
    game: dict, evals: list[PositionEval], engine: EngineInfo, cfg: Config
) -> GameAnalysis:
    color = player_color(game, cfg.lichess.username)
    if color is None:
        raise ValueError(f"{game['id']}: {cfg.lichess.username} did not play this game")
    start, moves = replay(game)
    if len(evals) != len(moves) + 1:
        raise ValueError(f"{game['id']}: {len(evals)} evals for {len(moves)} moves")
    clock = game.get("clock") or {}
    clock_initial = clock.get("initial")
    clocks = game.get("clocks") or []
    division = game.get("division") or None
    thresholds = tuple(cfg.analysis.thresholds)

    plies: list[Ply] = []
    board = start.copy()
    for i, move in enumerate(moves):
        mover = board.turn
        before, after = evals[i], evals[i + 1]
        san = board.san(move)
        best_line = _san_line(board, [before.best]) if before.best else []
        best_san = best_line[0] if best_line else None
        win_before = _pov(before.win_white(), mover)
        win_after = _pov(after.win_white(), mover)
        drop = round(win_before - win_after, 2)
        clock_left = clocks[i] / 100 if i < len(clocks) else None
        by_player = mover == color
        board_before = board.copy(stack=False)
        board.push(move)
        cls = classify(drop, thresholds)
        p = Ply(
            ply=i + 1,
            san=san,
            uci=move.uci(),
            byPlayer=by_player,
            cpBefore=_pov_int(before.cp, mover),
            cpAfter=_pov_int(after.cp, mover),
            mateBefore=_pov_int(before.mate, mover),
            mateAfter=_pov_int(after.mate, mover),
            winBefore=round(win_before, 2),
            winAfter=round(win_after, 2),
            winDrop=drop,
            bestSan=best_san,
            bestUci=before.best,
            cls=cls,
            clockLeft=clock_left,
            phase=_phase(i + 1, board, division),
            timePressure=in_time_pressure(
                clock_left, clock_initial, cfg.analysis.time_pressure_fraction
            ),
        )
        if by_player and i >= 1:
            prev = _pov(evals[i - 1].win_white(), mover)
            mw = MISSED_WIN
            p.missedWin = (
                prev < mw["prev_below"]
                and win_before >= prev + mw["gain"]
                and win_before >= mw["now_at_least"]
                and win_after < mw["after_below"]
            )
        if by_player and (cls != "good" or p.missedWin):
            p.pvSan = _san_line(board_before, before.pv)
        plies.append(p)

    mine = [p for p in plies if p.byPlayer]
    cp_losses = [
        max(0, _pov_cp(evals[i], color) - _pov_cp(evals[i + 1], color))
        for i, p in enumerate(plies)
        if p.byPlayer
    ]
    player_wins = [_pov(e.win_white(), color) for e in evals[1:]]
    counts = Counter(p.cls for p in mine)
    summary = Summary(
        acpl=round(sum(cp_losses) / len(cp_losses)) if cp_losses else 0,
        inaccuracies=counts["inaccuracy"],
        mistakes=counts["mistake"],
        blunders=counts["blunder"],
        accuracy=_round(
            game_accuracy(
                [e.win_white() for e in evals],
                color == chess.WHITE,
                white_moves_first=start.turn == chess.WHITE,
            )
        ),
        result=_result(game, color),
        maxAdvantageWin=round(max(player_wins), 2),
        minWin=round(min(player_wins), 2),
        missedWins=sum(p.missedWin for p in mine),
    )
    return GameAnalysis(
        gameId=game["id"],
        engine=engine,
        params={
            "thresholds": list(thresholds),
            "timePressureFraction": cfg.analysis.time_pressure_fraction,
        },
        playerColor="white" if color == chess.WHITE else "black",
        perf=game["perf"],
        createdAt=game["createdAt"],
        clockInitial=clock_initial,
        clockIncrement=clock.get("increment"),
        opening=game.get("opening"),
        division=division,
        initialFen=game.get("initialFen"),
        positions=evals,
        plies=plies,
        summary=summary,
        crossCheck=cross_check(game, evals, plies, thresholds),
    )


def _pov_cp(e: PositionEval, color: chess.Color) -> int:
    v = e.cp_white_clamped()
    return v if color == chess.WHITE else -v


def _round(x: float | None) -> float | None:
    return None if x is None else round(x, 1)


# -- Lichess cross-check --------------------------------------------------------

LICHESS_CLASS = {"Inaccuracy": "inaccuracy", "Mistake": "mistake", "Blunder": "blunder"}


def cross_check(
    game: dict, evals: list[PositionEval], plies: list[Ply], thresholds
) -> CrossCheck | None:
    """Compare with Lichess server analysis when it exists (`analysis[i]` = after ply i+1)."""
    server = game.get("analysis")
    if not server:
        return None
    diffs, agree, n = [], 0, 0
    ours: Counter = Counter()
    theirs: Counter = Counter()
    for i, p in enumerate(plies):
        if i >= len(server):
            break
        s = server[i]
        if "eval" not in s and "mate" not in s:
            continue
        if s.get("mate") == 0:
            # Lichess scores a checkmated position as "mate 0", which doesn't say who is mated.
            # Our eval for it comes from the board (terminal), so use that; skip if they disagree.
            if evals[i + 1].terminal is None:
                continue
            lichess_win = evals[i + 1].win_white()
        else:
            lichess_win = PositionEval(cp=s.get("eval"), mate=s.get("mate")).win_white()
        diffs.append(abs(evals[i + 1].win_white() - lichess_win))
        if p.byPlayer:
            n += 1
            their = LICHESS_CLASS.get((s.get("judgment") or {}).get("name"), "good")
            ours[p.cls] += 1
            theirs[their] += 1
            agree += their == p.cls
    if not diffs:
        return None
    return CrossCheck(
        plies=n,
        evalMaeWin=round(sum(diffs) / len(diffs), 2),
        classAgreement=round(agree / n, 3) if n else 0.0,
        ours={k: ours[k] for k in ("inaccuracy", "mistake", "blunder")},
        lichess={k: theirs[k] for k in ("inaccuracy", "mistake", "blunder")},
    )


# -- cache + orchestration --------------------------------------------------------


def analysis_path(game_id: str, directory: Path = ANALYSIS_DIR) -> Path:
    return directory / f"{game_id}.json"


def load_cached(game_id: str, directory: Path = ANALYSIS_DIR) -> dict | None:
    path = analysis_path(game_id, directory)
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def write_if_changed(path: Path, analysis: GameAnalysis) -> bool:
    text = json.dumps(analysis.model_dump(by_alias=True, exclude_none=False), indent=1) + "\n"
    if path.exists() and path.read_text(encoding="utf-8") == text:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)
    return True


def engine_signature_matches(cached: dict, current: EngineInfo) -> bool:
    """Cached evals are reusable only if made by the same engine version at the same nodes."""
    eng = cached.get("engine", {})
    return (
        eng.get("name") == current.name
        and eng.get("version") == current.version
        and eng.get("nodes") == current.nodes
    )


def run(
    cfg: Config,
    *,
    game_ids: list[str] | None = None,
    force: bool = False,
    limit: int | None = None,
    games_path: Path = GAMES_PATH,
    directory: Path = ANALYSIS_DIR,
) -> dict[str, int]:
    games = [g for g in iter_ndjson(games_path) if eligible(g, cfg)]
    if game_ids:
        games = [g for g in games if g["id"] in set(game_ids)]
    stats = Counter()
    if not games:
        return {"eligible": 0}
    # Start the engine up front: its real version is the cache key, even when all is cached.
    engine = Engine(cfg.engine)
    try:
        for game in games:
            cached = load_cached(game["id"], directory)
            reuse = (
                cached is not None and not force and engine_signature_matches(cached, engine.info)
            )
            if reuse:
                evals = [PositionEval.model_validate(p) for p in cached["positions"]]
                info = EngineInfo.model_validate(cached["engine"])
                stats["cached"] += 1
            else:
                if limit is not None and stats["analysed"] >= limit:
                    stats["deferred"] += 1
                    continue
                t0 = time.monotonic()
                evals = evaluate_game(engine, game)
                info = engine.info
                stats["analysed"] += 1
                log.info(
                    "analysed %s (%d plies) in %.1fs",
                    game["id"],
                    len(evals) - 1,
                    time.monotonic() - t0,
                )
            analysis = build_analysis(game, evals, info, cfg)
            if write_if_changed(analysis_path(game["id"], directory), analysis):
                stats["written"] += 1
    finally:
        engine.close()
    stats["eligible"] = len(games)
    return dict(stats)


def compare_report(game_id: str, cfg: Config, games_path: Path = GAMES_PATH) -> str:
    """Human-readable side-by-side of our flags vs Lichess judgments for one game."""
    cached = load_cached(game_id)
    if not cached:
        return f"{game_id}: not analysed yet"
    game = next((g for g in iter_ndjson(games_path) if g["id"] == game_id), None)
    server = (game or {}).get("analysis") or []
    lines = [
        f"{game_id} ({cached['perf']}, {cached['playerColor']}, {cached['summary']['result']})",
        f"{'ply':>4} {'move':<8} {'by':<3} {'ours':<11} {'drop':>6} {'lichess':<11} best",
    ]
    for p in cached["plies"]:
        s = server[p["ply"] - 1] if p["ply"] - 1 < len(server) else {}
        theirs = LICHESS_CLASS.get((s.get("judgment") or {}).get("name"), "-")
        ours = p["class"] if p["class"] != "good" else "-"
        if ours == "-" and theirs == "-":
            continue
        lines.append(
            f"{p['ply']:>4} {p['san']:<8} {'me' if p['byPlayer'] else 'op':<3} {ours:<11} "
            f"{p['winDrop']:>6.1f} {theirs:<11} {p['bestSan'] or ''}"
        )
    me = "white" if cached["playerColor"] == "white" else "black"
    lich = ((game or {}).get("players", {}).get(me, {}) or {}).get("analysis")
    s = cached["summary"]
    lines.append(
        f"ours:    inacc {s['inaccuracies']} mist {s['mistakes']} blund {s['blunders']} "
        f"acpl {s['acpl']} acc {s['accuracy']}"
    )
    if lich:
        lines.append(
            f"lichess: inacc {lich['inaccuracy']} mist {lich['mistake']} "
            f"blund {lich['blunder']} acpl {lich['acpl']} acc {lich.get('accuracy')}"
        )
    if cached.get("crossCheck"):
        cc = cached["crossCheck"]
        lines.append(
            f"class agreement {cc['classAgreement']:.0%} over {cc['plies']} moves, "
            f"eval MAE {cc['evalMaeWin']} win%"
        )
    return "\n".join(lines)
