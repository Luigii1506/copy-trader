"""Copy-trading backtest: what would copying the top-N traders by some rule have returned?

Built on the same grid and signals as analysis.persistence, so a rule evaluated here is the same
rule the paper-trading engine would run. At each formation date the rule sees only steps that
ended on or before that date; the portfolio then holds the selected traders for `hold_weeks`
and the realized return is the equal-weighted compound return of their equity curves.

Why this is a *lower-resolution* proxy for copying, stated once:
- A copier earns the trader's return minus the frictions of mirroring: our own taker fees
  (traders with volume discounts pay less than we would), slippage, and the lag between their
  fill and ours. `friction_per_step` is a flat haircut for that, to be calibrated against the
  paper-trading tracking error. `rebalance_cost` charges a full close-and-reopen at each
  formation date (conservative: continuing traders are not really closed).
- Traders that disappear during the holding window (account closed, no equity data) contribute
  0% for the missing steps and are counted in `n_missing`. A blow-up is NOT missing: the equity
  curve records it as a large negative return.
"""

from __future__ import annotations

import math
import random
from collections.abc import Callable
from datetime import datetime

import polars as pl

from .persistence import WEEK, _step, _window, formation_signals

Selector = Callable[[pl.DataFrame, datetime, int], list[str]]

MIN_ACCOUNT = 10_000.0
# 2 × (taker fee 0.045% + ~0.02% impact) for a full turnover of the book
REBALANCE_COST = 0.0013
# A trader with a single +/-100% step in the lookback runs leverage a 5x-capped copier cannot
# mirror; their past return is not what we would have earned.
MAX_STEP_ABS_RET = 1.0


# --- selection rules --------------------------------------------------------------------------

def top_by(signal: str, n: int, require_positive_return: bool = False) -> Selector:
    def pick(signals: pl.DataFrame, at: datetime, seed: int) -> list[str]:
        s = signals.filter(pl.col(signal).is_not_null() & pl.col(signal).is_finite())
        if require_positive_return:
            s = s.filter(pl.col("ret") > 0)
        return s.sort(signal, descending=True).head(n)["user"].to_list()
    return pick


def random_pick(n: int) -> Selector:
    def pick(signals: pl.DataFrame, at: datetime, seed: int) -> list[str]:
        users = sorted(signals["user"].to_list())
        return random.Random(seed).sample(users, min(n, len(users)))
    return pick


def everyone() -> Selector:
    """The whole eligible pool, equal-weighted: 'the average trader'."""
    return lambda signals, at, seed: signals["user"].to_list()


# --- backtest ---------------------------------------------------------------------------------

def _eligible_signals(returns: pl.DataFrame, at: datetime, lookback_weeks: int, min_obs: int,
                      min_account: float, max_step_abs_ret: float, seed: int) -> pl.DataFrame:
    signals = formation_signals(returns, at, lookback_weeks, min_obs, seed=seed)
    # Size at formation: last known account value on or before `at`.
    size = (returns.filter(pl.col("end") <= at).sort("end").group_by("user")
            .agg(account_value=pl.col("account_value").last()))
    return (signals.join(size, on="user")
            .filter((pl.col("account_value") >= min_account) & (pl.col("max_abs_ret") <= max_step_abs_ret)))


def copy_backtest(
    returns: pl.DataFrame,
    selector: Selector,
    lookback_weeks: int = 12,
    hold_weeks: int = 4,
    min_obs_frac: float = 0.75,
    min_account: float = MIN_ACCOUNT,
    max_step_abs_ret: float = MAX_STEP_ABS_RET,
    rebalance_cost: float = REBALANCE_COST,
    friction_per_step: float = 0.0,
    exclude: pl.Series | None = None,
    seed: int = 0,
) -> pl.DataFrame:
    """One row per holding period: formation, end, n_selected, n_missing, gross_ret, net_ret, equity."""
    if exclude is not None:
        returns = returns.filter(~pl.col("user").is_in(exclude.implode()))
    if returns.is_empty():
        return pl.DataFrame()
    step = _step(returns)
    steps_per_week = WEEK / step
    min_lookback = max(2, int(lookback_weeks * steps_per_week * min_obs_frac))
    ends = returns["end"].unique().sort()
    first, last = ends.min() + lookback_weeks * WEEK, ends.max() - hold_weeks * WEEK
    rows, equity, at, i = [], 1.0, first, 0
    while at <= last:
        signals = _eligible_signals(returns, at, lookback_weeks, min_lookback, min_account, max_step_abs_ret,
                                    seed * 100_003 + i)
        chosen = selector(signals, at, seed * 100_003 + i) if signals.height else []
        end = at + hold_weeks * WEEK
        if chosen:
            held = _window(returns, at, end).filter(pl.col("user").is_in(pl.Series(chosen).implode()))
            per_trader = (held.group_by("user")
                          .agg(ret=(1 + pl.col("ret").fill_null(0.0)).product() - 1, steps=pl.col("ret").is_not_null().sum()))
            present = set(per_trader["user"].to_list())
            n_missing = sum(u not in present for u in chosen) + int((per_trader["steps"] == 0).sum())
            gross = per_trader["ret"].sum() / len(chosen)  # absent traders contribute 0
        else:
            gross, n_missing = 0.0, 0
        n_steps = int(hold_weeks * steps_per_week)
        net = (1 + gross) * (1 - rebalance_cost) * (1 - friction_per_step) ** n_steps - 1 if chosen else 0.0
        equity *= 1 + net
        rows.append({"formation": at, "end": end, "n_selected": len(chosen), "n_missing": n_missing,
                     "gross_ret": gross, "net_ret": net, "equity": equity})
        at, i = end, i + 1
    return pl.DataFrame(rows)


