from pipeline.config import Config
from pipeline.plan import check

CFG = Config.model_validate({"lichess": {"username": "me"}})

GOOD = """---
week: 2026-W49
focus: [calculation.candidate-moves, middlegame.conversion]
daily:
  - {title: "Задачи", minutes: 10, url: "https://lichess.org/training/mix"}
  - {title: "Разбор", minutes: 7, url: "https://lichess.org/study/abc"}
weekly:
  - {title: "Рапид 15+10", count: 3, rule: "проверка хода"}
minimum_day: "3 позиции"
---
Почему так.
"""


def test_good_plan():
    assert check(GOOD, CFG) == []


def test_bad_plan_reports_each_problem():
    bad = (
        GOOD.replace("week: 2026-W49", "week: next")
        .replace("middlegame.conversion", "middlegame.converting, tactics.fork")
        .replace("minutes: 10", "minutes: 20")
        .replace('"https://lichess.org/training/mix"', '"http://x"')
        .replace("Почему так.", "")
    )
    problems = check(bad, CFG)
    assert any("url" in p for p in problems)  # schema error stops further checks
    fixed_url = bad.replace('"http://x"', '"https://x"')
    problems = check(fixed_url, CFG)
    assert any("ISO week" in p for p in problems)
    assert any("1–2 skills" in p for p in problems)
    assert any("middlegame.converting" in p for p in problems)
    assert any("budget is 20" in p for p in problems)
    assert any("explanation" in p for p in problems)


def test_missing_front_matter():
    assert check("just text", CFG) == ["missing YAML front matter"]
