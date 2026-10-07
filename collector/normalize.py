"""Raw JSON -> Parquet. Raw files are never modified; every table here can be rebuilt from them.

One Parquet file per raw file:
    <DATA_DIR>/processed/hyperliquid/<table>/date=YYYY-MM-DD/<run_id>.parquet

Tables:
    leaderboard        one row per wallet per leaderboard snapshot (the persistence-study universe)
    account_snapshots  one row per wallet per perp dex per clearinghouseState call
    positions          one row per open position (any perp dex, incl. HIP-3) per clearinghouseState call
    equity_history     portfolio() account value / PnL series per period (repeats across runs; dedup when querying)
    vaults             one row per vault per vaults snapshot (Hyperliquid's native copy trading)
    equity_census      equity_history for every leaderboard trader (collector/census.py)
    fills              one row per fill (overlaps across runs; dedup on user, tid, oid when querying)

A raw file is (re)processed when its Parquet is missing or older than it, and skipped while it is
still being written (modified in the last few minutes).
"""

from __future__ import annotations

import gzip
import json
import logging
import time
from datetime import timezone
from email.utils import parsedate_to_datetime
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import polars as pl

from .storage import DATA_DIR, PLATFORM, utcnow, write_json

log = logging.getLogger(__name__)

RAW_DIR = DATA_DIR / "raw" / PLATFORM
PROCESSED_DIR = DATA_DIR / "processed" / PLATFORM
SETTLE_SECONDS = 300

Rows = list[dict[str, Any]]


def _f(value: Any) -> float | None:
    return None if value is None else float(value)


def _http_date(value: str | None) -> str | None:
    """HTTP Last-Modified -> ISO 8601 UTC."""
    if not value:
        return None
    return parsedate_to_datetime(value).astimezone(timezone.utc).isoformat()


def _records(path: Path) -> Iterator[dict[str, Any]]:
    """Yields complete records; a run killed mid-write leaves a truncated last record, which is dropped."""
    try:
        with gzip.open(path, "rt", encoding="utf-8") as fh:
            for line in fh:
                if line.strip():
                    yield json.loads(line)
    except (EOFError, gzip.BadGzipFile, json.JSONDecodeError):
        log.warning("%s ends with a truncated record (interrupted run); keeping the complete ones", path)


def leaderboard_rows(record: dict[str, Any]) -> Rows:
    rows = []
    data_as_of = _http_date(record.get("source_version", {}).get("last_modified"))
    for r in record["payload"]["leaderboardRows"]:
        row = {
            "snapshot_at": record["fetched_at"],
            "data_as_of": data_as_of,  # when Hyperliquid produced it; None for early snapshots
            "user": r["ethAddress"].lower(),
            "display_name": r.get("displayName"),
            "account_value": _f(r["accountValue"]),
        }
        for window, perf in r["windowPerformances"]:
            for metric in ("pnl", "roi", "vlm"):
                row[f"{window.lower()}_{metric}"] = _f(perf.get(metric))
        rows.append(row)
    return rows


def account_rows(record: dict[str, Any]) -> Rows:
    p = record["payload"]
    summary = p["marginSummary"]
    return [{
        "snapshot_at": record["fetched_at"],
        "user": record["request"]["user"],
        "dex": record["request"].get("dex", ""),  # "" = main perp dex; others are HIP-3
        "account_value": _f(summary["accountValue"]),
        "total_notional": _f(summary["totalNtlPos"]),
        "total_margin_used": _f(summary["totalMarginUsed"]),
        "withdrawable": _f(p.get("withdrawable")),
        "open_positions": len(p["assetPositions"]),
    }]


def position_rows(record: dict[str, Any]) -> Rows:
    rows = []
    for ap in record["payload"]["assetPositions"]:
        pos = ap["position"]
        rows.append({
            "snapshot_at": record["fetched_at"],
            "user": record["request"]["user"],
            "dex": record["request"].get("dex", ""),
            "coin": pos["coin"],
            "size": _f(pos["szi"]),  # signed: negative = short
            "entry_px": _f(pos.get("entryPx")),
            "position_value": _f(pos.get("positionValue")),
            "unrealized_pnl": _f(pos.get("unrealizedPnl")),
            "leverage_type": pos["leverage"]["type"],
            "leverage": _f(pos["leverage"]["value"]),
            "liquidation_px": _f(pos.get("liquidationPx")),
            "margin_used": _f(pos.get("marginUsed")),
            "funding_since_open": _f(pos.get("cumFunding", {}).get("sinceOpen")),
        })
    return rows


