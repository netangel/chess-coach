import json
from datetime import date

from pipeline import site
from pipeline.config import load_config
from pipeline.state import State

PLAN = """---
week: 2026-W49
focus: [calculation.candidate-moves]
daily:
  - {title: "Задачи", minutes: 10, url: "https://lichess.org/training/mix"}
minimum_day: "3 позиции"
---
Почему **так**.
"""


def test_front_matter_and_markdown():
    fm, body = site.split_front_matter(PLAN)
    assert fm["week"] == "2026-W49" and fm["daily"][0]["minutes"] == 10
    assert "<strong>так</strong>" in site.render_md(body)
    assert site.split_front_matter("no front matter") == ({}, "no front matter")


def test_latest_journal_prefers_weekly(tmp_path):
    assert site.latest_journal(tmp_path) is None
    (tmp_path / "baseline.md").write_text("# b")
    assert site.latest_journal(tmp_path).name == "baseline.md"
    (tmp_path / "2026-W49.md").write_text("# w")
    (tmp_path / "2026-W50.md").write_text("# w")
    assert site.latest_journal(tmp_path).name == "2026-W50.md"


def test_build_writes_static_site(tmp_path):
    out = site.build(load_config(), State(), date(2026, 11, 27), out=tmp_path / "dist")
    assert (out / "index.html").exists() and (out / "app.js").exists()
    data = json.loads((out / "dashboard.json").read_text())
    assert data["mainPerf"] == "rapid" and "activity" in data and "diagnosis" in data


def test_latest_game_with_moments(tmp_path, monkeypatch):
    from pipeline.fetch import GAMES_PATH, iter_ndjson
    from pipeline.mistakes import load_mistakes
    from pipeline.state import load_state

    games = list(iter_ndjson(GAMES_PATH))
    one = next(g for g in games if g["id"] == "dJkzTqwS")
    short = next(g for g in games if g["id"] == "lriJnjHt")
    path = tmp_path / "games.ndjson"
    path.write_text(json.dumps(one) + "\n")
    monkeypatch.setattr(site, "GAMES_PATH", path)
    state = load_state()
    g = site.latest_game(load_config(), state, load_mistakes())
    assert g["id"] == "dJkzTqwS" and g["analysed"] and g["result"] == "loss"
    assert g["moments"] and g["moments"] == sorted(
        g["moments"], key=lambda m: int(m["label"].split()[1].rstrip(","))
    )
    in_study = [m for m in g["moments"] if m["inStudy"]]
    assert all(m["url"].startswith("https://lichess.org/study/") for m in in_study)

    path.write_text(json.dumps(one) + "\n" + json.dumps(short) + "\n")
    g = site.latest_game(load_config(), state, load_mistakes())
    assert g["id"] == "lriJnjHt" and g["notAnalysed"] == "short" and g["moments"] == []