def buy_and_hold(prices: pl.DataFrame, periods: pl.DataFrame) -> pl.DataFrame:
    """Same period table for holding an asset. prices: time_ms, close (daily)."""
    px = prices.select(ts=pl.from_epoch("time_ms", time_unit="ms").dt.cast_time_unit("ms").dt.replace_time_zone("UTC"),
                       close=pl.col("close")).sort("ts")
    rows, equity = [], 1.0
    for r in periods.select("formation", "end").iter_rows(named=True):
        p0 = px.filter(pl.col("ts") <= r["formation"]).tail(1)
        p1 = px.filter(pl.col("ts") <= r["end"]).tail(1)
        ret = (p1["close"][0] / p0["close"][0] - 1) if p0.height and p1.height else 0.0
        equity *= 1 + ret
        rows.append({"formation": r["formation"], "end": r["end"], "n_selected": 1, "n_missing": 0,
                     "gross_ret": ret, "net_ret": ret, "equity": equity})
    return pl.DataFrame(rows)


# --- metrics ----------------------------------------------------------------------------------

def summarize_backtest(table: pl.DataFrame, hold_weeks: int = 4) -> dict[str, float]:
    """Standard performance metrics (proyect.md section 41) from the per-period table."""
    if table.is_empty():
        return {}
    r = table["net_ret"]
    periods_per_year = 52 / hold_weeks
    years = table.height / periods_per_year
    equity = table["equity"]
    drawdown = (equity / equity.cum_max() - 1).min()
    mean, std = r.mean(), r.std() if table.height > 1 else None
    downside = r.map_elements(lambda x: min(x, 0.0), return_dtype=pl.Float64)
    downside_std = math.sqrt((downside ** 2).mean()) if table.height > 1 else None
    total = equity[-1] - 1
    cagr = (equity[-1]) ** (1 / years) - 1 if years > 0 and equity[-1] > 0 else -1.0
    wins = r.filter(r > 0).sum()
    losses = -r.filter(r < 0).sum()
    return {
        "periods": table.height,
        "total_return": total,
        "cagr": cagr,
        "max_drawdown": drawdown,
        "sharpe": mean / std * math.sqrt(periods_per_year) if std else None,
        "sortino": mean / downside_std * math.sqrt(periods_per_year) if downside_std else None,
        "calmar": cagr / -drawdown if drawdown < 0 else None,
        "hit_rate": (r > 0).mean(),
        "profit_factor": wins / losses if losses > 0 else None,
        "worst_period": r.min(),
        "missing_share": table["n_missing"].sum() / max(table["n_selected"].sum(), 1),
    }


def compare(strategies: dict[str, pl.DataFrame], hold_weeks: int = 4) -> pl.DataFrame:
    rows = [{"strategy": name, **summarize_backtest(t, hold_weeks)} for name, t in strategies.items()]
    return pl.DataFrame(rows).sort("sharpe", descending=True, nulls_last=True)


def random_baseline(returns: pl.DataFrame, n: int, seeds: int = 20, **kwargs) -> pl.DataFrame:
    """Distribution of outcomes for picking traders at random: the bar every rule must clear."""
    rows = []
    for seed in range(seeds):
        table = copy_backtest(returns, random_pick(n), seed=seed, **kwargs)
        rows.append({"seed": seed, **summarize_backtest(table, kwargs.get("hold_weeks", 4))})
    return pl.DataFrame(rows)
