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
