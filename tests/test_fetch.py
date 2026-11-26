import json

import httpx
import pytest

from pipeline import fetch
from pipeline.config import Config
from pipeline.lichess_client import LichessClient, LichessError, RateLimited
from pipeline.state import State

CFG = Config.model_validate({"lichess": {"username": "tester"}})


def ndjson(objs):
    return "".join(json.dumps(o) + "\n" for o in objs)


def make_client(handler, token="lip_x"):
    sleeps: list[float] = []
    client = LichessClient(token, transport=httpx.MockTransport(handler), sleep=sleeps.append)
    return client, sleeps


# -- client ------------------------------------------------------------------


def test_429_backoff_then_success():
    calls = {"n": 0}

    def handler(req):
        calls["n"] += 1
        if calls["n"] < 3:
            return httpx.Response(429)
        return httpx.Response(200, json={"ok": True})

    client, sleeps = make_client(handler)
    assert client.get_json("/x") == {"ok": True}
    assert sleeps == [60.0, 60.0]


def test_429_gives_up():
    client, sleeps = make_client(lambda req: httpx.Response(429))
    with pytest.raises(RateLimited):
        client.get_json("/x")
    assert len(sleeps) == 3


def test_http_error_and_headers():
    seen = {}

    def handler(req):
        seen.update(req.headers)
        return httpx.Response(404, text="nope")

    client, _ = make_client(handler)
    with pytest.raises(LichessError, match="404"):
        client.get_json("/x")
    assert seen["authorization"] == "Bearer lip_x"
    assert seen["user-agent"].startswith("chess-coach/")


# -- games -------------------------------------------------------------------


GAMES = [{"id": f"g{i}", "createdAt": 1000 + i, "moves": "e4 e5"} for i in range(4)]


def test_sync_games_full_then_incremental(tmp_path):
    path = tmp_path / "games.ndjson"
    seen_params = []

    def handler(req):
        seen_params.append(dict(req.url.params))
        since = int(req.url.params.get("since", 0))
        return httpx.Response(200, text=ndjson(g for g in GAMES if g["createdAt"] >= since))

    client, _ = make_client(handler)
    state = State()
    assert fetch.sync_games(client, CFG, state, path).added == 4
    assert state.games.lastCreatedAt == 1003 and state.games.count == 4
    assert seen_params[0]["sort"] == "dateAsc" and "since" not in seen_params[0]
    assert seen_params[0]["clocks"] == "true"

    assert fetch.sync_games(client, CFG, state, path).added == 0
    assert seen_params[1]["since"] == "1004"
    ids = [json.loads(line)["id"] for line in path.read_text().splitlines()]
    assert ids == ["g0", "g1", "g2", "g3"]


def test_sync_games_dedupes_after_interrupted_run(tmp_path):
    path = tmp_path / "games.ndjson"
    path.write_text(ndjson(GAMES[:2]))  # written, but state was never saved
    client, _ = make_client(lambda req: httpx.Response(200, text=ndjson(GAMES)))
    res = fetch.sync_games(client, CFG, State(), path)
    assert res.added == 2
    assert len(path.read_text().splitlines()) == 4


# -- puzzles -----------------------------------------------------------------


def puzzle(i):
    return {"date": 5000 + i, "win": i % 2 == 0, "puzzle": {"id": f"p{i}", "themes": ["fork"]}}


def test_sync_puzzles_paginates_backwards_and_is_incremental(tmp_path):
    path = tmp_path / "puzzles.ndjson"
    remote = [puzzle(i) for i in range(7)]
    requests = []

    def handler(req):
        p = req.url.params
        requests.append(dict(p))
        rows = sorted(remote, key=lambda r: -r["date"])  # newest first, like Lichess
        if "before" in p:
            rows = [r for r in rows if r["date"] < int(p["before"])]
        if "since" in p:
            rows = [r for r in rows if r["date"] >= int(p["since"])]
        return httpx.Response(200, text=ndjson(rows[: int(p["max"])]))

    client, _ = make_client(handler)
    state = State()
    assert fetch.sync_puzzles(client, state, path, page=3).added == 7
    dates = [json.loads(line)["date"] for line in path.read_text().splitlines()]
    assert dates == sorted(dates) and len(dates) == 7
    assert state.puzzles.lastDate == 5006
    assert len(requests) == 3  # 3 + 3 + 1

    remote.append(puzzle(7))
    assert fetch.sync_puzzles(client, state, path, page=3).added == 1
    assert requests[-1]["since"] == "5007"
    assert len(path.read_text().splitlines()) == 8


def test_sync_puzzles_without_token(tmp_path):
    client, _ = make_client(lambda req: httpx.Response(500), token=None)
    res = fetch.sync_puzzles(client, State(), tmp_path / "p.ndjson")
    assert res.skipped


def test_sync_ratings(tmp_path):
    body = [{"name": "Classical", "points": [[2026, 10, 1, 1650], [2026, 10, 8, 1672]]}]
    client, _ = make_client(lambda req: httpx.Response(200, json=body))
    state = State()
    assert fetch.sync_ratings(client, CFG, state, tmp_path / "r.json").added == 2
    assert json.loads((tmp_path / "r.json").read_text()) == body
    assert state.ratingsFetchedAt
