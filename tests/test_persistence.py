import random
from datetime import datetime, timedelta, timezone

import polars as pl

from analysis.persistence import (
    formation_signals,
    leaderboard_persistence,
    retroactive_persistence,
    summarize,
    period_returns,
)

START = datetime(2025, 1, 5, tzinfo=timezone.utc)  # a Sunday


def equity_from_returns(weekly: dict[str, list[float]], start_value=10_000.0) -> pl.DataFrame:
    """Builds portfolio()-style rows (cumulative PnL + account value) from weekly returns."""
    rows = []
    for user, rets in weekly.items():
        value, pnl = start_value, 0.0
        for i, r in enumerate([0.0] + rets):
            if i:
                gain = value * r
                pnl += gain
                value += gain
            ts = START + timedelta(weeks=i, hours=-1)  # observed just before each week boundary
            rows.append({"user": user, "period": "allTime", "time_ms": int(ts.timestamp() * 1000),
                         "account_value": value, "pnl": pnl})
    return pl.DataFrame(rows)


def world(n_wallets=200, weeks=60, skill_sd=0.02, noise_sd=0.03, seed=1):
    rng = random.Random(seed)
    out = {}
    for i in range(n_wallets):
        skill = rng.gauss(0, skill_sd)
        out[f"0x{i:04x}"] = [skill + rng.gauss(0, noise_sd) for _ in range(weeks)]
    return out


def test_returns_ignore_deposits():
    eq = equity_from_returns({"0xa": [0.01, 0.01]})
    # A deposit during week 1 doubles account value without changing PnL.
    eq = eq.with_columns(pl.when(pl.col("pnl") > 50).then(pl.col("account_value") * 2)
                         .otherwise(pl.col("account_value")).alias("account_value"))
    rets = period_returns(eq, step_weeks=1).drop_nulls("ret")["ret"].to_list()
    assert len(rets) == 2
    assert abs(rets[0] - 0.01) < 1e-9          # the deposit is not counted as a gain
    assert abs(rets[1] - 101 / 20_200) < 1e-9  # later returns are on the larger capital


def test_skilled_world_shows_persistence_and_random_does_not():
    summary = summarize(retroactive_persistence(period_returns(equity_from_returns(world()), step_weeks=1)))
    ic = dict(zip(summary["signal"], summary["mean_ic"]))
    assert ic["ret"] > 0.3 and ic["sharpe"] > 0.3
    assert abs(ic["random"]) < 0.1


def test_no_skill_world_shows_no_persistence():
    summary = summarize(retroactive_persistence(period_returns(equity_from_returns(world(skill_sd=0.0)), step_weeks=1)))
    ic = dict(zip(summary["signal"], summary["mean_ic"]))
    assert abs(ic["ret"]) < 0.1


def test_signals_never_use_future_weeks():
    data = world(n_wallets=30, weeks=30)
    at = START + timedelta(weeks=15)
    base = formation_signals(period_returns(equity_from_returns(data), step_weeks=1), at, 12, 9)
    future_changed = {u: r[:15] + [9.9] * 15 for u, r in data.items()}
    after = formation_signals(period_returns(equity_from_returns(future_changed), step_weeks=1), at, 12, 9)
    assert base.drop("random").equals(after.drop("random"))


def test_two_week_grid_keeps_wallets_sampled_every_two_weeks():
    """Long histories come back every ~14 days; they must not be dropped by a too-fine grid."""
    data = world(n_wallets=60, weeks=60, skill_sd=0.005)  # mild skill: nobody falls below min_account
    eq = equity_from_returns(data).filter((pl.col("time_ms").rank("dense").over("user") % 2) == 1)
    table = retroactive_persistence(period_returns(eq, step_weeks=2))
    assert table.filter(pl.col("signal") == "ret")["n"].min() == 60


def test_leaderboard_forward_counts_dropped_wallets():
    def snap(day, rows):
        return [{"snapshot_at": (START + timedelta(days=day)).isoformat(), "user": u,
                 "account_value": 50_000.0, "week_roi": r} for u, r in rows]
    users = [f"0x{i}" for i in range(20)]
    a = snap(0, [(u, i / 100) for i, u in enumerate(users)])
    b = snap(7, [(u, i / 100) for i, u in enumerate(users[:-3])])  # 3 wallets vanished
    table = leaderboard_persistence(pl.DataFrame(a + b))
    row = table.filter(pl.col("signal") == "week_roi").row(0, named=True)
    assert row["dropped"] == 3 and row["ic"] > 0.99
