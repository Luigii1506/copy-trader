"""Curve census: the full equity history (portfolio) of every trader on the leaderboard.

Why: the leaderboard keeps losing and blown-up wallets (on 2026-10-06: 22k with negative all-time
PnL, 10k with <$100 left after losing >$10k). Their portfolio() curves go back years, so pulling
them all gives a large retroactive persistence test with far less survivorship bias than the
300-wallet universe - in a day instead of months of forward collection.

Wallets are fetched in a seeded random order, so whatever has been downloaded at any moment is a
uniform random sample of the census. Progress is saved and the job resumes where it stopped.
"""

from __future__ import annotations

import gzip
import json
import logging
import random
import time
from typing import Any

from .hyperliquid import HyperliquidClient
from .storage import DATA_DIR, PLATFORM, RawWriter, envelope, read_json, utcnow, write_json

log = logging.getLogger(__name__)

CENSUS_PATH = DATA_DIR / "state" / "census.json"
MIN_ALLTIME_VOLUME = 10_000.0
SAVE_EVERY = 10
# A new raw file every N wallets: finished chunks can be normalized and analyzed while the census runs.
CHUNK = 1_000


def _latest_raw(dataset: str) -> dict[str, Any] | None:
    files = sorted((DATA_DIR / "raw" / PLATFORM / dataset).glob("date=*/*.jsonl.gz"))
    if not files:
        return None
    with gzip.open(files[-1], "rt", encoding="utf-8") as fh:
        return json.loads(fh.readline())


def _build_plan() -> dict[str, Any]:
    board = _latest_raw("leaderboard")
    if board is None:
        raise RuntimeError("no leaderboard snapshot yet; run `copy-trader leaderboard` first")
    vaults = _latest_raw("vaults")
    vault_addresses = {v["summary"]["vaultAddress"].lower() for v in vaults["payload"]} if vaults else set()

    wallets = []
    for row in board["payload"]["leaderboardRows"]:
        address = row["ethAddress"].lower()
        volume = float(dict(row["windowPerformances"])["allTime"]["vlm"])
        if volume >= MIN_ALLTIME_VOLUME and address not in vault_addresses:
            wallets.append(address)

    seed = int(utcnow().timestamp())
    wallets.sort()
    random.Random(seed).shuffle(wallets)
    return {
        "created_at": utcnow().isoformat(),
        "leaderboard_fetched_at": board["fetched_at"],
        "min_alltime_volume": MIN_ALLTIME_VOLUME,
        "seed": seed,
        "wallets": wallets,
        "done": 0,
    }


def run(client: HyperliquidClient) -> None:
    plan = read_json(CENSUS_PATH, None)
    if plan is None:
        plan = _build_plan()
        write_json(CENSUS_PATH, plan)
        log.info("census: planned %d wallets (seed %d)", len(plan["wallets"]), plan["seed"])

    wallets, start = plan["wallets"], plan["done"]
    if start >= len(wallets):
        log.info("census: complete (%d wallets)", len(wallets))
        return

    writer = RawWriter("portfolio_census", utcnow())
    t0, failures = time.monotonic(), 0
    for i in range(start, len(wallets)):
        user = wallets[i]
        if i > start and i % CHUNK == 0:
            writer = RawWriter("portfolio_census", utcnow())
        try:
            fetched = utcnow()
            writer.write(envelope("portfolio_census", {"type": "portfolio", "user": user},
                                  client.portfolio(user), fetched))
        except Exception:
            failures += 1
            log.exception("census: wallet %s failed", user)
        done = i + 1
        if done % SAVE_EVERY == 0 or done == len(wallets):
            plan["done"] = done
            write_json(CENSUS_PATH, plan)
            rate = (done - start) / max(time.monotonic() - t0, 1e-9)
            log.info("census: %d/%d done, %d failed, ~%.1fh left",
                     done, len(wallets), failures, (len(wallets) - done) / max(rate, 1e-9) / 3600)


def progress() -> tuple[int, int]:
    plan = read_json(CENSUS_PATH, None)
    return (plan["done"], len(plan["wallets"])) if plan else (0, 0)
