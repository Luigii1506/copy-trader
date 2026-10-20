"""Evidence summary for the dashboard: forward leaderboard test and copying cost.

Both come from the same functions as the research notes (analysis.persistence's
leaderboard_persistence, papertrade.tracking.report). Computing the forward test reads every
leaderboard snapshot, so the result is cached in state/evidence.json and refreshed at most
every CACHE_TTL.
"""

from __future__ import annotations

import logging
import statistics
from datetime import datetime, timedelta

import polars as pl

from analysis.persistence import leaderboard_persistence, summarize
from collector.storage import DATA_DIR, read_json, write_json

from .selection import _read
from .store import DB_PATH, Store
from .tracking import report

log = logging.getLogger(__name__)

CACHE_PATH = DATA_DIR / "state" / "evidence.json"
CACHE_TTL = timedelta(hours=6)


def _ic_row(table: pl.DataFrame, signal: str) -> dict | None:
    s = summarize(table)
    if s.is_empty():
        return None
    row = s.filter(pl.col("signal") == signal)
    if row.is_empty():
        return None
    r = row.to_dicts()[0]
    return {"periods": r["periods"], "mean_ic": r["mean_ic"], "ic_tstat": r["ic_tstat"],
            "ic_positive": r["ic_positive"]}


def forward_test() -> dict | None:
    """Week-ROI -> next-week-ROI on leaderboard snapshots: all daily pairs and non-overlapping weeks."""
    board = _read("leaderboard")
    if board is None:
        return None
    vaults = _read("vaults")
    table = leaderboard_persistence(board, horizon_days=7, period="week",
                                    exclude=vaults["vault_address"].unique() if vaults is not None else None)
    if table.is_empty():
        return None
    table = table.with_columns(day=pl.col("snapshot_a").dt.date())
    first = table["day"].min()
    independent = table.filter(((pl.col("day") - first).dt.total_days() % 7) == 0).drop("day")
    table = table.drop("day")
    return {
        "first": str(first),
        "wallets": float(table["n"].mean()),
        "dropped_median": float(table["dropped"].median()),
        "all_pairs": _ic_row(table, "week_roi"),
        "independent": _ic_row(independent, "week_roi"),
        "random": _ic_row(table, "random"),
    }


def copying_cost() -> dict | None:
    if not DB_PATH.exists():
        return None
    store = Store()
    try:
        rows = [r for r in report(store) if r["active"]]
    finally:
        store.close()
    if not rows:
        return None
    gaps = [r["gap_per_day"] for r in rows]
    return {"books": len(rows), "median_gap_per_day": statistics.median(gaps),
            "p25": sorted(gaps)[len(gaps) // 4], "p75": sorted(gaps)[(3 * len(gaps)) // 4],
            "max_hours": max(r["hours"] for r in rows)}


def evidence(now: datetime, force: bool = False) -> dict:
    cached = read_json(CACHE_PATH, None)
    if cached and not force and now - datetime.fromisoformat(cached["computed_at"]) < CACHE_TTL:
        return cached
    result: dict = {"computed_at": now.isoformat()}
    for key, fn in (("forward", forward_test), ("copying", copying_cost)):
        try:
            result[key] = fn()
        except Exception:
            log.exception("evidence %s failed", key)
            result[key] = None
    write_json(CACHE_PATH, result)
    return result
