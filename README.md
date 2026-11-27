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
uv run python -m pipeline all             # sync + analyze + mistakes + metrics
uv run pytest && uv run ruff check .
```

## Status

| Milestone | State |
|---|---|
| M0 Repo skeleton | done |
| M1 Sync | done |
| M2 Analysis + mistakes | done |
| M3 Metrics + diagnosis | done ([baseline report](journal/baseline.md)) |
| M4 Automation | next |

Known limitation: the game cursor is the newest `createdAt`. A long correspondence game created
before the cursor but finished after it would be missed. Bullet/blitz/rapid/classical are unaffected.
