"""Raw storage. Every API response is saved untouched inside an envelope so metrics can be recomputed later.

Layout:
    <DATA_DIR>/raw/hyperliquid/<dataset>/date=YYYY-MM-DD/<run_id>.jsonl.gz
    <DATA_DIR>/processed/...      Parquet tables built by collector.normalize
    <DATA_DIR>/state/...          collector cursors and locks
    <DATA_DIR>/universe/...       tracked wallets (append-only)
"""

from __future__ import annotations

import gzip
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Outside ~/Documents on purpose: macOS blocks launchd jobs from reading it without Full Disk Access.
DATA_DIR = Path(os.environ.get("COPY_TRADER_DATA", Path.home() / "data" / "copy-trader"))
PLATFORM = "hyperliquid"


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def run_id(ts: datetime) -> str:
    return ts.strftime("%Y%m%dT%H%M%SZ")


def envelope(dataset: str, request: dict[str, Any], payload: Any, fetched_at: datetime) -> dict[str, Any]:
    return {
        "platform": PLATFORM,
        "dataset": dataset,
        "fetched_at": fetched_at.isoformat(),
        "request": request,
        "payload": payload,
    }


class RawWriter:
    """Appends one JSON record per line. Each append is its own gzip member, so a crash never corrupts earlier records."""

    def __init__(self, dataset: str, started_at: datetime):
        self.path = (
            DATA_DIR / "raw" / PLATFORM / dataset / f"date={started_at:%Y-%m-%d}" / f"{run_id(started_at)}.jsonl.gz"
        )
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def write(self, record: dict[str, Any]) -> None:
        with gzip.open(self.path, "at", encoding="utf-8") as fh:
            fh.write(json.dumps(record, separators=(",", ":")) + "\n")


def read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text())


def write_json(path: Path, data: Any) -> None:
    """Atomic write so an interrupted run never leaves a half-written state file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=1, sort_keys=True))
    tmp.replace(path)
