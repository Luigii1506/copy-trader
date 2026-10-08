"""Collector entry point.

    python -m collector.sync leaderboard   # leaderboard + vaults snapshot when a new version exists (run hourly)
    python -m collector.sync wallets       # state, portfolio and new fills for every tracked wallet
    python -m collector.sync all           # both, in that order
    python -m collector.sync normalize     # raw JSON -> Parquet tables (see collector/normalize.py)
    python -m collector.sync health        # are the jobs running on schedule? exit code 1 if not
    python -m collector.sync census        # equity history of every leaderboard trader (one-off, resumable)
    python -m collector.sync papertrade    # paper-trading engine, runs forever (docs/decisions/ADR-002)
    python -m collector.sync papertrade-status
    python -m collector.sync papertrade-halt   # kill switch: close every paper position and stop
    python -m collector.sync dashboard     # write DATA_DIR/dashboard.html (plan section 31)
    python -m collector.sync papertrade-tracking   # copying cost: book vs copied trader (ADR-002)

Installed as the `copy-trader` command (`uv tool install .`), which is what launchd runs.
"""

from __future__ import annotations

import argparse
import fcntl
import json
import logging
import sqlite3
import time
from datetime import datetime, timedelta
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from . import census, health, normalize, universe
from .hyperliquid import LEADERBOARD_URL, VAULTS_URL, HyperliquidClient
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


LEADERBOARD_VERSIONS_PATH = DATA_DIR / "state" / "leaderboard_versions.jsonl"
MIN_SNAPSHOT_SPACING = timedelta(hours=6)
CANDLES_EVERY = timedelta(hours=20)


def sync_leaderboard(client: HyperliquidClient) -> None:
    """Runs hourly. Downloads the leaderboard only when Hyperliquid has published a new version, and
    at most once per MIN_SNAPSHOT_SPACING (~4 MB each). Every version seen is logged, stored or not,
    which tells us how often the source actually updates."""
    now = utcnow()
    state_path = last_run_path("leaderboard")
    state = read_json(state_path, {})
    head = client.stats_version(LEADERBOARD_URL)
    _log_version(head, now)

    last_stored = state.get("stored_at")
    if head["etag"] and head["etag"] == state.get("etag"):
        log.info("leaderboard: unchanged since %s", state.get("last_modified"))
    elif last_stored and now - datetime.fromisoformat(last_stored) < MIN_SNAPSHOT_SPACING:
        log.info("leaderboard: new version %s, but last snapshot is under %s old; skipping",
                 head["last_modified"], MIN_SNAPSHOT_SPACING)
    else:
        board, version = client.leaderboard()
        record = envelope("leaderboard", {"url": LEADERBOARD_URL}, board, now)
        record["source_version"] = version
        RawWriter("leaderboard", now).write(record)
        _, added = universe.refresh(board, now)
        log.info("leaderboard: %d rows saved (data as of %s), %d wallets added to universe",
                 len(board["leaderboardRows"]), version["last_modified"], added)

        # Vaults are Hyperliquid's native copy trading, and their addresses must be told apart from traders.
        vaults, vault_version = client.vaults()
        record = envelope("vaults", {"url": VAULTS_URL}, vaults, utcnow())
        record["source_version"] = vault_version
        RawWriter("vaults", now).write(record)
        log.info("vaults: %d saved", len(vaults))
        state.update(etag=version["etag"], last_modified=version["last_modified"], stored_at=now.isoformat())

    # Daily candles for every perp coin once a day (benchmarks + accumulation track).
    candles_at = state.get("candles_at")
    if candles_at is None or now - datetime.fromisoformat(candles_at) >= CANDLES_EVERY:
        sync_candles(client)
        state["candles_at"] = now.isoformat()

    # Daily vault details (native copy trading: depositing replicates the leader exactly).
    vaults_at = state.get("vault_details_at")
    if vaults_at is None or now - datetime.fromisoformat(vaults_at) >= CANDLES_EVERY:
        sync_vault_details(client)
        state["vault_details_at"] = now.isoformat()

    state["finished_at"] = utcnow().isoformat()
    write_json(state_path, state)


