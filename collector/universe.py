"""Tracked-wallet universe, built from leaderboard snapshots.

The universe is append-only: a wallet is never removed, even if it blows up or leaves the
leaderboard. Removing losers would reintroduce survivorship bias into every later analysis.

Cohorts (a wallet may belong to several):
- top_alltime_pnl: largest all-time PnL
- top_month_roi:   best 30-day ROI (with a minimum account size, to skip dust accounts)
- random:          random sample of eligible wallets; the control group for persistence tests
"""

from __future__ import annotations

import random
from datetime import datetime
from typing import Any

from .storage import DATA_DIR, read_json, write_json

UNIVERSE_PATH = DATA_DIR / "universe" / "hyperliquid.json"

MIN_ACCOUNT_VALUE = 10_000.0
TOP_ALLTIME_PNL = 100
TOP_MONTH_ROI = 100
RANDOM_SIZE = 100


def _window(row: dict[str, Any], name: str) -> dict[str, float]:
    for window, perf in row["windowPerformances"]:
        if window == name:
            return {k: float(v) for k, v in perf.items()}
    return {"pnl": 0.0, "roi": 0.0, "vlm": 0.0}


def _eligible(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        r for r in rows
        if float(r["accountValue"]) >= MIN_ACCOUNT_VALUE and _window(r, "month")["vlm"] > 0
    ]


def load() -> dict[str, Any]:
    return read_json(UNIVERSE_PATH, {"wallets": {}, "random_seed": None})


def refresh(leaderboard: dict[str, Any], now: datetime) -> tuple[dict[str, Any], int]:
    """Add newly qualifying wallets. Returns (universe, number_added)."""
    universe = load()
    wallets: dict[str, Any] = universe["wallets"]
    rows = leaderboard["leaderboardRows"]
    eligible = _eligible(rows)

    picks: dict[str, list[dict[str, Any]]] = {
        "top_alltime_pnl": sorted(rows, key=lambda r: _window(r, "allTime")["pnl"], reverse=True)[:TOP_ALLTIME_PNL],
        "top_month_roi": sorted(eligible, key=lambda r: _window(r, "month")["roi"], reverse=True)[:TOP_MONTH_ROI],
    }

    # The random cohort is drawn once; its seed is recorded so the draw is reproducible.
    if universe["random_seed"] is None:
        seed = int(now.timestamp())
        universe["random_seed"] = seed
        picks["random"] = random.Random(seed).sample(eligible, min(RANDOM_SIZE, len(eligible)))

    added = 0
    for cohort, cohort_rows in picks.items():
        for row in cohort_rows:
            address = row["ethAddress"].lower()
            entry = wallets.get(address)
            if entry is None:
                entry = wallets[address] = {"added_at": now.isoformat(), "cohorts": []}
                added += 1
            if cohort not in entry["cohorts"]:
                entry["cohorts"].append(cohort)

    write_json(UNIVERSE_PATH, universe)
    return universe, added
