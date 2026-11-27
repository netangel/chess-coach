# chess-coach — Design Document

Status: Draft v0.1 (2026-11-26) · Scope: Stage 1 (tracking + coaching loop). Stage 2 (book library) is only a hook here.

---

## 1. Purpose

A personal, data-driven chess coaching system, built with Claude, replacing a paid coaching app (Aimchess).

- **Lichess is the only place where training happens** (play, puzzles, studies, practice).
- **This repo is the coach's brain**: it syncs data from the Lichess API, analyses games with a local engine, diagnoses weaknesses, keeps state in plain files, writes a weekly plan, and publishes a dashboard.
- **Claude acts as the coach**: reads the derived data, writes weekly reviews and plans following the rules in `CLAUDE.md`.

### Goals
1. Automatic, incremental sync of games, puzzles, ratings and Storm results.
2. Own engine analysis of every new game (Lichess server analysis cannot be requested via API).
3. Weakness diagnosis based on leading indicators, not rating alone.
4. Personal mistake positions fed back into Lichess as a Study, with spaced repetition.
5. A weekly plan sized to a realistic time budget (default 15–20 min/day + 2–3 rapid games/week).
6. A dashboard that shows *today's assignment* (with direct Lichess links) and trends.
7. A shared skill taxonomy, so Stage 2 can map book chapters to diagnosed weaknesses.

### Non-goals (Stage 1)
- No backend server or database; files in git are the state.
- No custom puzzle UI or board; solving happens on Lichess.
- No opening repertoire trainer (light opening checks only).
- No multi-user support.

---

## 2. Constraints and facts about the Lichess API

| Topic | Fact | Design consequence |
|---|---|---|
| Server analysis | No endpoint to *request* Lichess computer analysis; `evals` are returned only if analysis already exists | Run Stockfish ourselves in the pipeline |
| Rate limiting | One request at a time; on HTTP 429 wait a full 60 s | Sequential client with a global lock + 429 back-off |
| Auth | Personal access token (Bearer), ~1 year lifetime, no refresh tokens | Token stored as GitHub secret `LICHESS_TOKEN`; expiry reminder in dashboard |
| Game export | Streamed ndjson; filters `since`, `until`, `max`, `perfType`, `rated`, `analysed`; options `clocks`, `evals`, `accuracy`, `opening`, `division` | Incremental sync by `since` = last seen `createdAt`/`lastMoveAt` |
| Puzzles | Activity (ndjson, `max`, `before`) and dashboard (`days`) need `puzzle:read` | Sync activity incrementally; snapshot dashboard weekly (30 days) |
| Studies | Import PGN into an existing study (multi-game PGN → multiple chapters), max 64 chapters/study; delete chapter supported | One study per review cycle, rebuilt by the pipeline; study is created once manually and its ID is configured |
| Explorer / tablebase / cloud eval | Separate hosts (`explorer.lichess.ovh`, `tablebase.lichess.ovh`), cloud-eval endpoint | Optional enrichment; not on the critical path |