VAULT_UNIVERSE_PATH = DATA_DIR / "universe" / "vaults.json"
VAULT_MIN_TVL = 10_000.0


def sync_vault_details(client: HyperliquidClient) -> None:
    """vaultDetails (portfolio history, commission, followers) for every open vault with TVL >=
    VAULT_MIN_TVL, plus every vault ever tracked: the list is append-only, so vaults that later
    shrink or close stay in the study instead of silently becoming survivors-only data."""
    now = utcnow()
    tracked: dict[str, str] = read_json(VAULT_UNIVERSE_PATH, {})
    listing, _ = client.vaults()
    for v in listing:
        s = v["summary"]
        if not s["isClosed"] and float(s["tvl"]) >= VAULT_MIN_TVL:
            tracked.setdefault(s["vaultAddress"].lower(), now.isoformat())
    write_json(VAULT_UNIVERSE_PATH, tracked)
    writer = RawWriter("vault_details", now)
    saved = 0
    for address in sorted(tracked):
        try:
            details = client.info({"type": "vaultDetails", "vaultAddress": address})
            writer.write(envelope("vault_details", {"type": "vaultDetails", "vaultAddress": address},
                                  details, utcnow()))
            saved += 1
        except Exception:
            log.exception("vault %s failed; continuing", address)
    log.info("vault details: %d of %d tracked vaults saved", saved, len(tracked))


CANDLES_CURSOR_PATH = DATA_DIR / "state" / "candles_cursor.json"
DAY_MS = 86_400_000


def sync_candles(client: HyperliquidClient) -> None:
    """Daily 1d candles for every perp coin on every dex, incremental via a per-coin cursor.

    Delisted coins are fetched too, on purpose: their histories are the graveyard an
    accumulation study must see, or it only learns from survivors. First run pulls each
    coin's full history (~90 min at this job's API budget); later runs refetch from one
    day before the cursor (the still-forming candle) and dedup happens at normalize."""
    cursors: dict[str, int] = read_json(CANDLES_CURSOR_PATH, {})
    coins: list[str] = []
    for dex in client.perp_dexs():
        body = {"type": "meta"} | ({"dex": dex} if dex else {})
        coins.extend(asset["name"] for asset in client.info(body)["universe"])
    started = utcnow()
    writer = RawWriter("candles", started)
    fetched_count = rows = 0
    for i, coin in enumerate(sorted(set(coins)), 1):
        try:
            start_ms = max(0, cursors.get(coin, 0) - DAY_MS)
            candles = client.candles(coin, "1d", start_ms=start_ms)
            if not candles:
                continue
            writer.write(envelope("candles", {"type": "candleSnapshot", "coin": coin, "interval": "1d"},
                                  candles, utcnow()))
            cursors[coin] = candles[-1]["t"]
            fetched_count += 1
            rows += len(candles)
        except Exception:
            log.exception("candles: %s failed; continuing", coin)
        if i % 25 == 0:
            write_json(CANDLES_CURSOR_PATH, cursors)
    write_json(CANDLES_CURSOR_PATH, cursors)
    log.info("candles: %d coins, %d rows", fetched_count, rows)


def _log_version(version: dict[str, str], seen_at: datetime) -> None:
    """Append-only log of every distinct leaderboard version we observe."""
    last = None
    if LEADERBOARD_VERSIONS_PATH.exists():
        lines = LEADERBOARD_VERSIONS_PATH.read_text().splitlines()
        last = json.loads(lines[-1]) if lines else None
    if last and last["etag"] == version["etag"]:
        return
    LEADERBOARD_VERSIONS_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(LEADERBOARD_VERSIONS_PATH, "a") as fh:
        fh.write(json.dumps({**version, "first_seen": seen_at.isoformat()}) + "\n")


def followed_by_papertrade() -> list[str]:
    """Traders with an open paper-trading book, so their fills are collected too."""
    db_path = DATA_DIR / "papertrade" / "papertrade.db"
    if not db_path.exists():
        return []
    with sqlite3.connect(f"file:{db_path}?mode=ro", uri=True) as db:
        return [r[0] for r in db.execute("select distinct trader from books where closed_at is null")]


CANDIDATES_TOP_SCORE = 100
CANDIDATES_TOP_SHARPE = 50


