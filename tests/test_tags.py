import chess
import pytest

from pipeline.tags import (
    Moment,
    captures_hanging,
    endgame_type,
    ends_in_back_rank_mate,
    is_fork,
    tag_moment,
)
from pipeline.taxonomy import load_taxonomy

FORK = "r3k3/8/8/3N4/8/8/8/4K3 w - - 0 1"  # Nc7+ forks king and rook
HANGING = "4k3/8/8/3n4/8/8/8/3RK3 w - - 0 1"  # Rxd5 wins an undefended knight
DEFENDED = "4k3/8/4p3/3n4/8/8/8/3RK3 w - - 0 1"
BACK_RANK = "6k1/5ppp/8/8/8/8/8/R5K1 w - - 0 1"  # Ra8#


def mv(u):
    return chess.Move.from_uci(u)


def test_fork():
    assert is_fork(chess.Board(FORK), mv("d5c7"))
    assert not is_fork(chess.Board(FORK), mv("d5f6"))  # only checks the king
    # forking square covered by an enemy bishop, knight undefended → not a fork
    assert not is_fork(chess.Board("r2bk3/8/8/3N4/8/8/8/4K3 w - - 0 1"), mv("d5c7"))


def test_hanging():
    assert captures_hanging(chess.Board(HANGING), mv("d1d5"))
    assert not captures_hanging(chess.Board(DEFENDED), mv("d1d5"))
    assert not captures_hanging(chess.Board(HANGING), mv("d1d2"))  # not a capture


def test_back_rank():
    assert ends_in_back_rank_mate(chess.Board(BACK_RANK), ["a1a8"])
    assert not ends_in_back_rank_mate(chess.Board(BACK_RANK), ["a1a7"])


def test_endgame_type():
    assert endgame_type(chess.Board("4k3/p7/8/8/8/8/P7/4K3 w - - 0 1")) == "endgame.pawn"
    assert endgame_type(chess.Board("r3k3/p7/8/8/8/8/P7/R3K3 w - - 0 1")) == "endgame.rook"
    assert endgame_type(chess.Board("4k3/p3n3/8/8/8/8/P7/2B1K3 w - - 0 1")) == "endgame.minor-piece"
    assert endgame_type(chess.Board("r3k3/p3n3/8/8/8/8/P7/2B1K3 w - - 0 1")) is None


def test_mixed_endgame_in_won_game_is_not_technique():
    tags = tag_moment(
        moment(
            fen="r3k3/p3n3/8/8/8/8/P7/2B1K3 w - - 0 1",
            played="c1d2",
            best_pv=["c1b2"],
            win_before=90.0,
            result="win",
            phase="endgame",
        )
    )
    assert "endgame.technique" not in tags


def moment(**kw):
    base = dict(
        fen=FORK,
        played="e1d2",
        best_pv=["d5c7", "e8d7", "c7a8"],
        reply_pv=[],
        mate_before=None,
        mate_after=None,
        win_before=50.0,
        phase="middlegame",
        time_pressure=False,
        result="loss",
        move_class="mistake",
    )
    base.update(kw)
    return Moment(**base)


def test_tag_missed_fork_and_defence():
    tags = tag_moment(moment(win_before=35.0))
    assert "tactics.fork" in tags and "middlegame.defence" in tags


def test_tag_missed_back_rank_mate():
    tags = tag_moment(
        moment(
            fen=BACK_RANK,
            played="g1f1",
            best_pv=["a1a8"],
            mate_before=1,
            mate_after=None,
            win_before=100.0,
            result="draw",
            phase="endgame",
        )
    )
    assert {"tactics.mateIn1", "tactics.backRankMate", "endgame.technique"} <= set(tags)
    assert "endgame.rook" in tags


def test_tag_time_pressure_and_fallback():
    assert tag_moment(moment(fen=DEFENDED, played="e1e2", best_pv=["e1f2"])) == ["tactics.other"]
    tags = tag_moment(moment(fen=DEFENDED, played="e1e2", best_pv=["e1f2"], time_pressure=True))
    assert tags == ["middlegame.time-management"]


@pytest.mark.parametrize("fen", [FORK, HANGING, DEFENDED, BACK_RANK])
def test_all_emitted_tags_exist_in_taxonomy(fen):
    taxonomy = load_taxonomy()
    board = chess.Board(fen)
    for move in board.legal_moves:
        for kw in (
            dict(),
            dict(mate_before=2, mate_after=-1, win_before=90, phase="endgame", time_pressure=True),
        ):
            tags = tag_moment(
                moment(
                    fen=fen,
                    played=move.uci(),
                    best_pv=[m.uci() for m in list(board.legal_moves)[:1]],
                    **kw,
                )
            )
            assert set(tags) <= set(taxonomy)
