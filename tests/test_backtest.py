import sys
from datetime import timedelta
from pathlib import Path

import polars as pl
import pytest

sys.path.insert(0, str(Path(__file__).parent))
from test_persistence import START, equity_from_returns, world  # noqa: E402

from analysis.backtest import (
    buy_and_hold,
    compare,
    copy_backtest,
    everyone,
    random_baseline,
    summarize_backtest,
    top_by,
)
from analysis.persistence import period_returns


def returns_of(data):
    return period_returns(equity_from_returns(data, start_value=50_000.0), step_weeks=1)


def test_top_return_beats_random_in_a_skilled_world_and_not_without_skill():
    skilled = returns_of(world(n_wallets=150, weeks=70, skill_sd=0.02, noise_sd=0.03))
    top = summarize_backtest(copy_backtest(skilled, top_by("ret", 10), rebalance_cost=0.0))
    rnd = random_baseline(skilled, 10, seeds=8, rebalance_cost=0.0)
    assert top["total_return"] > rnd["total_return"].quantile(0.9)

    flat = returns_of(world(n_wallets=150, weeks=70, skill_sd=0.0, noise_sd=0.03, seed=3))
    top = summarize_backtest(copy_backtest(flat, top_by("ret", 10), rebalance_cost=0.0))
    rnd = random_baseline(flat, 10, seeds=8, rebalance_cost=0.0)
    assert rnd["total_return"].quantile(0.1) <= top["total_return"] <= rnd["total_return"].quantile(0.9) + 0.2


def test_costs_only_lower_returns():
    r = returns_of(world(n_wallets=60, weeks=40))
    free = copy_backtest(r, top_by("ret", 5), rebalance_cost=0.0)
    paid = copy_backtest(r, top_by("ret", 5), rebalance_cost=0.01, friction_per_step=0.002)
    assert (paid["gross_ret"] == free["gross_ret"]).all()
    assert (paid["net_ret"] < free["net_ret"]).all()
    assert paid["equity"][-1] < free["equity"][-1]


def test_selection_never_sees_the_holding_period():
    data = world(n_wallets=40, weeks=40, seed=5)
    base = copy_backtest(returns_of(data), top_by("ret", 5), rebalance_cost=0.0)
    # Make everyone's last 10 weeks wildly different; formation dates before that must pick the same traders.
    altered = {u: r[:30] + [0.5 if i % 2 else -0.3 for i in range(10)] for u, r in data.items()}
    after = copy_backtest(returns_of(altered), top_by("ret", 5), rebalance_cost=0.0)
    cutoff = START + timedelta(weeks=30 - 4)
    same = base.filter(pl.col("end") <= cutoff)["gross_ret"]
    assert same.to_list() == pytest.approx(after.filter(pl.col("end") <= cutoff)["gross_ret"].to_list())


def test_missing_traders_count_as_cash_and_are_reported():
    data = world(n_wallets=30, weeks=40, seed=7)
    r = returns_of(data)
    victim = sorted(data)[0]
    gone = r.filter(~((pl.col("user") == victim) & (pl.col("end") > START + timedelta(weeks=20))))
    table = copy_backtest(gone, everyone(), rebalance_cost=0.0)
    assert table["n_missing"].sum() >= 1
    assert table["gross_ret"].is_finite().all()


def test_buy_and_hold_and_metrics():
    periods = pl.DataFrame({"formation": [START + timedelta(weeks=4 * i) for i in range(3)],
                            "end": [START + timedelta(weeks=4 * (i + 1)) for i in range(3)]})
    days = [START + timedelta(days=d) for d in range(0, 90)]
    prices = pl.DataFrame({"time_ms": [int(d.timestamp() * 1000) for d in days],
                           "close": [100.0 * 1.01 ** i for i in range(90)]})
    bh = buy_and_hold(prices, periods)
    assert bh["gross_ret"].to_list() == pytest.approx([1.01 ** 28 - 1] * 3, rel=1e-9)
    m = summarize_backtest(bh)
    assert m["max_drawdown"] == 0 and m["hit_rate"] == 1 and m["cagr"] > 0
    table = compare({"bh": bh, "bh2": bh})
    assert table.height == 2 and "sharpe" in table.columns
