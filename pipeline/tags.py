"""Heuristic motif tags for critical moments (DESIGN.md §7.2).

Precision over recall: a tag is emitted only when a simple, checkable pattern holds. Tags are
hints for the diagnosis, never ground truth. Every tag is a taxonomy key.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import chess

VALUE = {chess.PAWN: 1, chess.KNIGHT: 3, chess.BISHOP: 3, chess.ROOK: 5, chess.QUEEN: 9}


def value(piece: chess.Piece) -> int:
    return 100 if piece.piece_type == chess.KING else VALUE[piece.piece_type]


@dataclass
class Moment:
    fen: str  # position before the player's move
    played: str  # UCI
    best_pv: list[str]  # UCI, engine best line from `fen`
    reply_pv: list[str]  # UCI, engine best line after the played move (opponent to move)
    mate_before: int | None  # mover POV: >0 player could mate in n
    mate_after: int | None  # mover POV: <0 opponent can mate in n
    win_before: float
    phase: str
    time_pressure: bool
    result: str  # player's game result: win | loss | draw
    move_class: str
    extra: list[str] = field(default_factory=list)


# -- primitives ----------------------------------------------------------------


def captures_hanging(board: chess.Board, move: chess.Move) -> bool:
    """Move captures an undefended piece worth ≥ 3."""
    if not board.is_capture(move) or board.is_en_passant(move):
        return False
    victim = board.piece_at(move.to_square)
    if victim is None or victim.piece_type in (chess.PAWN, chess.KING):
        return False
    return not board.attackers(victim.color, move.to_square)


def is_fork(board: chess.Board, move: chess.Move) -> bool:
    """After `move`, the moved piece safely attacks ≥ 2 valuable enemy pieces."""
    if move not in board.legal_moves:
        return False
    after = board.copy(stack=False)
    after.push(move)
    piece = after.piece_at(move.to_square)
    if piece is None:
        return False
    me, opp = piece.color, not piece.color
    v = value(piece)
    attackers = after.attackers(opp, move.to_square)
    if attackers:
        cheapest = min(value(after.piece_at(sq)) for sq in attackers)
        if cheapest < v or not after.attackers(me, move.to_square):
            return False
    targets = 0
    for sq in after.attacks(move.to_square):
        target = after.piece_at(sq)
        if target is None or target.color != opp or target.piece_type == chess.PAWN:
            continue
        if target.piece_type == chess.KING or value(target) > v or not after.attackers(opp, sq):
            targets += 1
    return targets >= 2


def ends_in_back_rank_mate(board: chess.Board, pv: list[str]) -> bool:
    b = board.copy(stack=False)
    for u in pv:
        move = chess.Move.from_uci(u)
        if move not in b.legal_moves:
            return False
        b.push(move)
        if b.is_checkmate():
            king_sq = b.king(b.turn)
            back = 0 if b.turn == chess.WHITE else 7
            if king_sq is None or chess.square_rank(king_sq) != back:
                return False
            return any(
                b.piece_at(sq).piece_type in (chess.ROOK, chess.QUEEN)
                and chess.square_rank(sq) == back
                for sq in b.checkers()
            )
    return False


def endgame_type(board: chess.Board) -> str:
    kinds = {
        p.piece_type
        for p in board.piece_map().values()
        if p.piece_type not in (chess.KING, chess.PAWN)
    }
    if not kinds:
        return "endgame.pawn"
    if kinds == {chess.ROOK}:
        return "endgame.rook"
    if kinds <= {chess.KNIGHT, chess.BISHOP}:
        return "endgame.minor-piece"
    if kinds == {chess.QUEEN}:
        return "endgame.queen"
    return "endgame.technique"


# -- tagging -------------------------------------------------------------------


def tag_moment(m: Moment) -> list[str]:
    board = chess.Board(m.fen)
    played = chess.Move.from_uci(m.played)
    after = board.copy(stack=False)
    after.push(played)
    best = chess.Move.from_uci(m.best_pv[0]) if m.best_pv else None
    reply = chess.Move.from_uci(m.reply_pv[0]) if m.reply_pv else None
    tags: set[str] = set()

    # missed mate
    if m.mate_before is not None and 0 < m.mate_before <= 3:
        still_mating = m.mate_after is not None and 0 < m.mate_after < m.mate_before
        if not still_mating:
            tags.add(f"tactics.mateIn{m.mate_before}")
            if ends_in_back_rank_mate(board, m.best_pv):
                tags.add("tactics.backRankMate")
    # allowed a quick mate
    if m.mate_after is not None and -3 <= m.mate_after < 0:
        tags.add(f"tactics.mateIn{-m.mate_after}")
        if ends_in_back_rank_mate(after, m.reply_pv):
            tags.add("tactics.backRankMate")

    if best and best != played:
        # "missed a free piece" only if the played move didn't capture on that square anyway
        if captures_hanging(board, best) and best.to_square != played.to_square:
            tags.add("tactics.hangingPiece")
        if is_fork(board, best):
            tags.add("tactics.fork")
    if reply:
        if captures_hanging(after, reply):
            tags.add("tactics.hangingPiece")
        if is_fork(after, reply):
            tags.add("tactics.fork")

    serious = m.move_class in ("mistake", "blunder")
    if m.win_before >= 75 and m.result != "win":
        tags.add("endgame.technique" if m.phase == "endgame" else "middlegame.conversion")
    if m.win_before <= 40 and m.result == "loss" and serious:
        tags.add("middlegame.defence")
    if m.time_pressure:
        tags.add("middlegame.time-management")
    if m.phase == "endgame":
        tags.add(endgame_type(board))

    if not tags:
        tags.add("tactics.other")
    tags.update(m.extra)
    return sorted(tags)
