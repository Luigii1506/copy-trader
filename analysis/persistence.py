"""Does past performance persist? The first experiment of the project (see ADR-001).

Two complementary tests:

Retroactive (available now, biased)
    Uses each tracked wallet's weekly equity history from portfolio(). At every formation date we
    rank wallets on a lookback window and measure their return over the following, non-overlapping
    holding window. Biased because the universe was chosen from today's leaderboard: every wallet
    in it survived until today. Good for building the method, not for conclusions.

Forward (accumulates from 2026-10-06, unbiased)
    Uses daily leaderboard snapshots of ~47k wallets. The "week" window of a snapshot taken 7 days
    after snapshot A covers exactly the 7 days after A, so the signal (A's week ROI) and the outcome
    (B's week ROI) never overlap. Wallets that vanish from the leaderboard are counted, not dropped.

Every test includes a `random` signal: the spread a meaningless ranking produces on the same data.
A real signal has to beat it consistently, not once.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import polars as pl

WEEK = timedelta(days=7)
SIGNALS = ["ret", "sharpe", "low_dd", "pnl_usd", "random"]
QUINTILE = 0.2


# --- weekly returns -------------------------------------------------------------------------------

def period_returns(
    equity: pl.DataFrame,
    pnl_period: str = "perpAllTime",
    capital_period: str = "allTime",
    step_weeks: int = 2,
    min_account: float = 1_000.0,
) -> pl.DataFrame:
    """Perp-trading returns per wallet on a common grid of `step_weeks`-long steps, Sunday 00:00 UTC.

    Return = change in cumulative **perp** PnL / **total** capital at the start of the step plus
    any net deposit during it. This is what a copier of the trader's perp positions, sized
    against the trader's total equity, would earn:
    - perp PnL only (`perpAllTime`): spot holdings and airdrops (HYPE, Dec 2024: +1000% on spot
      balances) are not trading skill and cannot be copied;
    - total capital (`allTime`): many traders keep collateral in spot or unified accounts, so
      the perp sub-account alone understates their capital and overstates leverage;
    - deposits in the denominator: with a point every ~2 weeks their timing is unknown, and
      dividing by the starting value alone would turn "$200k deposited onto $1.5k, then $20k
      earned" into +1,333%. Withdrawals are assumed to happen after the gains they take out,
      so "+$3.1M on $1.7M, then $3.2M withdrawn" stays +182% instead of 27x.
    Steps that start under `min_account`, or where withdrawals leave no meaningful capital, get
    a null return. Returns are floored at -100%.

    Defaults come from the data: portfolio() returns ~70-110 points per wallet regardless of age,
    so long histories are sampled every ~14 days; a weekly grid would leave half the steps empty
    and silently drop exactly the longest-lived wallets.

    equity: deduplicated rows of user, period, time_ms, account_value, pnl.
    Returns: user, end (UTC datetime, end of step), account_value, pnl, dpnl, ret.
    """
    step = timedelta(weeks=step_weeks)
    tolerance = step + timedelta(days=7)
    empty = pl.DataFrame(schema={"user": pl.String, "end": pl.Datetime("ms", "UTC"), "account_value": pl.Float64,
                                 "pnl": pl.Float64, "dpnl": pl.Float64, "ret": pl.Float64})

    def series(period: str, value: str, name: str) -> pl.DataFrame:
        # Hyperliquid prepends a synthetic (0, 0) origin point to each history; it is not an observation.
        return (equity.filter((pl.col("period") == period) & ~((pl.col("account_value") == 0) & (pl.col("pnl") == 0)))
                .with_columns(ts=pl.from_epoch("time_ms", time_unit="ms").dt.cast_time_unit("ms").dt.replace_time_zone("UTC"))
                .select("user", "ts", pl.col(value).alias(name)).sort("user", "ts"))

    capital = series(capital_period, "account_value", "account_value")
    total_pnl = series(capital_period, "pnl", "pnl_total")
    perp_pnl = series(pnl_period, "pnl", "pnl")
    if capital.is_empty() or perp_pnl.is_empty():
        return empty

    # Grid points are only valid inside a wallet's observed range: past its last observation we
    # don't know the value, so that partial step is dropped rather than filled.
    first = capital["ts"].min().date()
    first_sunday = first + timedelta(days=(6 - first.weekday()) % 7)
    ends = pl.datetime_range(
        datetime.combine(first_sunday, datetime.min.time(), tzinfo=timezone.utc),
        capital["ts"].max() + timedelta(days=1),
        interval=f"{step_weeks}w", time_unit="ms", time_zone="UTC", eager=True,
    ).alias("end")
    bounds = capital.group_by("user").agg(lo=pl.col("ts").min(), hi=pl.col("ts").max())
    grid = (bounds.join(ends.to_frame(), how="cross")
            .filter(pl.col("end").is_between(pl.col("lo"), pl.col("hi") + timedelta(days=1)))
            .select("user", "end").sort("user", "end"))

    # Backward as-of: each grid boundary takes the last observation at or before it (never after).
    def snap(frame: pl.DataFrame, src: pl.DataFrame, ts_name: str) -> pl.DataFrame:
        return frame.join_asof(src.rename({"ts": ts_name}), left_on="end", right_on=ts_name, by="user",
                               strategy="backward", tolerance=tolerance, check_sortedness=False)

    snapped = snap(snap(snap(grid, capital, "ts"), total_pnl, "ts_total"), perp_pnl, "ts_perp")
    prev = lambda c: pl.col(c).shift(1).over("user")
    return (
        snapped.with_columns(dpnl=pl.col("pnl") - prev("pnl"),
                             flow=pl.col("account_value") - prev("account_value") - (pl.col("pnl_total") - prev("pnl_total")))
        # Conservative timing of unknown flows: deposits count from the start of the step (they are
        # made before trading them), withdrawals at the end (profits are withdrawn after they are
        # made) and so never shrink the denominator. Both assumptions bias returns *down*.
        .with_columns(capital=prev("account_value") + pl.max_horizontal(pl.col("flow"), pl.lit(0.0)))
        .with_columns(
            # Null when the start is too small, when withdrawals leave no meaningful capital, or when
            # a boundary snapped to the same observation as the previous one (a gap would read as 0%).
            ret=pl.when((prev("account_value") >= min_account) & (pl.col("capital") >= 0.5 * min_account)
                        & (pl.col("ts") != prev("ts")) & (pl.col("ts_perp") != prev("ts_perp")))
            .then(pl.max_horizontal(pl.col("dpnl") / pl.col("capital"), pl.lit(-1.0)))
        )
        .select("user", "end", "account_value", "pnl", "dpnl", "ret")
    )


# --- signals and outcomes -------------------------------------------------------------------------

def _window(returns: pl.DataFrame, start: datetime, end: datetime) -> pl.DataFrame:
    """Steps ending in (start, end]."""
    return returns.filter((pl.col("end") > start) & (pl.col("end") <= end))


def _step(returns: pl.DataFrame) -> timedelta:
    return returns["end"].unique().sort().diff().drop_nulls().min()


def formation_signals(returns: pl.DataFrame, at: datetime, lookback_weeks: int,
                      min_obs: int, seed: int = 0) -> pl.DataFrame:
    """Signals computed only from steps ending on or before `at` (no look-ahead)."""
    w = _window(returns, at - lookback_weeks * WEEK, at).filter(pl.col("ret").is_not_null())
    growth = (1 + pl.col("ret")).cum_prod()
    drawdowns = w.sort("user", "end").with_columns(
        curve=growth.over("user"),
    ).with_columns(dd=pl.col("curve") / pl.col("curve").cum_max().over("user") - 1)
    signals = drawdowns.group_by("user").agg(
        n_obs=pl.len(),
        max_abs_ret=pl.col("ret").abs().max(),  # one step of +/-100% means ruin-level leverage
        ret=(1 + pl.col("ret")).product() - 1,
        sharpe=pl.col("ret").mean() / pl.col("ret").std(),
        low_dd=pl.col("dd").min(),  # max drawdown as a negative number: higher = shallower
        pnl_usd=pl.col("dpnl").sum(),
        consistency=(pl.col("ret") > 0).mean(),  # share of profitable steps
        # Stability: same average return in both halves of the window (0 = identical; more
        # negative = the style's results changed). Groups preserve the chronological sort above.
        stability=-(pl.col("ret").slice(0, pl.len() // 2).mean()
                    - pl.col("ret").slice(pl.len() // 2, pl.len() - pl.len() // 2).mean()).abs(),
    ).filter(pl.col("n_obs") >= min_obs)
    return signals.sort("user").with_columns(
        random=pl.Series(values=_uniform(len(signals), seed), dtype=pl.Float64)
    )


def _uniform(n: int, seed: int) -> list[float]:
    import random
    rng = random.Random(seed)
    return [rng.random() for _ in range(n)]


def forward_outcome(returns: pl.DataFrame, at: datetime, hold_weeks: int, min_obs: int) -> pl.DataFrame:
    w = _window(returns, at, at + hold_weeks * WEEK).filter(pl.col("ret").is_not_null())
    return (
        w.group_by("user")
        .agg(fwd_obs=pl.len(), fwd_ret=(1 + pl.col("ret")).product() - 1)
        .filter(pl.col("fwd_obs") >= min_obs)
    )


# --- persistence statistics -----------------------------------------------------------------------

def rank_stats(df: pl.DataFrame, signal: str, outcome: str) -> dict[str, float]:
    """How well `signal` ranks `outcome` in one cross-section.

    ic:          Spearman rank correlation (0 = no information, 1 = perfect ordering)
    top/bottom:  median outcome of the top/bottom quintile by signal; all: median of everyone.
                 Medians, not means: trader returns are heavy-tailed and a few small accounts
                 with +/-90% outcomes would otherwise dominate the comparison.
    top_hit:     share of the top quintile whose outcome beats the cross-sectional median
    """
    d = df.select(signal, outcome).drop_nulls().filter(pl.col(signal).is_finite() & pl.col(outcome).is_finite())
    n = d.height
    if n < 10:
        return {"n": n}
    d = d.sort(signal, descending=True)
    k = max(1, int(n * QUINTILE))
    median = d[outcome].median()
    return {
        "n": n,
        "ic": d.select(pl.corr(signal, outcome, method="spearman")).item(),
        "top": d.head(k)[outcome].median(),
        "bottom": d.tail(k)[outcome].median(),
        "all": median,
        "top_hit": (d.head(k)[outcome] > median).mean(),
    }


def retroactive_persistence(
    returns: pl.DataFrame,
    lookback_weeks: int = 12,
    hold_weeks: int = 4,
    min_obs_frac: float = 0.75,
    users: pl.Series | None = None,
) -> pl.DataFrame:
    """One row per (formation date, signal). Formation dates step by `hold_weeks` so holding
    windows never overlap and the rows are (closer to) independent observations.

    `min_obs_frac` is the share of grid steps a wallet must have in each window."""
    if users is not None:
        returns = returns.filter(pl.col("user").is_in(users.implode()))
    if returns.is_empty():
        return pl.DataFrame()
    steps_per_week = WEEK / _step(returns)
    min_lookback = max(2, int(lookback_weeks * steps_per_week * min_obs_frac))
    min_hold = max(1, int(hold_weeks * steps_per_week * min_obs_frac))
    ends = returns["end"].unique().sort()
    first = ends.min() + lookback_weeks * WEEK
    last = ends.max() - hold_weeks * WEEK
    rows = []
    at, i = first, 0
    while at <= last:
        sig = formation_signals(returns, at, lookback_weeks, min_lookback, seed=i)
        out = forward_outcome(returns, at, hold_weeks, min_hold)
        joined = sig.join(out, on="user")
        for s in SIGNALS:
            rows.append({"formation": at, "signal": s, **rank_stats(joined, s, "fwd_ret")})
        at += hold_weeks * WEEK
        i += 1
    return pl.DataFrame(rows)


def leaderboard_persistence(
    leaderboard: pl.DataFrame,
    horizon_days: int = 7,
    period: str = "week",
    min_account: float = 10_000.0,
    exclude: pl.Series | None = None,
    slack: timedelta = timedelta(hours=12),
) -> pl.DataFrame:
    """Forward test on leaderboard snapshots: signal = `{period}_roi` at snapshot A, outcome = the
    same field at the snapshot `horizon_days` later (whose window covers exactly the days after A).

    Wallets present at A but missing at B are reported in `dropped` - excluding them silently is
    survivorship bias. Returns one row per (A, signal); empty until two snapshots are far enough apart.
    """
    col = f"{period}_roi"
    # Date each snapshot by when Hyperliquid produced it (data_as_of), falling back to fetch time for
    # early snapshots taken before we recorded it. The same version fetched twice counts once.
    as_of = pl.col("data_as_of") if "data_as_of" in leaderboard.columns else pl.lit(None, pl.String)
    lb = leaderboard.with_columns(
        snap=pl.coalesce(as_of, pl.col("snapshot_at")).str.to_datetime(time_zone="UTC")
    ).unique(subset=["snap", "user"], keep="first")
    if exclude is not None:
        lb = lb.filter(~pl.col("user").is_in(exclude.implode()))
    snaps = lb["snap"].unique().sort().to_list()
    horizon = timedelta(days=horizon_days)
    rows = []
    for i, a in enumerate(snaps):
        matches = [b for b in snaps[i + 1:] if abs((b - a) - horizon) <= slack]
        if not matches:
            continue
        b = min(matches, key=lambda s: abs((s - a) - horizon))
        sa = lb.filter((pl.col("snap") == a) & (pl.col("account_value") >= min_account)).select("user", col)
        sb = lb.filter(pl.col("snap") == b).select("user", pl.col(col).alias("outcome"))
        joined = sa.join(sb, on="user", how="left")
        joined = joined.sort("user").with_columns(
            random=pl.Series(values=_uniform(joined.height, i), dtype=pl.Float64)
        )
        dropped = joined["outcome"].null_count()
        for s in (col, "random"):
            rows.append({"snapshot_a": a, "snapshot_b": b, "signal": s, "dropped": dropped,
                         **rank_stats(joined, s, "outcome")})
    return pl.DataFrame(rows)


def summarize(table: pl.DataFrame) -> pl.DataFrame:
    """Aggregate per signal across formation dates.

    ic_tstat = mean IC / (std IC / sqrt(periods)). |t| < 2 is indistinguishable from noise.
    ic_positive = share of periods with IC > 0; persistence should show up most of the time.
    """
    if table.is_empty() or "ic" not in table.columns:
        return pl.DataFrame()
    return (
        table.filter(pl.col("ic").is_not_null())
        .group_by("signal")
        .agg(
            periods=pl.len(),
            wallets_avg=pl.col("n").mean().round(0),
            mean_ic=pl.col("ic").mean(),
            ic_tstat=pl.col("ic").mean() / (pl.col("ic").std() / pl.len().sqrt()),
            ic_positive=(pl.col("ic") > 0).mean(),
            top_minus_all=(pl.col("top") - pl.col("all")).mean(),
            top_minus_bottom=(pl.col("top") - pl.col("bottom")).mean(),
            top_hit=pl.col("top_hit").mean(),
        )
        .sort("mean_ic", descending=True)
    )
