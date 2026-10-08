"""BTC beta: is a trader's performance skill or BTC exposure in disguise?

beta  = cov(trader step return, BTC step return) / var(BTC step return)
alpha = mean(trader) - beta * mean(BTC), per step

On the same 2-week grid as analysis.persistence, so a beta can sit next to the signals that
selected the trader. A top-Sharpe trader with beta ~1 and alpha ~0 is a leveraged BTC holder:
copying them adds fees and lag to something buy & hold gives for free.
"""

from __future__ import annotations

import polars as pl


def btc_step_returns(candles: pl.DataFrame, ends: pl.Series) -> pl.DataFrame:
    """BTC return over each grid step, from daily closes (as-of the step end, backward)."""
    btc = (candles.filter(pl.col("coin") == "BTC").sort("snapshot_at")
           .unique(subset=["time_ms"], keep="last")
           .with_columns(ts=pl.from_epoch("time_ms", time_unit="ms").dt.cast_time_unit("ms")
                         .dt.replace_time_zone("UTC"))
           .select("ts", "close").sort("ts"))
    grid = pl.DataFrame({"end": ends.unique().sort()}).sort("end")
    snapped = grid.join_asof(btc, left_on="end", right_on="ts", strategy="backward")
    return snapped.with_columns(btc_ret=pl.col("close") / pl.col("close").shift(1) - 1).select("end", "btc_ret")


def trader_beta(returns: pl.DataFrame, candles: pl.DataFrame, min_obs: int = 6) -> pl.DataFrame:
    """Per trader: beta, alpha per step, correlation with BTC, and observations used."""
    btc = btc_step_returns(candles, returns["end"])
    joined = returns.join(btc, on="end").drop_nulls(["ret", "btc_ret"])
    return (joined.group_by("user").agg(
        n_beta_obs=pl.len(),
        beta=pl.cov("ret", "btc_ret") / pl.col("btc_ret").var(),
        btc_corr=pl.corr("ret", "btc_ret"),
        mean_ret=pl.col("ret").mean(),
        mean_btc=pl.col("btc_ret").mean(),
    ).filter(pl.col("n_beta_obs") >= min_obs)
     .with_columns(alpha=pl.col("mean_ret") - pl.col("beta") * pl.col("mean_btc"))
     .drop("mean_ret", "mean_btc"))