Endpoints to use (verify paths against https://lichess.org/api during implementation):

```
GET  /api/games/user/{username}?since=&perfType=&clocks=true&evals=true&opening=true&accuracy=true   (Accept: application/x-ndjson)
GET  /api/user/{username}/rating-history
GET  /api/user/{username}/perf/{perf}
GET  /api/puzzle/activity?max=&before=           (puzzle:read)
GET  /api/puzzle/dashboard/{days}                (puzzle:read)
GET  /api/storm/dashboard/{username}?days=
POST /api/study/{studyId}/import-pgn             (study:write)  form: name, pgn, orientation
DELETE /api/study/{studyId}/{chapterId}          (study:write)
GET  /api/study/{studyId}.pgn                    (study:read)   to list chapter IDs
```

Token scopes: `puzzle:read`, `study:read`, `study:write`. Nothing else.

---

## 3. Architecture

```
                 ┌─────────────────────── GitHub Actions (nightly + weekly) ───────────────────────┐
 Lichess API ──► │ fetch ──► analyze (Stockfish) ──► extract mistakes ──► metrics ──► diagnose     │
                 │                                         │                              │        │
                 │                               publish_study ──► Lichess Study          ▼        │
                 │                                                               build site ──► GitHub Pages
                 └──────────────────────────────── commits data/ back to repo ──────────────────────┘
                                                        │
                       Claude (weekly scheduled session / ad-hoc in Code mode)
                       reads data/derived + diagnosis.json ──► writes journal/ + plan/current.md
```

### Runtime choice
GitHub Actions: open internet access, free minutes for public repos, Stockfish installable, commits state and deploys Pages. (Alternative later: the self-hosted home server via a Docker cron container — the pipeline must therefore be runnable locally with a single command, independent of Actions.)

### Tech stack
- **Pipeline:** Python 3.12, `uv` for dependency management, `python-chess` (PGN/engine handling), `httpx` (streaming HTTP), `pydantic` (schemas), `pytest`.
  Python is chosen over Java/TS because `python-chess` is the most complete chess library available.
- **Engine:** Stockfish (official Linux binary, pinned version, cached in Actions).
- **Dashboard:** static site, TypeScript compiled with `esbuild` (or plain ES modules for v1), a small chart lib (uPlot or Chart.js). Reads JSON from `data/derived/`.
- **Coach:** Claude, governed by `CLAUDE.md`.

---

## 4. Repository layout

```
chess-coach/
├── DESIGN.md                    this document
├── CLAUDE.md                    coaching rules + repo conventions for Claude
├── README.md
├── config.yaml                  user settings (see §5)
├── pyproject.toml / uv.lock
├── pipeline/
│   ├── __main__.py              `python -m pipeline sync|analyze|metrics|diagnose|study|all`
│   ├── lichess_client.py        sequential client, 429 back-off, ndjson streaming
│   ├── fetch.py                 incremental sync of all sources
│   ├── analyze.py               Stockfish analysis per game (cached)
│   ├── mistakes.py              critical-moment extraction + tagging
│   ├── review.py                spaced-repetition scheduler
│   ├── metrics.py               aggregates (weekly + rolling)
│   ├── diagnose.py              rule-based weakness scoring
│   ├── publish_study.py         due positions → Lichess Study
│   ├── taxonomy.py              loads taxonomy.yaml
│   └── models.py                pydantic schemas
├── taxonomy.yaml                shared skill taxonomy (§9)
├── data/
│   ├── state.json               sync cursors, versions, token expiry
│   ├── raw/
│   │   ├── games.ndjson         append-only, as returned by Lichess
│   │   ├── puzzles.ndjson       append-only puzzle activity
│   │   ├── ratings.json         latest rating-history snapshot
│   │   └── snapshots/           weekly puzzle-dashboard + storm snapshots (YYYY-Www.json)
│   ├── analysis/{gameId}.json   per-game engine analysis (cache; never recomputed unless engine config changes)
│   ├── mistakes.jsonl           one critical position per line, with review state
│   ├── reviews.jsonl            review results (from check-ins, §7.3)
│   └── derived/
│       ├── metrics.json         dashboard input
│       ├── weekly/YYYY-Www.json weekly aggregates
│       └── diagnosis.json       ranked weaknesses with evidence
├── plan/
│   ├── current.md               this week's prescription (Claude-written)
│   └── history/YYYY-Www.md
├── journal/YYYY-Www.md          weekly review: findings, decisions, rationale
├── site/                        dashboard source
├── tests/                       unit tests with fixture games
└── .github/workflows/
    ├── nightly.yml              sync → analyze → mistakes → metrics → study → site
    └── weekly.yml               snapshots + diagnose + open weekly check-in issue
```

Conventions: all timestamps UTC ms (as Lichess); ISO week IDs (`2026-W48`); raw data is append-only and never edited by hand; everything under `derived/` is reproducible from `raw/` + `analysis/`.

---

## 5. Configuration (`config.yaml`)

```yaml
lichess:
  username: TODO            # open question
  review_study_id: TODO     # created manually once on Lichess (private study)
training:
  main_perf: rapid          # rapid | classical | blitz
  tracked_perfs: [rapid, classical, blitz]
  budget:
    daily_minutes: 20
    games_per_week: 3
    weekend_block_minutes: 30
  focus_duration_weeks: 2   # min weeks before a focus area is re-evaluated
engine:
  binary: stockfish
  version: "17"             # pinned; changing it invalidates analysis cache
  nodes_per_position: 1000000
  threads: 2
  hash_mb: 256
analysis:
  only_perfs: [rapid, classical]   # blitz/bullet: synced, but analysed only on demand
  time_pressure_fraction: 0.10     # remaining clock < 10% of initial time
review:
  boxes_days: [1, 3, 7, 14, 30]    # Leitner intervals
  max_due_per_day: 5
  max_chapters: 60                 # below Lichess 64 limit
dashboard:
  public: true                     # open question (public repo vs private artifact)
```

---

## 6. Data model (key schemas)

### 6.1 Game analysis — `data/analysis/{gameId}.json`
```json
{
  "gameId": "abcd1234",
  "engine": {"name": "Stockfish", "version": "17", "nodes": 1000000},
  "playerColor": "white",
  "perf": "rapid",
  "clockInitial": 900, "clockIncrement": 10,
  "opening": {"eco": "C65", "name": "Ruy Lopez: Berlin Defense"},
  "division": {"middle": 22, "end": 61},
  "plies": [
    {"ply": 23, "san": "Nxe5", "byPlayer": true,
     "cpBefore": 35, "cpAfter": -240, "mateBefore": null, "mateAfter": null,
     "winBefore": 53.2, "winAfter": 28.1, "winDrop": 25.1,
     "bestSan": "d4", "class": "mistake",
     "clockLeft": 412, "phase": "middlegame", "timePressure": false}
  ],
  "summary": {"acpl": 41, "inaccuracies": 3, "mistakes": 2, "blunders": 1,
              "accuracy": 82.4, "result": "loss", "maxAdvantageWin": 71.0}
}
```

### 6.2 Mistake / review position — `data/mistakes.jsonl`
```json
{"id": "abcd1234-23", "gameId": "abcd1234", "ply": 23,
 "fen": "…", "playerColor": "white", "played": "Nxe5", "best": "d4", "pv": ["d4","exd4","Nxd4"],
 "class": "mistake", "winDrop": 25.1, "phase": "middlegame", "timePressure": false,
 "tags": ["tactics.hangingPiece"], "createdAt": 1764163200000,
 "review": {"box": 0, "due": "2026-11-27", "attempts": 0, "lastResult": null, "chapterId": null}}
```

### 6.3 Diagnosis — `data/derived/diagnosis.json`
```json
{"week": "2026-W48", "sampleSize": {"games": 11, "puzzles": 140},
 "weaknesses": [
   {"skill": "middlegame.time-management", "score": 0.78, "confidence": "medium",
    "evidence": ["45% of blunders under time pressure", "avg clock at move 30: 18%"]},
   {"skill": "tactics.fork", "score": 0.64, "confidence": "high",
    "evidence": ["puzzle win rate 52% vs 68% overall (n=41)"]}
 ]}
```

---

## 7. Pipeline

### 7.1 Sync (`fetch.py`)
- Games: `since = state.games.lastCreatedAt + 1`, ndjson stream, all perfs, `clocks/evals/opening/accuracy/division=true`; dedupe by `id`; append.
- Puzzles: page backwards with `before` until reaching the last stored puzzle; append in chronological order.
- Ratings: full rating-history snapshot (small) overwritten.
- Weekly only: puzzle dashboard (`days=30`) and storm dashboard → `raw/snapshots/YYYY-Www.json`.
- Client: single in-flight request, User-Agent `chess-coach/<version> (+repo URL)`, on 429 sleep 60 s and retry (max 3), streaming parse to keep memory flat.

### 7.2 Analysis (`analyze.py`, `mistakes.py`)
- For each new game in `analysis.only_perfs` without a cache file (or with stale engine version): evaluate every position at fixed `nodes` (deterministic-ish, comparable across runs). Reuse Lichess `evals` when present? No — always own engine, for consistent metrics; Lichess evals kept only as a cross-check.
- **Win% conversion** (Lichess formula): `win = 50 + 50 * (2 / (1 + exp(-0.00368208 * cp)) - 1)`; mate scores map to ±100 (or clamp cp to ±1000).
- **Move classes** by win% drop for the mover: inaccuracy ≥ 5, mistake ≥ 10, blunder ≥ 15 (configurable). *Changed 2026-11-26 from 10/20/30:* 5/10/15 is Lichess's own cut (0.1/0.2/0.3 on the ±1 winning-chances scale) and reproduced 97% of Lichess judgments on our games vs 81%.
- **Accuracy** per move: Lichess-style `103.1668 * exp(-0.04354 * winDrop) - 3.1669` (+1, clamped 0–100); game accuracy = Lichess method: average of the volatility-weighted mean (sliding-window std-dev of win%) and the harmonic mean of move accuracies. Lands within ~0–9 points of Lichess on our games.
- **Phase**: Lichess `division` when present; fallback heuristic on non-pawn material.
- **Time pressure**: `clockLeft < time_pressure_fraction * clockInitial`.
- **Critical moments**: player's moves classed mistake/blunder, plus *missed wins* (the opponent's last move raised the player's win% by ≥ 20 to ≥ 65 from < 60, and the player's reply dropped it back below 60) → `mistakes.jsonl` (FEN before the move, best line). Skipped when already lost (win before ≤ 15) or still clearly winning (win after ≥ 80).
- **Tagging (heuristic, v1)**: derive simple motifs from the best line with python-chess: hanging piece (moved/left piece capturable for free), fork (best move attacks ≥ 2 higher-value pieces), missed mate (mate in ≤ 3 available), back-rank, conversion failure (win ≥ 75 → result not a win), defence failure. Unknown → `tactics.other`. Precision over recall; tags are hints for diagnosis, not ground truth.

