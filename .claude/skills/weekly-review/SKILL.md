---
name: weekly-review
description: Run the Sunday coaching review for chess-coach — read the week's data, write journal/YYYY-Www.md and next week's plan/current.md in Russian, validate, commit and push to main. Use when asked for the weekly review, the weekly plan, or "/weekly-review".
---

# Weekly coaching review

You are the coach. Follow `CLAUDE.md` (coaching policy, method, coaching voice, language:
Russian for plan/journal).
The week being reviewed is the ISO week that ends today (Sunday); the plan is for the next one.

## 1. Fresh data

```bash
git switch main && git pull --ff-only
uv sync
uv run python -m pipeline metrics
uv run python -m pipeline diagnose
```

Don't commit anything under `data/` yourself; the bot owns it. If `metrics`/`diagnose` change
files, discard them with `git restore data/` before committing. Use them only for reading.

## 2. Read the inputs

- `data/derived/diagnosis.json`: ranked weaknesses, `basis`, sample sizes
- the last 4 files in `data/derived/weekly/`, plus `data/derived/metrics.json` (`games.<perf>.last4Weeks`,
  `puzzles.last4Weeks`, `weeklySeries`)
- `plan/current.md`: what was planned
- the newest file in `journal/`: last week's decisions and what was to be checked
- `data/reviews.jsonl` rows for this week: review study results from the check-in issue
- `data/mistakes.jsonl`: this week's new critical positions (by `gameCreatedAt`), for 2–3 concrete examples with links

## 3. Write `journal/YYYY-Www.md` (the week just ended, in Russian)

Sections:
1. **План vs факт:** games played vs planned, puzzles, review results. State adherence honestly.
2. **Что изменилось:** the leading indicators against last week and the 4-week window. Show `n`
   for every number, and don't draw conclusions below n = 5 games / 30 puzzles per theme.
3. **Примеры:** 2–3 critical moments from this week's games, with lichess links and the idea that was missed.
4. **Решение:** keep or switch focus, and why. A focus stays at least `focus_duration_weeks`
   unless a clearly bigger problem appears; if you switch, say what outweighed it.

## 4. Write the new plan

1. Move the old plan: `git mv plan/current.md plan/history/<its week>.md` (its `week:` field).
   If `plan/current.md` is already for next week (written early), don't archive it: revise it in place.
2. Write `plan/current.md` for next week in the format from `CLAUDE.md`:
   - `week`: next ISO week; `focus`: 1–2 taxonomy keys
   - `daily` items each with `minutes` and an `https://` `url`, totalling ≤ the daily budget in `config.yaml`
   - include the review study (`lichess.review_study_id` → `https://lichess.org/study/<id>`)
   - `weekly`: rapid 15+10 games (`count`, plus one concrete `rule`), and the weekend block
   - `minimum_day`
   - below the front matter: «Почему именно это на этой неделе» in a few sentences
   If adherence was low, reduce the load instead of piling on.
3. Validate: `uv run python -m pipeline plan-check`. It must print `plan: ok`.

## 5. Commit and push

```bash
git add journal/ plan/
git commit -m "coach: weekly review <week>"
git push origin main
```

Pushing `plan/` or `journal/` to `main` redeploys the dashboard.

## 6. Report

Reply with a short summary in Russian: the decision, the two focus areas, and the dashboard link.
