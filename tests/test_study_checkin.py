import json
from datetime import date

import chess
import httpx

from pipeline import checkin, publish_study
from pipeline.config import Config
from pipeline.lichess_client import LichessClient
from pipeline.models import Mistake
from pipeline.review import ReviewState
from pipeline.state import State

CFG = Config.model_validate({"lichess": {"username": "me", "review_study_id": "STUDY001"}})
TODAY = date(2026, 11, 27)
FEN_W = "1k1r1b1r/ppp4p/4Bqpn/6N1/nP1p1B2/5Q2/P1b2PPP/4RK1R w - - 1 19"
FEN_B = "r1bqkbnr/pppp1ppp/2n5/4p2Q/2B1P3/8/PPPP1PPP/RNB1K1NR b KQkq - 3 3"


def mistake(mid, fen, color, played, pv, drop=30.0, due=TODAY, box=0):
    return Mistake(
        id=mid,
        gameId=mid.split("-")[0],
        perf="rapid",
        ply=int(mid.split("-")[1]),
        url=f"https://lichess.org/{mid.split('-')[0]}/{color}#1",
        fen=fen,
        playerColor=color,
        played=played,
        best=pv[0],
        pv=pv,
        cls="blunder",
        winBefore=80.0,
        winDrop=drop,
        phase="middlegame",
        timePressure=False,
        missedWin=False,
        tags=["tactics.other"],
        gameCreatedAt=1,
        createdAt=1,
        review=ReviewState(box=box, due=due),
    )


M1 = mistake("abcdefgh-37", FEN_W, "white", "g3", ["Bxc7+", "Kxc7", "Qxf6"], drop=80)
M2 = mistake("ijklmnop-6", FEN_B, "black", "Nf6", ["g6", "Qf3"], drop=60)
M3 = mistake("qrstuvwx-9", FEN_B, "black", "Nf6", ["g6"], due=date(2026, 12, 20))


def write_mistakes(path, *ms):
    path.write_text(
        "".join(json.dumps(m.model_dump(mode="json", by_alias=True)) + "\n" for m in ms)
    )


def test_select_week_horizon_and_order():
    sel = publish_study.select_week({m.id: m for m in (M1, M2, M3)}, CFG, TODAY)
    assert [m.id for m in sel] == ["abcdefgh-37", "ijklmnop-6"]


def test_chapter_pgn_is_gamebook_with_played_side_line():
    pgn = publish_study.chapter_pgn(M1)
    game = publish_study._pgn_games(pgn)[0]
    assert game.headers["FEN"] == FEN_W and game.headers["SetUp"] == "1"
    first = game.variations[0]
    assert first.san() == "Bxc7+" and first.comment == "Верно!"
    side = game.variations[1]
    assert side.san() == "g3" and "−80%" in side.comment
    assert [n.san() for n in game.mainline()] == ["Bxc7+", "Kxc7", "Qxf6"]
    assert publish_study.chapter_name(M1) == "Ход 19, белые (зевок) · abcdefgh"
    assert publish_study.move_label(M2) == "3..."


class FakeLichess:
    def __init__(self, existing):
        self.chapters = list(existing)
        self.calls = []

    def __call__(self, req: httpx.Request):
        self.calls.append((req.method, req.url.path))
        if req.method == "GET":
            body = "\n\n".join(
                f'[ChapterURL "https://lichess.org/study/STUDY001/{c}"]\n\n*' for c in self.chapters
            )
            return httpx.Response(200, text=body)
        if req.method == "DELETE":
            self.chapters.remove(req.url.path.rsplit("/", 1)[1])
            return httpx.Response(204)
        form = dict(httpx.QueryParams(req.content.decode()))
        assert form["mode"] == "gamebook" and form["orientation"] in ("white", "black")
        assert len(self.chapters) < 64
        new = f"ch{len(self.calls):06d}"
        self.chapters.append(new)
        return httpx.Response(200, json={"chapters": [{"id": new, "name": form["name"]}]})


