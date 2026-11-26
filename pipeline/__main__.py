"""CLI: python -m pipeline sync|snapshot|analyze|metrics|diagnose|study|all"""

from __future__ import annotations

import argparse
import logging
import sys

from . import fetch
from .config import load_config, load_token
from .lichess_client import LichessClient
from .state import load_state, now_ms, save_state

SOURCES = ("games", "puzzles", "ratings")
NOT_YET = {"analyze": "M2", "mistakes": "M2", "metrics": "M3", "diagnose": "M3", "study": "M5"}


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


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="python -m pipeline")
    p.add_argument("-v", "--verbose", action="store_true")
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("sync", help="incremental sync of games, puzzles, ratings")
    s.add_argument("--only", default=",".join(SOURCES), help="comma list of " + ",".join(SOURCES))
    sub.add_parser("snapshot", help="weekly puzzle + storm dashboard snapshot")
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
    if args.cmd == "all":
        return cmd_sync(list(SOURCES))
    print(f"{args.cmd}: not implemented yet (milestone {NOT_YET[args.cmd]})", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