def equity_rows(record: dict[str, Any]) -> Rows:
    rows = []
    for period, series in record["payload"]:
        pnl = dict(series["pnlHistory"])
        for ts, value in series["accountValueHistory"]:
            rows.append({
                "user": record["request"]["user"],
                "period": period,
                "time_ms": ts,
                "account_value": _f(value),
                "pnl": _f(pnl.get(ts)),
            })
    return rows


def vault_rows(record: dict[str, Any]) -> Rows:
    rows = []
    for v in record["payload"]:
        s = v["summary"]
        rows.append({
            "snapshot_at": record["fetched_at"],
            "vault_address": s["vaultAddress"].lower(),
            "leader": s["leader"].lower(),
            "name": s["name"],
            "tvl": _f(s["tvl"]),
            "apr": _f(v.get("apr")),
            "is_closed": s["isClosed"],
            "relationship": s.get("relationship", {}).get("type"),
            "created_ms": s.get("createTimeMillis"),
        })
    return rows


def fill_rows(record: dict[str, Any]) -> Rows:
    return [{
        "user": record["request"]["user"],
        "time_ms": f["time"],
        "coin": f["coin"],
        "side": f["side"],
        "dir": f["dir"],
        "px": _f(f["px"]),
        "sz": _f(f["sz"]),
        "start_position": _f(f["startPosition"]),
        "closed_pnl": _f(f["closedPnl"]),
        "fee": _f(f["fee"]),
        "fee_token": f.get("feeToken"),
        "crossed": f.get("crossed"),
        "oid": f["oid"],
        "tid": f["tid"],
        "hash": f["hash"],
    } for f in record["payload"]]


# raw dataset -> [(table, row builder)]
TABLES: dict[str, list[tuple[str, Callable[[dict[str, Any]], Rows]]]] = {
    "leaderboard": [("leaderboard", leaderboard_rows)],
    "clearinghouse_state": [("account_snapshots", account_rows), ("positions", position_rows)],
    "portfolio": [("equity_history", equity_rows)],
    "portfolio_census": [("equity_census", equity_rows)],
    "fills": [("fills", fill_rows)],
    "vaults": [("vaults", vault_rows)],
}


def _process(raw: Path, dataset: str) -> int:
    builders = TABLES[dataset]
    rows: dict[str, Rows] = {table: [] for table, _ in builders}
    for record in _records(raw):
        for table, build in builders:
            rows[table].extend(build(record))

    partition, name = raw.parent.name, raw.name.removesuffix(".jsonl.gz")
    for table, table_rows in rows.items():
        out = PROCESSED_DIR / table / partition / f"{name}.parquet"
        out.parent.mkdir(parents=True, exist_ok=True)
        tmp = out.with_suffix(".parquet.tmp")
        pl.DataFrame(table_rows, infer_schema_length=None).write_parquet(tmp)
        tmp.replace(out)
    return sum(len(r) for r in rows.values())


def run() -> None:
    now = time.time()
    done = skipped = 0
    for dataset, builders in TABLES.items():
        for raw in sorted((RAW_DIR / dataset).glob("date=*/*.jsonl.gz")):
            raw_mtime = raw.stat().st_mtime
            if now - raw_mtime < SETTLE_SECONDS:
                skipped += 1  # still being written by a running collector
                continue
            outputs = [
                PROCESSED_DIR / table / raw.parent.name / raw.name.replace(".jsonl.gz", ".parquet")
                for table, _ in builders
            ]
            if all(o.exists() and o.stat().st_mtime >= raw_mtime for o in outputs):
                continue
            n = _process(raw, dataset)
            done += 1
            log.info("normalized %s/%s (%d rows)", dataset, raw.name, n)
    write_json(DATA_DIR / "state" / "last_run_normalize.json", {"finished_at": utcnow().isoformat(), "processed": done})
    log.info("normalize: %d raw files processed, %d still being written", done, skipped)