### 7.3 Spaced repetition (`review.py`, `publish_study.py`)
- Leitner boxes with intervals from config; new positions enter box 0 (due tomorrow).
- Nightly: select due positions (≤ `max_due_per_day` × days until next run, ordered by `winDrop`), rebuild the review study: delete old chapters, import due positions as PGN chapters (`[FEN]`/`[SetUp]` headers, orientation = player colour, comment with game link and "find the best move"; solution as a variation hidden behind a comment or as a gamebook-style move).
- *As built:* the study holds positions due within the next 7 days (≤ `max_due_per_day` × 7), one chapter per position in **gamebook** mode (find the engine's best move; the game move is a commented side line), imported one call per chapter so name and orientation are exact. Updates are incremental (kept positions keep their chapter ID, so links in the open check-in issue stay valid). The study is created by `study --init` (private; `shareable` must not be `nobody`, or even the owner cannot export it, and export is how chapter IDs are listed).
- **Result feedback** (Lichess does not expose study practice results):
  v1 = weekly check-in **GitHub Issue** opened by `weekly.yml`, listing the week's positions as checkboxes ("solved" ticked = correct). On issue close, a workflow parses it into `reviews.jsonl`; correct → box+1, wrong → box 0. Unanswered = treated as not attempted (stay in box, re-due).
  Alternative to evaluate: reporting results in a Claude session, which writes `reviews.jsonl`.

### 7.4 Metrics (`metrics.py`)
Weekly and rolling-4-week aggregates per perf:
- **Leading**: blunders/game and mistakes/game per phase; % of errors under time pressure; avg clock at move 20/30/40; conversion rate (games with max win ≥ 75 that were won); save rate (games with min win ≤ 25 not lost); missed-win count; puzzle win rate per theme (from activity and dashboard); puzzle rating; Storm best/avg; review-position success rate.
- **Lagging**: rating (main perf), score by opening (ECO family, per colour, min n=3).
- Each metric stores `n` so the coach and dashboard can show confidence.

### 7.5 Diagnosis (`diagnose.py`)
Rule-based, transparent scoring per taxonomy skill, combining normalized signals (e.g. theme win rate gap vs overall, share of errors in a phase vs expected, time-pressure share). Output ranked list with `score`, `confidence` (by sample size) and human-readable `evidence`. The diagnosis proposes; Claude decides the plan.

Implemented rules (v1, each → score in [0,1], combined per skill by noisy-OR `1 − Π(1 − s)`):
- puzzle theme gap: `(overall − theme win rate) / 0.25`, themes with n ≥ 10 only (low confidence below 30);
- mistake tags: share of games with ≥ 1 critical position carrying the tag (`tactics.other` × 0.5; endgame-type tags are descriptive only);
- conversion: `1 − conversion rate` (n ≥ 3 winning positions); time pressure: error share / 0.5 (n ≥ 5), clock at move 30;
- opening-phase errors per game / 2; missed wins per game → `calculation.candidate-moves`.
- Basis: non-correspondence games of the last 365 days if ≥ 5, else all analysed games; legacy correspondence games cap confidence at low.

---

## 8. Coaching loop (Claude)

### 8.1 Weekly review (Sunday evening; scheduled task or manual)
Inputs: `diagnosis.json`, `weekly/*.json` (last 4), `plan/current.md`, last journal, `reviews.jsonl`.
Outputs:
1. `journal/YYYY-Www.md` — what was done vs planned (adherence), what changed in metrics, interpretation, decision (keep/switch focus) with rationale.
2. `plan/current.md` — next week's prescription; previous one moved to `plan/history/`.

### 8.2 Rules for `CLAUDE.md` (coaching policy)
- Max **2 focus areas** at a time; keep a focus ≥ `focus_duration_weeks` unless a clearly bigger issue appears.
- Respect the time budget; always include a "minimum viable day" (e.g. one Storm run or 3 review positions).
- Prefer leading indicators over rating; never judge on n < 5 games or < 30 puzzles per theme.
- Default weekly template:
  - daily ~10 min themed puzzles (weakest theme, via `https://lichess.org/training/{theme}`),
  - daily ~5–10 min review study,
  - 2–3 rapid/classical games, each reviewed next day (3 critical moments from the pipeline),
  - weekend endgame block (Lichess Practice / later: book chapter).
- Every plan item has a direct link and an estimated duration.
- Be honest about adherence; adjust load down rather than piling on.

### 8.3 Plan format (`plan/current.md`)
Front matter (machine-readable, rendered by dashboard) + prose:
```markdown
---
week: 2026-W49
focus: [tactics.fork, middlegame.time-management]
daily:
  - {title: "Fork puzzles", minutes: 10, url: "https://lichess.org/training/fork"}
  - {title: "Review study", minutes: 7, url: "https://lichess.org/study/<id>"}
weekly:
  - {title: "Rapid 15+10 games", count: 3, rule: "use ≥ 30s on every capture/check"}
  - {title: "Rook endgames (Practice)", minutes: 30, url: "https://lichess.org/practice"}
minimum_day: "1 Storm run or 3 review positions"
---
Why this week: …
```

---

## 9. Skill taxonomy (`taxonomy.yaml`) — Stage 2 hook

Hierarchical keys shared by diagnosis, plans and (later) book chapters. Leaves under `tactics.*` reuse Lichess puzzle theme slugs so they map directly to training URLs.

```yaml
tactics:      {fork, pin, skewer, discoveredAttack, doubleCheck, hangingPiece, backRankMate,
               mateIn1, mateIn2, mateIn3, deflection, attraction, sacrifice, zugzwang, other}
calculation:  {defensive-resources, candidate-moves, visualization}
strategy:     {pawn-structure, piece-activity, weak-squares, open-files, prophylaxis}
middlegame:   {conversion, defence, attack-on-king, time-management}
endgame:      {pawn, rook, minor-piece, queen, theoretical-positions, technique}
opening:      {repertoire-white, repertoire-black, early-deviations}
psychology:   {tilt, rushing, passivity}
```
Each node may carry `lichess_theme`, `lichess_url`, and (Stage 2) `resources: [{book, chapter, pages, lang: ru}]`.

---

## 10. Dashboard (GitHub Pages)

Single page, mobile-first (training happens on the phone):
1. **Today** — plan items with links and minutes, review-study link, "minimum day" fallback; streak of active days.
2. **This week** — planned vs done (games played, puzzles solved, review results).
3. **Trends** — main-perf rating, blunders/game by phase, time-pressure share, puzzle win rate for focus themes, Storm best.
4. **Diagnosis** — current top weaknesses with evidence and confidence.
5. **Journal** — latest weekly review (rendered Markdown).
6. Footer: last sync time, token expiry warning (< 30 days).

Build: `site/` → `dist/` in `nightly.yml`, deployed with `actions/deploy-pages`. Data copied from `data/derived/` and `plan/`.

---

## 11. Workflows

**`nightly.yml`** (cron ~03:00 UTC + manual dispatch): checkout → setup uv + cached Stockfish → `python -m pipeline all` → commit `data/` if changed (`[skip ci]`) → build & deploy site.
**`weekly.yml`** (Sunday ~16:00 UTC): snapshots → diagnose → open check-in issue (§7.3) → commit.
**`checkin.yml`** (on issue closed with label `checkin`): parse → `reviews.jsonl` → commit.
Concurrency group `pipeline` so runs never overlap (respects the one-request-at-a-time rule too).

Secrets: `LICHESS_TOKEN`. Permissions: `contents: write`, `pages: write`, `id-token: write`, `issues: write`.

---

## 12. Testing

- Fixture PGNs/ndjson (a handful of own games with known blunders) for `mistakes.py` and tagging.
- Deterministic unit tests for win%/accuracy/classification math and Leitner scheduling.
- Mocked HTTP for client (429 handling, ndjson streaming, pagination with `before`).
- `--dry-run` for `publish_study` (prints PGN, no API writes).

---

## 13. Milestones

| # | Milestone | Done when |
|---|---|---|
| M0 | Repo skeleton | layout, `config.yaml`, `CLAUDE.md`, uv project, CI lint/test green |
| M1 | Sync | full history imported locally; incremental re-run fetches only new data |
| M2 | Analysis + mistakes | all rapid/classical games analysed; `mistakes.jsonl` populated; spot-checked against Lichess analysis for 3 games |
| M3 | Metrics + diagnosis | `metrics.json` + `diagnosis.json` produced; **baseline report** written by Claude in `journal/baseline.md` |
| M4 | Automation | nightly/weekly workflows running on GitHub Actions |
| M5 | Review study | due positions appear in the Lichess study nightly; check-in issue round-trip works |
| M6 | Dashboard | Pages site live with Today / Trends / Diagnosis |
| M7 | Coaching loop | first weekly review + plan generated by a scheduled Claude session |

---

## 14. Risks and mitigations

| Risk | Mitigation |
|---|---|
| Few games/week → noisy stats | Rolling 4-week windows, `n` shown everywhere, puzzle data weighted early |
| Heuristic motif tags wrong | Tags only as hints; diagnosis evidence always shows raw counts; refine with fixtures |
| Token expiry (~1 year) | Expiry date in `state.json`, warning on dashboard |
| Lichess API changes | Thin client module, raw responses stored, contract tests on fixtures |
| Public repo exposes puzzle activity/plan | Decide in open question 3; fallback: private repo + private dashboard elsewhere |
| Review feedback friction | Keep check-in to one weekly issue with checkboxes; allow "skip" |
| Repo growth | ndjson is small (~1–2 KB/game); analysis cache compressed if > 50 MB |

---

## 15. Open questions

1. Lichess username and main time control (default assumed: rapid).
2. Realistic time budget (default: 20 min/day, 3 games/week, 30 min weekend).
3. Public repo + GitHub Pages, or private dashboard?
4. Review feedback: weekly GitHub-issue check-in vs reporting to Claude in chat.
5. Baseline window: whole history or last 12 months (older games reflect an older level).
6. Language of plans/journal (English assumed; Stage 2 books are Russian).
