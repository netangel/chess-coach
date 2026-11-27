# chess-coach

A personal, data-driven chess coach built on the Lichess API. It syncs your games and puzzles,
analyses them with Stockfish, diagnoses weaknesses, and has Claude write a weekly plan.
See [DESIGN.md](DESIGN.md) for the design and [CLAUDE.md](CLAUDE.md) for the coaching rules.

## Setup

```bash
uv sync
```

Create a Lichess personal access token at https://lichess.org/account/oauth/token with scopes
`puzzle:read`, `study:read`, `study:write`. Put it in a `.env` file (gitignored):

```
LICHESS_TOKEN=lip_xxxxxxxx
```

Games and ratings sync without a token; puzzle activity and the puzzle dashboard need it.

Stockfish is needed from milestone M2 on: `brew install stockfish` (macOS).

## Usage

```bash
uv run python -m pipeline sync            # games + puzzles + ratings, incremental
uv run python -m pipeline sync --only games
uv run python -m pipeline snapshot        # weekly puzzle/storm dashboard snapshot
uv run python -m pipeline analyze         # Stockfish analysis of new games (cached per game)
uv run python -m pipeline mistakes        # critical positions -> data/mistakes.jsonl
uv run python -m pipeline compare <gameId>  # our move labels vs Lichess server analysis
uv run python -m pipeline metrics         # weekly + rolling aggregates -> data/derived/
uv run python -m pipeline diagnose        # ranked weaknesses -> data/derived/diagnosis.json
uv run python -m pipeline study --dry-run # print review-study PGN; without the flag: publish
uv run python -m pipeline checkin render  # weekly check-in issue body
uv run python -m pipeline plan-check      # validate plan/current.md against the coaching rules
uv run python -m pipeline all             # sync + analyze + mistakes + metrics + study
uv run pytest && uv run ruff check .
```

## Automation (GitHub Actions)

- `nightly.yml` (~03:17 UTC): sync → analyze → mistakes → metrics, then commits `data/` to `main`.
- `weekly.yml` (Sunday ~16:07 UTC): the same plus Storm/puzzle snapshot and diagnosis.
- Both use the official Stockfish 19 binary (SHA-256 pinned, cached) and the `LICHESS_TOKEN`
  repo secret, share the `pipeline` concurrency group, and can be started by hand from the
  Actions tab ("Run workflow"; untick *push* for a dry run that only logs the commit).
- `weekly.yml` also opens a **check-in issue** listing the week's review positions. Tick
  «решил верно» or «ошибся» per position and close the issue: `checkin.yml` records the
  results (Leitner boxes) and updates the study. Untouched positions come back again.
- `pages.yml` builds the dashboard (`site/` + `dashboard.json`) and deploys it to GitHub Pages
  after every data run, and when `site/`, `plan/` or `journal/` change on `main`.
  **One-time setup:** repo Settings → Pages → Source: *GitHub Actions*.
  Local preview: `uv run python -m pipeline site && python3 -m http.server -d dist 8765`.
- After the bot is live, only Actions commits `data/`.

## Weekly coaching (Claude)

On Sundays, after `weekly.yml`, run the review in Claude Code from this repo:

```
/weekly-review
```

The skill (`.claude/skills/weekly-review/SKILL.md`) reads the week's data, writes
`journal/YYYY-Www.md` and the next `plan/current.md` (Russian), validates them with
`plan-check`, and pushes to `main`, which redeploys the dashboard.

## Status

| Milestone | State |
|---|---|
| M0 Repo skeleton | done |
| M1 Sync | done |
| M2 Analysis + mistakes | done |
| M3 Metrics + diagnosis | done ([baseline report](journal/baseline.md)) |
| M4 Automation | done (runs once merged to `main`) |
| M5 Review study | done ([study](https://lichess.org/study/ubCwtsu5), weekly check-in issue) |
| M6 Dashboard | done (needs Pages enabled, see above) |
| M7 Coaching loop | first plan written; weekly `/weekly-review` skill (scheduling: see below) |

Known limitation: the game cursor is the newest `createdAt`. A long correspondence game created
before the cursor but finished after it would be missed. Bullet/blitz/rapid/classical are unaffected.