def test_publish_rebuilds_then_noops_then_increments(tmp_path):
    path = tmp_path / "mistakes.jsonl"
    write_mistakes(path, M1, M2, M3)
    fake = FakeLichess(["old00001", "old00002"])
    client = LichessClient("t", transport=httpx.MockTransport(fake), sleep=lambda s: None)
    state = State()
    res = publish_study.publish(client, CFG, state, TODAY, mistakes_path=path)
    assert res["changed"] and res["added"] == 2 and res["deleted"] == 2
    assert list(state.study.chapters) == ["abcdefgh-37", "ijklmnop-6"]
    assert sorted(fake.chapters) == sorted(state.study.chapters.values())
    # the last old chapter is deleted only after the new ones exist
    assert [m for m, _ in fake.calls] == ["GET", "DELETE", "POST", "POST", "DELETE"]

    n = len(fake.calls)
    assert publish_study.publish(client, CFG, state, TODAY, mistakes_path=path)["changed"] is False
    assert len(fake.calls) == n

    # M1 solved (no longer due), M3 becomes due: only those two change, M2 keeps its chapter
    kept = state.study.chapters["ijklmnop-6"]
    m1 = M1.model_copy(update={"review": ReviewState(box=1, due=date(2026, 12, 30))})
    m3 = M3.model_copy(update={"review": ReviewState(due=TODAY)})
    write_mistakes(path, m1, M2, m3)
    res = publish_study.publish(client, CFG, state, TODAY, mistakes_path=path)
    assert res["added"] == 1 and res["deleted"] == 1
    assert state.study.chapters["ijklmnop-6"] == kept
    assert set(state.study.chapters) == {"ijklmnop-6", "qrstuvwx-9"}
    assert sorted(fake.chapters) == sorted(state.study.chapters.values())


def test_save_study_id(tmp_path):
    cfg = tmp_path / "config.yaml"
    cfg.write_text("lichess:\n  username: me\n  review_study_id: null       # TODO\n")
    publish_study.save_study_id("AbCd1234", cfg)
    assert "review_study_id: AbCd1234       # TODO" in cfg.read_text()


def test_checkin_render_parse_apply(tmp_path):
    path = tmp_path / "mistakes.jsonl"
    reviews = tmp_path / "reviews.jsonl"
    write_mistakes(path, M1, M2, M3)
    state = State()
    state.study.studyId = "STUDY001"
    state.study.chapters = {"abcdefgh-37": "ch1", "ijklmnop-6": "ch2", "qrstuvwx-9": "ch3"}
    body = checkin.render(CFG, state, TODAY, mistakes_path=path)
    assert "https://lichess.org/study/STUDY001/ch1" in body and "week=2026-W48" in body
    assert "ход 19 за белых" in body

    body = body.replace("- [ ] решил верно", "- [x] решил верно", 1)  # first: solved
    lines = body.splitlines()
    i = lines.index(next(line for line in lines if "`ijklmnop-6`" in line))
    lines[i + 2] = lines[i + 2].replace("[ ]", "[x]")  # second: missed; third: untouched
    body = "\n".join(lines)
    assert checkin.parse(body) == {
        "abcdefgh-37": "correct",
        "ijklmnop-6": "wrong",
        "qrstuvwx-9": "skipped",
    }

    res = checkin.apply(body, 7, CFG, TODAY, mistakes_path=path, reviews_path=reviews)
    assert res == {"recorded": 3, "correct": 1, "wrong": 1, "skipped": 1}
    rows = {json.loads(line)["id"]: json.loads(line) for line in path.read_text().splitlines()}
    assert rows["abcdefgh-37"]["review"]["box"] == 1
    assert rows["ijklmnop-6"]["review"]["box"] == 0
    assert rows["qrstuvwx-9"]["review"]["due"] == TODAY.isoformat()
    assert json.loads(reviews.read_text().splitlines()[0])["week"] == "2026-W48"
    # applying the same issue again changes nothing
    assert (
        checkin.apply(body, 7, CFG, TODAY, mistakes_path=path, reviews_path=reviews)["recorded"]
        == 0
    )


def test_board_side_matches_player_color():
    assert chess.Board(M1.fen).turn == chess.WHITE and chess.Board(M2.fen).turn == chess.BLACK
