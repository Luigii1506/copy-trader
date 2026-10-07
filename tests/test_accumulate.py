from datetime import date, timedelta

import polars as pl
import pytest

from analysis.accumulate import PriceBook, accumulate_backtest, daily_closes, features_at
from analysis.backtest import summarize_backtest

START = date(2024, 1, 1)


def candle_frame(series: dict[str, list[float]], notional: float = 5_000_000.0) -> pl.DataFrame:
    rows = []
    for coin, closes in series.items():
        for i, close in enumerate(closes):
            day = START + timedelta(days=i)
            ms = int(day.strftime("%s")) if False else (day - date(1970, 1, 1)).days * 86_400_000
            rows.append({"snapshot_at": "s", "coin": coin, "interval": "1d", "time_ms": ms,
                         "open": close, "high": close, "low": close, "close": close,
                         "volume": notional / close})
    return pl.DataFrame(rows)


def world(days=500):
    """BTC flat-ish, STRONG doubles vs BTC, WEAK bleeds, DEAD crashes 97%, FRESH lists late."""
    return {
        "BTC": [100.0 * (1 + 0.0005) ** i for i in range(days)],
        "STRONG": [10.0 * (1 + 0.004) ** i for i in range(days)],
        "WEAK": [10.0 * (1 - 0.003) ** i for i in range(days)],
        "DEAD": [10.0 if i < 100 else 10.0 * 0.02 for i in range(days)],
        "FRESH": [1.0 + 0.01 * i for i in range(60)],
    }


def test_daily_closes_dedup_keeps_latest_snapshot():
    a = candle_frame({"BTC": [1.0, 2.0]})
    b = a.with_columns(pl.lit("z").alias("snapshot_at"), pl.col("close") + 1)
    out = daily_closes(pl.concat([a, b]))
    assert out["close"].to_list() == [2.0, 3.0]


def test_quality_filter_excludes_dead_fresh_and_illiquid():
    closes = daily_closes(candle_frame(world()))
    feats = features_at(PriceBook(closes), START + timedelta(days=400))
    by = {r["coin"]: r["eligible"] for r in feats.to_dicts()}
    assert by["STRONG"] and by["WEAK"] and by["BTC"]
    assert not by["DEAD"]                   # 98% below its ATH
    assert "FRESH" not in by or not by["FRESH"]   # listed 60 days, stale since
    illiquid = daily_closes(candle_frame({"BTC": world()["BTC"], "THIN": world()["STRONG"]}, notional=1.0))
    thin = {r["coin"]: r["eligible"] for r in
            features_at(PriceBook(illiquid), START + timedelta(days=400)).to_dicts()}
    assert not thin["THIN"]


def test_strong_beats_fallen_in_a_trending_world():
    closes = daily_closes(candle_frame(world()))
    strong = accumulate_backtest(closes, "strong", n=1)
    fallen = accumulate_backtest(closes, "fallen", n=1)
    btc = accumulate_backtest(closes, "btc_only")
    assert strong["equity"][-1] > btc["equity"][-1] > fallen["equity"][-1]
    # fallen keeps buying WEAK (always nearest its 90d low among eligibles)
    assert summarize_backtest(fallen, 4)["total_return"] < 0


def test_no_lookahead_in_features():
    closes = daily_closes(candle_frame(world()))
    book = PriceBook(closes)
    at = START + timedelta(days=300)
    base = features_at(book, at)
    # Change every price after `at`: features at `at` must be identical.
    altered = {c: v[:301] + [999.0] * (len(v) - 301) for c, v in world().items()}
    after = features_at(PriceBook(daily_closes(candle_frame(altered))), at)
    assert base.sort("coin").equals(after.sort("coin"))


def test_delisted_coin_realizes_last_price_and_counts_missing():
    series = {"BTC": [100.0] * 400, "GONE": [10.0] * 250}   # GONE stops printing at day 250
    closes = daily_closes(candle_frame(series))
    table = accumulate_backtest(closes, "everything")
    assert table["n_missing"].sum() >= 1
    assert table["gross_ret"].is_finite().all()


def test_costs_only_reduce_returns():
    closes = daily_closes(candle_frame(world()))
    free = accumulate_backtest(closes, "strong", n=2, cost=0.0)
    paid = accumulate_backtest(closes, "strong", n=2, cost=0.01)
    assert paid["equity"][-1] < free["equity"][-1]
    assert (paid["gross_ret"] == free["gross_ret"]).all()
