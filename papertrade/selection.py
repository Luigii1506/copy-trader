"""Which traders each strategy copies.

Signals reuse analysis.persistence so paper trading and the persistence study rank traders the
same way. Pool: tracked universe + census, minus vaults, minus accounts under MIN_TRADER_EQUITY,
minus traders too active to copy with a 60 s poll (when their fills are known).
"""

from __future__ import annotations

import logging
import random
from datetime import datetime, timedelta

import polars as pl

from analysis.backtest import MAX_STEP_ABS_RET
from analysis.behavior import behavior_features
from analysis.persistence import formation_signals, period_returns
from analysis.score import V2_MIN_STEP_VOL, behavior_exclusions, score_from_signals
from collector.storage import DATA_DIR, PLATFORM

from .config import LOOKBACK_WEEKS, MAX_FILLS_PER_DAY, MIN_TRADER_EQUITY, Strategy

PROCESSED = DATA_DIR / "processed" / PLATFORM
log = logging.getLogger(__name__)


def _read(table: str) -> pl.DataFrame | None:
    files = sorted((PROCESSED / table).glob("date=*/*.parquet"))
    if not files:
        return None
    return pl.concat([pl.read_parquet(f) for f in files], how="diagonal_relaxed")


def candidate_signals(now: datetime) -> pl.DataFrame:
    """One row per eligible trader with every strategy signal (higher = better)."""
    # Pool: tracked universe plus every trader the census has reached so far.
    tables = [t for t in (_read("equity_history"), _read("equity_census")) if t is not None]
    if not tables:
        raise RuntimeError("no equity history yet; run the wallets and normalize jobs first")
    equity = pl.concat(tables, how="diagonal_relaxed").unique(subset=["user", "period", "time_ms"])

    returns = period_returns(equity)
    last_end = returns["end"].max()
    signals = formation_signals(returns, last_end, LOOKBACK_WEEKS, min_obs=4).drop("random")

    # Current size: latest total account value per trader.
    latest = (equity.filter(pl.col("period") == "allTime").sort("time_ms")
              .group_by("user").agg(account_value=pl.col("account_value").last()))
    pool = signals.join(latest, on="user").filter(
        (pl.col("account_value") >= MIN_TRADER_EQUITY)
        # Same rule as the backtest: a +/-100% step means leverage a 5x-capped book cannot mirror.
        & (pl.col("max_abs_ret") <= MAX_STEP_ABS_RET))

    vaults = _read("vaults")
    if vaults is not None:
        pool = pool.filter(~pl.col("user").is_in(vaults["vault_address"].unique().implode()))

    fills = _read("fills")
    if fills is not None:
        # Too active to follow with a 60 s poll, or not trading at all (nothing to copy).
        # Traders whose fills we haven't downloaded yet are kept: unknown is not inactive.
        since = int((now - timedelta(days=30)).timestamp() * 1000)
        activity = (fills.unique(subset=["user", "tid", "oid"]).group_by("user").agg(
            fills_per_day=(pl.col("time_ms") >= since).sum() / 30,
            last_fill_ms=pl.col("time_ms").max(),
        ))
        pool = pool.join(activity, on="user", how="left").filter(
            pl.col("last_fill_ms").is_null()
            | ((pl.col("fills_per_day") <= MAX_FILLS_PER_DAY) & (pl.col("last_fill_ms") >= since)))

    # TraderScore: behavior penalties where fills exist (universe + followed); neutral elsewhere.
    behavior = None
    if fills is not None:
        try:
            behavior = behavior_features(fills, equity, now)
        except Exception:
            log.exception("behavior features failed; scoring without penalties")
    pool = behavior_exclusions(score_from_signals(pool, behavior), behavior)

    board = _read("leaderboard")
    if board is not None:
        stamp = "data_as_of" if "data_as_of" in board.columns else "snapshot_at"
        newest = board.with_columns(t=pl.coalesce(pl.col(stamp), pl.col("snapshot_at"))).filter(
            pl.col("t") == pl.col("t").max())
        pool = pool.join(newest.select("user", leaderboard_month_pnl="month_pnl"), on="user", how="left")
    return pool


def select(strategy: Strategy, candidates: pl.DataFrame, now: datetime) -> list[tuple[str, float]]:
    """Top `n_traders` by the strategy's signal, as (trader, signal value)."""
    if strategy.signal == "random":
        users = sorted(candidates["user"].to_list())
        rng = random.Random(f"{strategy.name}:{now:%Y-%m-%d}")
        return [(u, 0.0) for u in rng.sample(users, min(strategy.n_traders, len(users)))]
    if strategy.signal == "sharpe_v2":
        # v2 candidate (inactive until ADR-003 ends): sharpe ranking, behavior only excludes.
        candidates = candidates.filter(~pl.col("behavior_excluded") & (pl.col("vol") >= V2_MIN_STEP_VOL))
        ranked = (candidates.filter(pl.col("sharpe").is_finite())
                  .sort("sharpe", descending=True).head(strategy.n_traders))
        return list(zip(ranked["user"].to_list(), ranked["sharpe"].to_list()))
    if strategy.signal == "low_dd":
        # Shallow drawdowns only count with a positive return: a flat account has no drawdown either.
        candidates = candidates.filter(pl.col("ret") > 0)
    ranked = (candidates.filter(pl.col(strategy.signal).is_not_null() & pl.col(strategy.signal).is_finite())
              .sort(strategy.signal, descending=True).head(strategy.n_traders))
    return list(zip(ranked["user"].to_list(), ranked[strategy.signal].to_list()))
