"""Collector entry point.

    python -m collector.sync leaderboard   # full leaderboard snapshot + universe refresh (run daily)
    python -m collector.sync wallets       # state, portfolio and new fills for every tracked wallet
    python -m collector.sync all           # both, in that order
    python -m collector.sync normalize     # raw JSON -> Parquet tables (see collector/normalize.py)
    python -m collector.sync health        # are the jobs running on schedule? exit code 1 if not

Installed as the `copy-trader` command (`uv tool install .`), which is what launchd runs.
"""

from __future__ import annotations

import argparse
import fcntl
import logging
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from . import health, normalize, universe
from .hyperliquid import HyperliquidClient
from .storage import DATA_DIR, RawWriter, envelope, read_json, utcnow, write_json

log = logging.getLogger("collector")

FILLS_CURSOR_PATH = DATA_DIR / "state" / "hyperliquid_fills_cursor.json"


def last_run_path(job: str) -> Path:
    return DATA_DIR / "state" / f"last_run_{job}.json"


def fill_gap_suspected(start_ms: int, fills: list[dict]) -> bool:
    """True when fills between runs may have been lost.

    An incremental fetch starts at the timestamp of the last fill already stored, so that fill is
    returned again. If the oldest returned fill is newer than the cursor, the fills in between fell
    out of the API's "10,000 most recent" window before we fetched them.
    """
    return start_ms > 0 and bool(fills) and min(f["time"] for f in fills) > start_ms


def sync_leaderboard(client: HyperliquidClient) -> None:
    started = utcnow()
    board = client.leaderboard()
    RawWriter("leaderboard", started).write(envelope("leaderboard", {"url": "leaderboard"}, board, started))
    _, added = universe.refresh(board, started)
    rows = len(board["leaderboardRows"])
    write_json(last_run_path("leaderboard"), {"finished_at": utcnow().isoformat(), "rows": rows, "added": added})
    log.info("leaderboard: %d rows saved, %d wallets added to universe", rows, added)


def sync_wallets(client: HyperliquidClient, limit: int | None = None) -> None:
    started = utcnow()
    wallets = sorted(universe.load()["wallets"])[:limit]
    if not wallets:
        log.error("universe is empty; run `python -m collector.sync leaderboard` first")
        return

    cursors: dict[str, int] = read_json(FILLS_CURSOR_PATH, {})
    writers = {name: RawWriter(name, started) for name in ("clearinghouse_state", "portfolio", "fills")}
    failures = 0
    gaps: list[str] = []
    t0 = time.monotonic()

    for i, user in enumerate(wallets, 1):
        try:
            fetched = utcnow()
            state = client.clearinghouse_state(user)
            writers["clearinghouse_state"].write(
                envelope("clearinghouse_state", {"type": "clearinghouseState", "user": user}, state, fetched))

            fetched = utcnow()
            portfolio = client.portfolio(user)
            writers["portfolio"].write(envelope("portfolio", {"type": "portfolio", "user": user}, portfolio, fetched))

            fetched = utcnow()
            start_ms = cursors.get(user, 0)
            fills = client.fills_since(user, start_ms)
            request = {"type": "userFillsByTime", "user": user, "startTime": start_ms}
            record = envelope("fills", request, fills, fetched)
            if fill_gap_suspected(start_ms, fills):
                gaps.append(user)
                record["gap_suspected"] = True
                log.warning("wallet %s: possible fill gap after %d (too many fills between runs)", user, start_ms)
            writers["fills"].write(record)
            if fills:
                # Next run starts at the last seen timestamp; duplicates are removed during normalization.
                cursors[user] = max(f["time"] for f in fills)
                write_json(FILLS_CURSOR_PATH, cursors)
        except Exception:
            failures += 1
            log.exception("wallet %s failed", user)

        if i % 25 == 0 or i == len(wallets):
            log.info("wallets: %d/%d done, %d failed, %.0fs elapsed", i, len(wallets), failures, time.monotonic() - t0)

    write_json(last_run_path("wallets"), {
        "started_at": started.isoformat(),
        "finished_at": utcnow().isoformat(),
        "wallets": len(wallets),
        "failures": failures,
        "gap_suspected": gaps,
    })


@contextmanager
def job_lock(name: str) -> Iterator[bool]:
    """Non-blocking per-job lock, so a scheduled run never overlaps a manual or still-running one."""
    path = DATA_DIR / "state" / f"{name}.lock"
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as fh:
        try:
            fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            yield False
            return
        yield True


def main() -> None:
    parser = argparse.ArgumentParser(description="Hyperliquid raw data collector")
    parser.add_argument("job", choices=["leaderboard", "wallets", "all", "normalize", "health"])
    parser.add_argument("--limit", type=int, help="only sync the first N tracked wallets (for testing)")
    args = parser.parse_args()

    if args.job == "health":
        raise SystemExit(health.main())

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    # `all` touches the wallet cursors, so it shares the wallets lock.
    with job_lock("wallets" if args.job == "all" else args.job) as acquired:
        if not acquired:
            log.warning("%s is already running; skipping this run", args.job)
            return
        if args.job == "normalize":
            normalize.run()
            return
        client = HyperliquidClient()
        try:
            if args.job in ("leaderboard", "all"):
                sync_leaderboard(client)
            if args.job in ("wallets", "all"):
                sync_wallets(client, args.limit)
        finally:
            client.close()


if __name__ == "__main__":
    main()
