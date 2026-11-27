"""CLI: python -m pipeline sync|snapshot|analyze|mistakes|compare|metrics|diagnose|study|all"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

from . import analyze, checkin, diagnose, fetch, metrics, mistakes, plan, publish_study, site
from .config import load_config, load_token
from .lichess_client import LichessClient
from .state import load_state, now_ms, save_state

SOURCES = ("games", "puzzles", "ratings", "token")


def cmd_sync(only: list[str]) -> int:
    cfg = load_config()
    state = load_state()
    with LichessClient(load_token()) as client:
        try:
            for source in only:
                if source == "games":
                    res = fetch.sync_games(client, cfg, state)
                elif source == "puzzles":
                    res = fetch.sync_puzzles(client, state)
                elif source == "token":
                    res = fetch.sync_token(client, state)
                else:
                    res = fetch.sync_ratings(client, cfg, state)
                print(res)
        finally:
            state.lastSyncAt = now_ms()
            save_state(state)
    return 0


def cmd_snapshot() -> int:
    cfg = load_config()
    with LichessClient(load_token()) as client:
        print(fetch.snapshot(client, cfg))
    return 0


def cmd_analyze(game_ids, force, limit, threads) -> int:
    cfg = load_config()
    if threads:
        cfg.engine.threads = threads
    stats = analyze.run(cfg, game_ids=game_ids or None, force=force, limit=limit)
    print("analyze:", ", ".join(f"{k} {v}" for k, v in sorted(stats.items())))
    return 0


def cmd_mistakes() -> int:
    stats = mistakes.run(load_config())
    print("mistakes:", ", ".join(f"{k} {v}" for k, v in sorted(stats.items())))
    return 0


def cmd_metrics() -> int:
    stats = metrics.run(load_config())
    print("metrics:", ", ".join(f"{k} {v}" for k, v in sorted(stats.items())))
    return 0


def cmd_diagnose() -> int:
    d = diagnose.run(load_config())
    print(f"diagnose: {len(d['weaknesses'])} weaknesses ({d['basis']['games']})")
    for w in d["weaknesses"][:5]:
        print(f"  {w['score']:.2f} {w['confidence']:<6} {w['skill']}")
    return 0


def today():
    return datetime.now(UTC).date()


def cmd_study(dry_run: bool, init: bool, force: bool) -> int:
    cfg = load_config()
    state = load_state()
    token = load_token()
    if not dry_run and not token:
        print("study: skipped (no LICHESS_TOKEN)")
        return 0
    with LichessClient(token) as client:
        if init:
            if cfg.lichess.review_study_id:
                print(f"study: already configured ({cfg.lichess.review_study_id})")
                return 0
            study_id = publish_study.create_study(client)
            publish_study.save_study_id(study_id)
            print(f"study: created {publish_study.study_url(study_id)} and saved it to config.yaml")
            cfg = load_config()
        if not dry_run and not cfg.lichess.review_study_id:
            print("study: skipped (lichess.review_study_id not set; run `study --init`)")
            return 0
        res = publish_study.publish(client, cfg, state, today(), dry_run=dry_run, force=force)
    if not dry_run:
        save_state(state)
    print("study:", ", ".join(f"{k} {v}" for k, v in res.items()))
    return 0


def cmd_checkin(action: str, issue: int | None, body_file: str | None) -> int:
    cfg = load_config()
    if action == "render":
        sys.stdout.write(checkin.render(cfg, load_state(), today()))
        return 0
    if issue is None or body_file is None:
        print("checkin apply needs --issue and --body-file", file=sys.stderr)
        return 2
    body = Path(body_file).read_text(encoding="utf-8")
    res = checkin.apply(body, issue, cfg, today())
    print("checkin:", ", ".join(f"{k} {v}" for k, v in res.items()))
    return 0


def cmd_site() -> int:
    out = site.build(load_config(), load_state())
    print(f"site: built {out}")
    return 0


def study_in_ci() -> int:
    """`all` publishes the study only in CI, so CI stays the single writer of the study."""
    if not os.environ.get("GITHUB_ACTIONS"):
        print("study: skipped outside GitHub Actions (run `study` explicitly to publish)")
        return 0
    return cmd_study(False, False, False)


def cmd_plan_check() -> int:
    problems = plan.check_file(load_config())
    for p in problems:
        print(f"plan: {p}", file=sys.stderr)
    print("plan: ok" if not problems else f"plan: {len(problems)} problem(s)")
    return 1 if problems else 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="python -m pipeline")
    p.add_argument("-v", "--verbose", action="store_true")
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("sync", help="incremental sync of games, puzzles, ratings")
    s.add_argument("--only", default=",".join(SOURCES), help="comma list of " + ",".join(SOURCES))
    sub.add_parser("snapshot", help="weekly puzzle + storm dashboard snapshot")
    a = sub.add_parser("analyze", help="Stockfish analysis of eligible games (cached)")
    a.add_argument("--game", action="append", default=[], help="only this game id (repeatable)")
    a.add_argument("--force", action="store_true", help="re-run the engine even if cached")
    a.add_argument("--limit", type=int, help="max games to run through the engine")
    a.add_argument("--threads", type=int, help="override engine.threads for this run")
    sub.add_parser("mistakes", help="extract critical positions into data/mistakes.jsonl")
    sub.add_parser("metrics", help="weekly + rolling aggregates into data/derived/")
    sub.add_parser("diagnose", help="ranked weaknesses into data/derived/diagnosis.json")
    c = sub.add_parser("compare", help="our analysis vs Lichess server analysis for a game")
    c.add_argument("game_id")
    st = sub.add_parser("study", help="publish due review positions to the Lichess study")
    st.add_argument("--dry-run", action="store_true", help="print the PGN, no API writes")
    st.add_argument("--init", action="store_true", help="create the private study if not set")
    st.add_argument("--force", action="store_true", help="rebuild even if unchanged")
    sub.add_parser("site", help="build the dashboard into dist/")
    sub.add_parser("plan-check", help="validate plan/current.md against the coaching rules")
    ci = sub.add_parser("checkin", help="weekly review check-in issue")
    ci.add_argument("action", choices=["render", "apply"])
    ci.add_argument("--issue", type=int)
    ci.add_argument("--body-file")
    sub.add_parser("all", help="run every implemented nightly step")
    args = p.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format="%(levelname)s %(name)s: %(message)s",
    )

    if args.cmd == "sync":
        only = [s.strip() for s in args.only.split(",") if s.strip()]
        bad = set(only) - set(SOURCES)
        if bad:
            p.error(f"unknown source(s): {', '.join(sorted(bad))}")
        return cmd_sync(only)
    if args.cmd == "snapshot":
        return cmd_snapshot()
    if args.cmd == "analyze":
        return cmd_analyze(args.game, args.force, args.limit, args.threads)
    if args.cmd == "mistakes":
        return cmd_mistakes()
    if args.cmd == "metrics":
        return cmd_metrics()
    if args.cmd == "diagnose":
        return cmd_diagnose()
    if args.cmd == "study":
        return cmd_study(args.dry_run, args.init, args.force)
    if args.cmd == "checkin":
        return cmd_checkin(args.action, args.issue, args.body_file)
    if args.cmd == "plan-check":
        return cmd_plan_check()
    if args.cmd == "site":
        return cmd_site()
    if args.cmd == "compare":
        print(analyze.compare_report(args.game_id, load_config()))
        return 0
    if args.cmd == "all":
        return (
            cmd_sync(list(SOURCES))
            or cmd_analyze([], False, None, None)
            or cmd_mistakes()
            or cmd_metrics()
            or study_in_ci()
        )
    p.error(f"unknown command {args.cmd}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
