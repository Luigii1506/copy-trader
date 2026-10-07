"""Behavior watch: when to stop copying a trader (proyect.md sections 18, 28, 32).

Every WATCH_INTERVAL the engine evaluates the traders it follows with analysis.behavior over
their recent fills and flags the ones whose behavior crossed a limit. A flagged trader's book is
closed and the trader is not re-selected while the flag is fresh.

Thresholds live in papertrade.config and are starting points, not calibrated values: the plan
asks for them to be tested, and the flags table records every trigger so they can be.
"""

from __future__ import annotations

from datetime import datetime

import polars as pl

from analysis.behavior import behavior_features

from .config import EXIT_RULES, WATCH_WINDOW_DAYS
from .selection import _read


def load_inputs(traders: set[str]) -> tuple[pl.DataFrame | None, pl.DataFrame | None]:
    fills = _read("fills")
    tables = [t for t in (_read("equity_history"), _read("equity_census")) if t is not None]
    equity = pl.concat(tables, how="diagonal_relaxed").unique(subset=["user", "period", "time_ms"]) if tables else None
    if fills is not None:
        fills = fills.filter(pl.col("user").is_in(pl.Series(sorted(traders)).implode()))
    return fills, equity


def evaluate(features: pl.DataFrame) -> list[dict]:
    """Apply EXIT_RULES to a behavior-features table. One dict per (trader, rule) hit;
    `actionable` is False when the trader has fewer closed trades than the rule requires."""
    flags = []
    for row in features.to_dicts():
        n_trades = row.get("n_trades") or 0
        for rule, column, op, limit, min_trades in EXIT_RULES:
            value = row.get(column)
            if value is None:
                continue
            hit = value > limit if op == ">" else value < limit
            if hit:
                flags.append({"trader": row["user"], "rule": rule, "column": column, "value": float(value),
                              "limit": limit, "n_trades": int(n_trades), "actionable": n_trades >= min_trades})
    return flags


def run(traders: set[str], now: datetime) -> list[dict]:
    if not traders:
        return []
    fills, equity = load_inputs(traders)
    if fills is None or fills.is_empty() or equity is None:
        return []
    features = behavior_features(fills, equity, now, window_days=WATCH_WINDOW_DAYS)
    return evaluate(features)
