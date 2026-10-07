"""Accumulation ranking research (ROADMAP "Línea 2"): which coins to keep buying, never when.

Monthly formation dates over daily candles (delisted coins included - the graveyard is the
point). At each date, coins passing the QUALITY filter are ranked by a rule; the portfolio
holds equal weights for 4 weeks; costs apply to the fraction of the book that rotates.
Everything uses only candles at or before the formation date.

Quality filter (all four, at formation):
- age >= 180 days of candles (no fresh listings)
- median daily notional over the last 30 days >= $1M (tradeable)
- not down more than 95% from its all-time high so far (not already dead)
- a candle within the last 3 days (still trading)

Rules under test:
- strong_n:   top N by 26-week return relative to BTC (momentum - the evidence-backed rule)
- fallen_n:   bottom N by distance from their 90-day high (the "buy the dip" hypothesis)
- btc_only:   accumulate BTC and nothing else (the bar to clear)
- random_n:   seeded random eligible coins (the luck baseline)
- everything: all eligible coins, equal weight (the market of eligibles)

The per-period output matches analysis.backtest.summarize_backtest, so both research tracks
share metrics. A coin that stops printing candles mid-hold is valued at its last close and
counted in n_missing (a delisting realizes that price; pretending otherwise flatters results).
"""

from __future__ import annotations

import random
from bisect import bisect_right
from datetime import date, timedelta

import polars as pl

QUALITY_MIN_AGE_DAYS = 180
QUALITY_MIN_NOTIONAL = 1_000_000.0
QUALITY_MAX_FALL_FROM_ATH = 0.95
STALE_DAYS = 3
MOMENTUM_DAYS = 182          # 26 weeks
FALLEN_WINDOW_DAYS = 90
HOLD_WEEKS = 4
COST_PER_TURNOVER = 0.0015   # spot round trip: taker fees + slippage on the rotated fraction
BENCHMARK = "BTC"


def daily_closes(candles: pl.DataFrame) -> pl.DataFrame:
    """Dedup across snapshots -> one row per (coin, day) with close and notional volume."""
    return (candles.sort("snapshot_at").unique(subset=["coin", "time_ms"], keep="last")
            .with_columns(date=pl.from_epoch("time_ms", time_unit="ms").dt.date(),
                          notional=pl.col("close") * pl.col("volume"))
            .select("coin", "date", "close", "notional").sort("coin", "date"))


class PriceBook:
    """Per-coin date-indexed closes with backward as-of lookup."""

    def __init__(self, closes: pl.DataFrame):
        self.coins: dict[str, tuple[list[date], list[float], list[float]]] = {}
        for (coin,), g in closes.group_by(["coin"], maintain_order=True):
            self.coins[coin] = (g["date"].to_list(), g["close"].to_list(), g["notional"].to_list())

    def at(self, coin: str, when: date, tolerance_days: int = STALE_DAYS) -> float | None:
        dates, closes, _ = self.coins.get(coin, ([], [], []))
        i = bisect_right(dates, when) - 1
        if i < 0 or (when - dates[i]).days > tolerance_days:
            return None
        return closes[i]

    def last_close(self, coin: str, when: date) -> float | None:
        """Last close at or before `when`, however stale (a delisting realizes this price)."""
        dates, closes, _ = self.coins.get(coin, ([], [], []))
        i = bisect_right(dates, when) - 1
        return closes[i] if i >= 0 else None


def features_at(book: PriceBook, at: date) -> pl.DataFrame:
    """Per-coin eligibility and signals using only candles at or before `at`."""
    btc_now = book.at(BENCHMARK, at)
    btc_then = book.at(BENCHMARK, at - timedelta(days=MOMENTUM_DAYS))
    rows = []
    for coin, (dates, closes, notionals) in book.coins.items():
        i = bisect_right(dates, at) - 1
        if i < 0:
            continue
        now = closes[i]
        hist_dates, hist_closes = dates[: i + 1], closes[: i + 1]
        last30 = [n for d, n in zip(hist_dates, notionals[: i + 1]) if (at - d).days <= 30]
        vol30 = sorted(last30)[len(last30) // 2] if last30 else 0.0
        ath = max(hist_closes)
        then = book.at(coin, at - timedelta(days=MOMENTUM_DAYS))
        high90 = max((c for d, c in zip(hist_dates, hist_closes) if (at - d).days <= FALLEN_WINDOW_DAYS),
                     default=now)
        momentum = None
        if then and btc_now and btc_then:
            momentum = (now / then) / (btc_now / btc_then) - 1   # return vs BTC over 26 weeks
        rows.append({
            "coin": coin,
            "eligible": ((at - hist_dates[0]).days >= QUALITY_MIN_AGE_DAYS
                         and vol30 >= QUALITY_MIN_NOTIONAL
                         and now > ath * (1 - QUALITY_MAX_FALL_FROM_ATH)
                         and (at - hist_dates[-1]).days <= STALE_DAYS),
            "momentum": momentum,
            "fall_from_high90": now / high90 - 1,
        })
    return pl.DataFrame(rows)


def accumulate_backtest(closes: pl.DataFrame, rule: str, n: int = 5,
                        hold_weeks: int = HOLD_WEEKS, cost: float = COST_PER_TURNOVER,
                        seed: int = 0) -> pl.DataFrame:
    """One row per holding period, same columns as analysis.backtest's tables."""
    book = PriceBook(closes)
    if BENCHMARK not in book.coins:
        return pl.DataFrame()
    dates = book.coins[BENCHMARK][0]
    first = dates[0] + timedelta(days=MOMENTUM_DAYS)
    last = dates[-1] - timedelta(weeks=hold_weeks)
    rows: list[dict] = []
    equity, prev = 1.0, []
    at, i = first, 0
    while at <= last:
        feats = features_at(book, at)
        pool = feats.filter(pl.col("eligible"))
        if rule == "btc_only":
            chosen = [BENCHMARK]
        elif rule == "random":
            users = sorted(pool["coin"].to_list())
            chosen = random.Random(seed * 7919 + i).sample(users, min(n, len(users)))
        elif rule == "everything":
            chosen = pool["coin"].to_list()
        elif rule == "strong":
            chosen = (pool.filter(pl.col("momentum").is_not_null())
                      .sort("momentum", descending=True).head(n)["coin"].to_list())
        elif rule == "fallen":
            chosen = pool.sort("fall_from_high90").head(n)["coin"].to_list()
        else:
            raise ValueError(rule)
        end = at + timedelta(weeks=hold_weeks)
        rets, missing = [], 0
        for coin in chosen:
            p0 = book.at(coin, at)
            p1 = book.at(coin, end)
            if p1 is None:
                p1 = book.last_close(coin, end)
                missing += 1
            rets.append(p1 / p0 - 1 if p0 and p1 else 0.0)
        gross = sum(rets) / len(rets) if rets else 0.0
        turnover = (sum(c not in prev for c in chosen) / len(chosen)) if chosen else None
        net = (1 + gross) * (1 - cost * (turnover or 0.0)) - 1 if chosen else 0.0
        equity *= 1 + net
        rows.append({"formation": at, "end": end, "n_selected": len(chosen), "n_missing": missing,
                     "turnover": turnover, "gross_ret": gross, "net_ret": net, "equity": equity})
        prev = chosen
        at, i = end, i + 1
    return pl.DataFrame(rows)
