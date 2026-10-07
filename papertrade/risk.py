"""Portfolio risk for copying traders (proyect.md sections 27-28).

Three pieces, all pure except weights_for (which loads processed data):

- correlation_groups: traders whose recent daily PnL moves together. Ten books long BTC at 10x
  are one bet, not ten; grouping makes that measurable.
- allocate: equal-weight allocation under two caps: MAX_TRADER_ALLOCATION per trader and
  MAX_CORRELATED_EXPOSURE per correlated group. What the caps remove stays in cash on purpose:
  when few traders are eligible or many are correlated, the right response is holding cash,
  not concentrating harder. Score-proportional sizing arrives with TraderScore.
- the daily-loss pause lives in the engine: when a strategy loses more than DAILY_LOSS_PAUSE
  in a UTC day, it stops adding exposure until the next day (closes are always allowed).
"""

from __future__ import annotations

import logging

import polars as pl

from .config import (
    CORRELATION_MIN_OVERLAP,
    CORRELATION_THRESHOLD,
    MAX_CORRELATED_EXPOSURE,
    MAX_TRADER_ALLOCATION,
)
from .selection import _read

log = logging.getLogger(__name__)


def daily_pnl_returns(equity: pl.DataFrame, users: list[str]) -> pl.DataFrame:
    """Daily PnL returns per user from the 'month' portfolio period (~12 h sampling).

    Caveat: the month PnL series is a rolling window, so a diff also picks up PnL rolling out of
    the window. Good enough for correlation grouping; never use it to measure performance."""
    m = (equity.filter((pl.col("period") == "month") & pl.col("user").is_in(pl.Series(users).implode()))
         .with_columns(date=pl.from_epoch("time_ms", time_unit="ms").dt.date())
         .sort("time_ms").group_by("user", "date")
         .agg(av=pl.col("account_value").last(), pnl=pl.col("pnl").last()))
    m = m.sort("user", "date").with_columns(
        dpnl=pl.col("pnl").diff().over("user"), prev=pl.col("av").shift(1).over("user"))
    return (m.filter(pl.col("prev") > 100)
            .with_columns(ret=pl.col("dpnl") / pl.col("prev"))
            .drop_nulls("ret").select("user", "date", "ret"))


def correlation_groups(daily: pl.DataFrame, users: list[str],
                       threshold: float = CORRELATION_THRESHOLD,
                       min_overlap: int = CORRELATION_MIN_OVERLAP) -> list[list[str]]:
    """Union-find over pairs whose daily returns correlate >= threshold on enough common days."""
    users = sorted(users)
    parent = {u: u for u in users}

    def find(u: str) -> str:
        while parent[u] != u:
            parent[u] = parent[parent[u]]
            u = parent[u]
        return u

    series = {u: daily.filter(pl.col("user") == u).select("date", "ret") for u in users}
    for i, a in enumerate(users):
        for b in users[i + 1:]:
            if find(a) == find(b):
                continue
            joined = series[a].join(series[b].rename({"ret": "ret_b"}), on="date")
            if joined.height < min_overlap:
                continue
            c = joined.select(pl.corr("ret", "ret_b")).item()
            if c is not None and c == c and c >= threshold:
                parent[find(b)] = find(a)

    groups: dict[str, list[str]] = {}
    for u in users:
        groups.setdefault(find(u), []).append(u)
    return [sorted(g) for g in groups.values()]


def allocate(users: list[str], groups: list[list[str]],
             max_trader: float = MAX_TRADER_ALLOCATION,
             max_group: float = MAX_CORRELATED_EXPOSURE) -> dict[str, float]:
    """Equal base weights under the per-trader and per-group caps; the remainder is cash."""
    if not users:
        return {}
    weights = {u: min(1 / len(users), max_trader) for u in users}
    for group in groups:
        members = [u for u in group if u in weights]
        total = sum(weights[u] for u in members)
        if total > max_group:
            factor = max_group / total
            for u in members:
                weights[u] *= factor
    return weights


def weights_for(users: list[str]) -> tuple[dict[str, float], list[list[str]]]:
    """Allocation weights for a set of chosen traders, plus the correlated groups that were capped.
    Falls back to equal capped weights when equity data is missing or the grouping fails."""
    users = sorted(users)
    equal = {u: min(1 / len(users), MAX_TRADER_ALLOCATION) for u in users} if users else {}
    try:
        tables = [t for t in (_read("equity_history"), _read("equity_census")) if t is not None]
        if not tables:
            return equal, []
        equity = pl.concat(tables, how="diagonal_relaxed").unique(subset=["user", "period", "time_ms"])
        groups = correlation_groups(daily_pnl_returns(equity, users), users)
    except Exception:
        log.exception("correlation grouping failed; using equal weights")
        return equal, []
    return allocate(users, groups), [g for g in groups if len(g) > 1]
