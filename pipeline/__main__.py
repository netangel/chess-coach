"""CLI: python -m pipeline sync|snapshot|analyze|mistakes|compare|metrics|diagnose|study|all"""

from __future__ import annotations

import argparse
import logging
import sys

from . import analyze, diagnose, fetch, metrics, mistakes
from .config import load_config, load_token
from .lichess_client import LichessClient
from .state import load_state, now_ms, save_state

SOURCES = ("games", "puzzles", "ratings")
NOT_YET = {"study": "M5"}


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
    for name in NOT_YET:
        sub.add_parser(name)
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
    if args.cmd == "compare":
        print(analyze.compare_report(args.game_id, load_config()))
        return 0
    if args.cmd == "all":
        return (
            cmd_sync(list(SOURCES))
            or cmd_analyze([], False, None, None)
            or cmd_mistakes()
            or cmd_metrics()
        )
    print(f"{args.cmd}: not implemented yet (milestone {NOT_YET[args.cmd]})", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