def candidate_wallets() -> list[str]:
    """Top census traders by the live selection signals.

    Their fills make behavior penalties and exit rules apply to the wallets the engine is most
    likely to pick next, instead of only to those it already follows. Append-only via the
    `candidates` cohort, so the covered set only grows. Also writes state/ranking.json: the
    top of the TraderScore ranking that the dashboard shows (plan section 36, "mostrar ranking")."""
    try:
        import polars as pl
        from papertrade.selection import candidate_signals
        now = utcnow()
        pool = candidate_signals(now)
        scored = pool.filter(pl.col("trader_score").is_not_null()).sort("trader_score", descending=True)
        write_json(DATA_DIR / "state" / "ranking.json", {
            "generated_at": now.isoformat(),
            "eligible": scored.height,
            "top": scored.head(20).select(
                "user", "trader_score", "sharpe", "low_dd", "consistency", "n_obs",
                "account_value", "behavior_known", "behavior_penalty",
            ).to_dicts(),
        })
        by_score = scored.head(CANDIDATES_TOP_SCORE)["user"].to_list()
        by_sharpe = (pool.filter(pl.col("sharpe").is_not_null() & pl.col("sharpe").is_finite())
                     .sort("sharpe", descending=True).head(CANDIDATES_TOP_SHARPE)["user"].to_list())
        return sorted(set(by_score) | set(by_sharpe))
    except Exception:
        log.exception("candidate funnel failed; continuing without it")
        return []


def sync_wallets(client: HyperliquidClient, limit: int | None = None) -> None:
    started = utcnow()
    followed = followed_by_papertrade()
    if followed:
        added = universe.add(followed, "papertrade", started)
        log.info("wallets: %d traders followed by paper trading, %d new in universe", len(followed), added)
    candidates = candidate_wallets()
    if candidates:
        added = universe.add(candidates, "candidates", started)
        log.info("wallets: %d score/sharpe candidates, %d new in universe", len(candidates), added)
    wallets = sorted(universe.load()["wallets"])[:limit]
    if not wallets:
        log.error("universe is empty; run `python -m collector.sync leaderboard` first")
        return

    cursors: dict[str, int] = read_json(FILLS_CURSOR_PATH, {})
    # Positions are per perp dex: HIP-3 dexs (equity/index perps etc.) are invisible from the main one.
    # Fills and portfolio already cover every dex.
    dexs = client.perp_dexs()
    writers = {name: RawWriter(name, started) for name in ("clearinghouse_state", "portfolio", "fills")}
    failures = 0
    gaps: list[str] = []
    t0 = time.monotonic()

    for i, user in enumerate(wallets, 1):
        try:
            for dex in dexs:
                fetched = utcnow()
                state = client.clearinghouse_state(user, dex)
                request = {"type": "clearinghouseState", "user": user, "dex": dex}
                writers["clearinghouse_state"].write(envelope("clearinghouse_state", request, state, fetched))

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
    parser.add_argument("job", choices=["leaderboard", "wallets", "all", "normalize", "health", "census",
                                        "papertrade", "papertrade-status", "papertrade-halt", "papertrade-tracking", "dashboard"])
    parser.add_argument("--limit", type=int, help="only sync the first N tracked wallets (for testing)")
    args = parser.parse_args()

    if args.job == "health":
        raise SystemExit(health.main())
    if args.job == "papertrade-tracking":
        from papertrade import tracking
        raise SystemExit(tracking.main())
    if args.job == "dashboard":
        from papertrade import dashboard
        raise SystemExit(dashboard.main())
    if args.job == "papertrade-status":
        from papertrade import status
        raise SystemExit(status.main())
    if args.job == "papertrade-halt":
        from papertrade.engine import KILL_FILE
        KILL_FILE.parent.mkdir(parents=True, exist_ok=True)
        KILL_FILE.touch()
        print(f"kill switch set ({KILL_FILE}); the engine closes all positions on its next step. "
              "Delete the file to allow a restart.")
        return

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
        if args.job == "papertrade":
            from papertrade.engine import run_forever
            run_forever()
            return
        if args.job == "census":
            client = HyperliquidClient()
            try:
                census.run(client)
            finally:
                client.close()
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
