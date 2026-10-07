"""Behavioral features from fills (proyect.md section 18).

Fills are the ground truth of what a trader did: every partial entry, add, reduce, flip and
liquidation. From them we rebuild round-trip trades and measure *how* a trader trades, which the
equity curve cannot show: averaging down, martingale sizing, leverage, concentration, overtrading,
dependence on a single trade, and recent changes of style.

Pipeline:
    perp_fills(fills)                       dedup, drop spot, signed sizes, flips split in two legs
    round_trips(perp)                       one row per trade (flat -> position -> flat)
    gross_exposure(perp, equity)            gross notional / equity at every fill (leverage path)
    behavior_features(fills, equity, now)   one row per trader over a lookback window

Caveats, stated once here:
- Only the 10,000 most recent fills per wallet are available. `window_complete` is False when a
  trader's oldest fill lies inside the window: their early history was cut off, and activity-based
  features for them are lower bounds.
- Prices of other coins between fills are unknown; gross exposure values each position at its own
  last fill price. Good enough for leverage *behavior* (does the trader run 2x or 20x), not for
  exact mark-to-market.
- Equity between portfolio() samples is unknown; see gross_exposure for how gaps are handled.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import polars as pl

HOUR_MS = 3_600_000
DAY_MS = 24 * HOUR_MS

SPOT_DIRS = {"Buy", "Sell", "Spot Dust Conversion"}
FLIP_DIRS = {"Long > Short", "Short > Long"}


# --- 1. clean fills ---------------------------------------------------------------------------

def perp_fills(fills: pl.DataFrame) -> pl.DataFrame:
    """Deduplicated perp fills with signed sizes, flips split into a closing and an opening leg.

    Output columns: user, coin, time_ms, px, signed_sz, start_position, position_after,
    closed_pnl, fee, liquidated, leg ("" | "close" | "open").
    """
    f = (
        fills.unique(subset=["user", "tid", "oid"])
        .with_columns(pl.col("sz", "px", "start_position", "closed_pnl", "fee").cast(pl.Float64))
        .filter(~pl.col("dir").is_in(SPOT_DIRS) & ~pl.col("coin").str.contains("/") & ~pl.col("coin").str.starts_with("@"))
        .with_columns(
            signed_sz=pl.when(pl.col("side") == "B").then(pl.col("sz")).otherwise(-pl.col("sz")),
            liquidated=pl.col("liquidated").fill_null(False) if "liquidated" in fills.columns else pl.lit(False),
        )
        .with_columns(position_after=pl.col("start_position") + pl.col("signed_sz"))
    )
    base = ["user", "coin", "time_ms", "px", "signed_sz", "start_position", "position_after",
            "closed_pnl", "fee", "liquidated", "tid"]
    plain = f.filter(~pl.col("dir").is_in(FLIP_DIRS)).select(*base).with_columns(leg=pl.lit(""))
    flips = f.filter(pl.col("dir").is_in(FLIP_DIRS))
    if flips.is_empty():
        return plain.sort("user", "coin", "time_ms", "tid")
    # A flip closes the whole old position and opens the remainder on the other side. The fee is
    # split by size; all realized PnL belongs to the closing leg.
    closing = flips.with_columns(
        signed_sz=-pl.col("start_position"),
        fee=pl.col("fee") * (pl.col("start_position").abs() / pl.col("signed_sz").abs()),
        leg=pl.lit("close"),
    ).with_columns(position_after=pl.lit(0.0)).select(*base, "leg")
    opening = flips.with_columns(
        signed_sz=pl.col("position_after"),
        start_position=pl.lit(0.0),
        closed_pnl=pl.lit(0.0),
        fee=pl.col("fee") * (pl.col("position_after").abs() / pl.col("signed_sz").abs()),
        liquidated=pl.lit(False),
        leg=pl.lit("open"),
    ).select(*base, "leg")
    return pl.concat([plain, closing, opening]).sort("user", "coin", "time_ms", "tid", "leg")


# --- 2. round trips ---------------------------------------------------------------------------

def round_trips(perp: pl.DataFrame) -> pl.DataFrame:
    """One row per trade: from flat to flat (or to the end of the data, then closed_ms is null).

    Tracks the average entry price along the way, so each add is labeled as averaging down
    (adding at a worse price than the running average) or pyramiding (adding at a better one).
    """
    rows = []
    for (user, coin), g in perp.sort("user", "coin", "time_ms", "tid", "leg").group_by(["user", "coin"], maintain_order=True):
        trade = None
        for r in g.iter_rows(named=True):
            start, after, signed, px = r["start_position"], r["position_after"], r["signed_sz"], r["px"]
            if trade is None or start == 0:
                if trade is not None:
                    rows.append(trade)
                trade = {
                    "user": user, "coin": coin, "opened_ms": r["time_ms"], "closed_ms": None,
                    "side": "long" if signed > 0 else "short", "n_fills": 0, "n_adds": 0, "n_adds_losing": 0,
                    "initial_notional": abs(signed) * px, "max_notional": 0.0, "avg_entry": px,
                    "realized_pnl": 0.0, "fees": 0.0, "liquidated": False, "_abs_pos": 0.0,
                }
            trade["n_fills"] += 1
            trade["fees"] += r["fee"]
            trade["realized_pnl"] += r["closed_pnl"]
            trade["liquidated"] |= bool(r["liquidated"])
            increasing = abs(after) > abs(start)
            if increasing and start != 0:
                trade["n_adds"] += 1
                worse = px < trade["avg_entry"] if trade["side"] == "long" else px > trade["avg_entry"]
                trade["n_adds_losing"] += int(worse)
            if increasing:
                trade["avg_entry"] = (trade["avg_entry"] * abs(start) + px * abs(signed)) / abs(after)
            trade["max_notional"] = max(trade["max_notional"], abs(after) * px, abs(start) * px)
            if after == 0:
                trade["closed_ms"] = r["time_ms"]
                rows.append(trade)
                trade = None
        if trade is not None:
            rows.append(trade)
    schema = {"user": pl.String, "coin": pl.String, "opened_ms": pl.Int64, "closed_ms": pl.Int64, "side": pl.String,
              "n_fills": pl.Int64, "n_adds": pl.Int64, "n_adds_losing": pl.Int64, "initial_notional": pl.Float64,
              "max_notional": pl.Float64, "avg_entry": pl.Float64, "realized_pnl": pl.Float64, "fees": pl.Float64,
              "liquidated": pl.Boolean, "_abs_pos": pl.Float64}
    trades = pl.DataFrame(rows, schema=schema).drop("_abs_pos")
    return trades.with_columns(
        pnl_net=pl.col("realized_pnl") - pl.col("fees"),
        duration_h=(pl.col("closed_ms") - pl.col("opened_ms")) / HOUR_MS,
    ).sort("user", "opened_ms")


# --- 3. leverage path -------------------------------------------------------------------------

MAX_PLAUSIBLE_LEVERAGE = 50.0   # Hyperliquid caps at 40x; anything above is an equity-data artifact
EQUITY_TOLERANCE_MS = 15 * DAY_MS


def equity_points(equity: pl.DataFrame) -> pl.DataFrame:
    """Account value over time, merging every portfolio() period.

    Each period samples the same account value at a different resolution (day: ~30 min, month:
    ~12 h, allTime: up to 14 days), so the union is the finest curve available at every date.
    """
    return (equity.select("user", "time_ms", equity=pl.col("account_value"))
            .unique(subset=["user", "time_ms"]).sort("time_ms"))


def gross_exposure(perp: pl.DataFrame, equity: pl.DataFrame) -> pl.DataFrame:
    """Gross notional across all coins after every fill, with the trader's equity at that moment.

    Equity comes from the sample at or before the fill. When that sample is more than a day
    old the next sample is considered too, and the larger of the two is used: with sparse
    history a deposit can land between samples, and under-counting equity would invent
    leverage that never existed. Values above MAX_PLAUSIBLE_LEVERAGE are set to null.

    Output: user, time_ms, gross, equity, leverage.
    """
    rows = []
    for (user,), g in perp.sort("user", "time_ms", "tid", "leg").group_by(["user"], maintain_order=True):
        book: dict[str, tuple[float, float]] = {}
        gross = 0.0
        for r in g.iter_rows(named=True):
            coin = r["coin"]
            old = book.get(coin)
            if old:
                gross -= abs(old[0]) * old[1]
            book[coin] = (r["position_after"], r["px"])
            gross += abs(r["position_after"]) * r["px"]
            rows.append({"user": user, "time_ms": r["time_ms"], "gross": gross})
    schema = {"user": pl.String, "time_ms": pl.Int64, "gross": pl.Float64, "equity": pl.Float64, "leverage": pl.Float64}
    if not rows:
        return pl.DataFrame(schema=schema)
    exposure = pl.DataFrame(rows).sort("time_ms")
    curve = equity_points(equity)
    back = exposure.join_asof(curve.rename({"time_ms": "t_back"}), left_on="time_ms", right_on="t_back", by="user",
                              strategy="backward", tolerance=EQUITY_TOLERANCE_MS, check_sortedness=False)
    both = back.join_asof(curve.rename({"time_ms": "t_fwd", "equity": "equity_fwd"}), left_on="time_ms",
                          right_on="t_fwd", by="user", strategy="forward", tolerance=EQUITY_TOLERANCE_MS,
                          check_sortedness=False)
    stale = (pl.col("time_ms") - pl.col("t_back")) > DAY_MS
    equity_used = pl.when(stale | pl.col("equity").is_null()).then(
        pl.max_horizontal("equity", "equity_fwd")).otherwise(pl.col("equity"))
    return (both.with_columns(equity=equity_used)
            .with_columns(leverage=pl.when(pl.col("equity") > 0).then(pl.col("gross") / pl.col("equity")))
            .with_columns(leverage=pl.when(pl.col("leverage") <= MAX_PLAUSIBLE_LEVERAGE).then(pl.col("leverage")))
            .select("user", "time_ms", "gross", "equity", "leverage").sort("user", "time_ms"))


# --- 4. features ------------------------------------------------------------------------------

def _trade_features(trades: pl.DataFrame, window_ms: int) -> pl.DataFrame:
    closed = trades.filter(pl.col("closed_ms").is_not_null())
    wins = pl.col("pnl_net").clip(lower_bound=0).sum()
    losses = (-pl.col("pnl_net")).clip(lower_bound=0).sum()
    return closed.group_by("user").agg(
        n_trades=pl.len(),
        trades_per_day=pl.len() / (window_ms / DAY_MS),
        n_coins=pl.col("coin").n_unique(),
        win_rate=(pl.col("pnl_net") > 0).mean(),
        profit_factor=pl.when(losses > 0).then(wins / losses),
        median_duration_h=pl.col("duration_h").median(),
        # Averaging down: share of trades with at least one add at a worse price
        avg_down_share=(pl.col("n_adds_losing") > 0).mean(),
        adds_losing_share=pl.when(pl.col("n_adds").sum() > 0).then(pl.col("n_adds_losing").sum() / pl.col("n_adds").sum()),
        liquidations=pl.col("liquidated").sum(),
        # Dependence on a single trade: best trade's share of all gains
        best_trade_share=pl.when(wins > 0).then(pl.col("pnl_net").max() / wins),
        worst_trade_pnl=pl.col("pnl_net").min(),
    )


def _coin_concentration(trades: pl.DataFrame) -> pl.DataFrame:
    """Share of traded notional in the most traded coin, and Herfindahl index across coins."""
    by_coin = trades.group_by("user", "coin").agg(notional=pl.col("max_notional").sum())
    return by_coin.with_columns(share=pl.col("notional") / pl.col("notional").sum().over("user")).group_by("user").agg(
        top_coin_share=pl.col("share").max(),
        hhi=(pl.col("share") ** 2).sum(),
    )


def _martingale(trades: pl.DataFrame) -> pl.DataFrame:
    """Size of each trade relative to the previous one, split by whether the previous one lost.

    A martingale trader scales up after losses: post_loss_size_ratio well above 1 and above
    post_win_size_ratio. `martingale_share` = share of post-loss trades at least 1.5x larger.
    """
    seq = (trades.filter(pl.col("closed_ms").is_not_null()).sort("user", "opened_ms")
           .with_columns(prev_pnl=pl.col("pnl_net").shift(1).over("user"),
                         prev_notional=pl.col("initial_notional").shift(1).over("user"))
           .filter(pl.col("prev_notional") > 0)
           .with_columns(ratio=pl.col("initial_notional") / pl.col("prev_notional")))
    after_loss = pl.col("prev_pnl") < 0
    return seq.group_by("user").agg(
        post_loss_size_ratio=pl.col("ratio").filter(after_loss).median(),
        post_win_size_ratio=pl.col("ratio").filter(~after_loss).median(),
        martingale_share=(pl.col("ratio").filter(after_loss) >= 1.5).mean(),
    )


def _leverage(exposure: pl.DataFrame) -> pl.DataFrame:
    return exposure.group_by("user").agg(
        median_leverage=pl.col("leverage").median(),
        p95_leverage=pl.col("leverage").quantile(0.95),
        max_leverage=pl.col("leverage").max(),
        # Share of fills where equity was unknown or implied an impossible leverage
        leverage_unknown_share=pl.col("leverage").is_null().mean(),
    )


def _style_change(trades: pl.DataFrame, exposure: pl.DataFrame, now_ms: int, recent_days: int) -> pl.DataFrame:
    """Recent period vs the rest of the window: ratios of medians (1 = no change) and coin overlap.

    Trade size is measured relative to the trader's equity when the trade opened, so a trader who
    deposited 20x more and trades 20x bigger has not changed behavior; one who trades 3x bigger
    on the same capital has."""
    cut = now_ms - recent_days * DAY_MS
    equity_at_open = exposure.select("user", opened_ms=pl.col("time_ms"), equity_at_open=pl.col("equity")).unique(
        subset=["user", "opened_ms"], keep="first")
    t = (trades.join(equity_at_open, on=["user", "opened_ms"], how="left")
         .with_columns(recent=pl.col("opened_ms") >= cut,
                       size_frac=pl.when(pl.col("equity_at_open") > 0).then(pl.col("initial_notional") / pl.col("equity_at_open"))))
    per = t.group_by("user", "recent").agg(
        size=pl.col("size_frac").median(), duration=pl.col("duration_h").median(),
        coins=pl.col("coin").unique(),
    )
    e = exposure.filter(pl.col("leverage").is_not_null()).with_columns(recent=pl.col("time_ms") >= cut)
    lev = e.group_by("user", "recent").agg(lev=pl.col("leverage").median())
    per = per.join(lev, on=["user", "recent"], how="left")
    recent = per.filter(pl.col("recent")).drop("recent")
    prior = per.filter(~pl.col("recent")).drop("recent")
    j = recent.join(prior, on="user", suffix="_prior")
    return j.select(
        "user",
        change_size=pl.col("size") / pl.col("size_prior"),
        change_duration=pl.col("duration") / pl.col("duration_prior"),
        change_leverage=pl.col("lev") / pl.col("lev_prior"),
        coin_overlap=pl.col("coins").list.set_intersection(pl.col("coins_prior")).list.len()
        / pl.col("coins").list.set_union(pl.col("coins_prior")).list.len(),
    )


def behavior_features(fills: pl.DataFrame, equity: pl.DataFrame, now: datetime,
                      window_days: int = 90, recent_days: int = 30) -> pl.DataFrame:
    """One row per trader with the behavioral features over the last `window_days`.

    Trades are attributed to the window by their opening time; trades still open at `now` are
    counted in activity but not in PnL-based stats.
    """
    now_ms = int(now.timestamp() * 1000)
    start_ms = now_ms - window_days * DAY_MS
    perp = perp_fills(fills)
    coverage = perp.group_by("user").agg(first_fill_ms=pl.col("time_ms").min(), fills_total=pl.len())
    window = perp.filter(pl.col("time_ms") >= start_ms)
    if window.is_empty():
        return pl.DataFrame(schema={"user": pl.String})
    trades = round_trips(window)
    exposure = gross_exposure(window, equity)
    activity = window.group_by("user").agg(fills_per_day=pl.len() / window_days,
                                           liquidation_fills=pl.col("liquidated").sum())
    features = (
        coverage.join(activity, on="user", how="inner")
        .join(_trade_features(trades, window_days * DAY_MS), on="user", how="left")
        .join(_coin_concentration(trades), on="user", how="left")
        .join(_martingale(trades), on="user", how="left")
        .join(_leverage(exposure), on="user", how="left")
        .join(_style_change(trades, exposure, now_ms, recent_days), on="user", how="left")
        .with_columns(window_complete=pl.col("first_fill_ms") < start_ms)
    )
    return features.sort("user")
