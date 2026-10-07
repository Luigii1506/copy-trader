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
            for period in ("allTime", "perpAllTime"):   # all PnL is perp PnL in these worlds
                rows.append({"user": user, "period": period, "time_ms": int(ts.timestamp() * 1000),
                             "account_value": value, "pnl": pnl})
    return pl.DataFrame(rows)


def world(n_wallets=200, weeks=60, skill_sd=0.02, noise_sd=0.03, seed=1):
    rng = random.Random(seed)
    out = {}
    for i in range(n_wallets):
        skill = rng.gauss(0, skill_sd)
        out[f"0x{i:04x}"] = [skill + rng.gauss(0, noise_sd) for _ in range(weeks)]
    return out


def test_returns_without_flows_are_simple_returns():
    rets = period_returns(equity_from_returns({"0xa": [0.01, 0.02]}), step_weeks=1).drop_nulls("ret")["ret"]
    assert [round(r, 9) for r in rets] == [0.01, 0.02]


def test_mid_step_deposit_does_not_inflate_returns():
    ms = lambda w: int((START + timedelta(weeks=w, hours=-1)).timestamp() * 1000)
    eq = pl.DataFrame([
        {"user": "0xa", "period": p, "time_ms": ms(0), "account_value": 1_500.0, "pnl": 0.0} for p in ("allTime", "perpAllTime")
    ] + [
        # $200k deposited during the week, then $20k earned trading it
        {"user": "0xa", "period": p, "time_ms": ms(1), "account_value": 221_500.0, "pnl": 20_000.0} for p in ("allTime", "perpAllTime")
    ])
    [ret] = period_returns(eq, step_weeks=1).drop_nulls("ret")["ret"].to_list()
    # Deposit counted from the start: 20k / (1.5k + 200k) = 9.9%, the conservative bound.
    assert abs(ret - 20_000 / 201_500) < 1e-9


def test_withdrawn_profits_do_not_shrink_the_capital_base():
    ms = lambda w: int((START + timedelta(weeks=w, hours=-1)).timestamp() * 1000)
    rows = [{"user": "0xa", "period": p, "time_ms": ms(0), "account_value": 1.7e6, "pnl": 0.0} for p in ("allTime", "perpAllTime")]
    # +$3.1M earned, $3.2M withdrawn: account ends slightly lower
    rows += [{"user": "0xa", "period": p, "time_ms": ms(1), "account_value": 1.6e6, "pnl": 3.1e6} for p in ("allTime", "perpAllTime")]
    [ret] = period_returns(pl.DataFrame(rows), step_weeks=1).drop_nulls("ret")["ret"].to_list()
    assert abs(ret - 3.1e6 / 1.7e6) < 1e-9


def test_synthetic_origin_point_is_ignored():
    ms = lambda h: int((START + timedelta(hours=h)).timestamp() * 1000)
    rows = [{"user": "0xa", "period": "allTime", "time_ms": ms(-2), "account_value": 0.0, "pnl": 0.0},
            {"user": "0xa", "period": "allTime", "time_ms": ms(-1), "account_value": 10_000.0, "pnl": 500_000.0},
            {"user": "0xa", "period": "perpAllTime", "time_ms": ms(-2), "account_value": 0.0, "pnl": 0.0},
            {"user": "0xa", "period": "perpAllTime", "time_ms": ms(-1), "account_value": 10_000.0, "pnl": 500_000.0}]
    rows += [{"user": "0xa", "period": p, "time_ms": ms(24 * 7 - 1), "account_value": 10_100.0, "pnl": 500_100.0}
             for p in ("allTime", "perpAllTime")]
    [ret] = period_returns(pl.DataFrame(rows), step_weeks=1).drop_nulls("ret")["ret"].to_list()
    assert abs(ret - 100 / 10_000) < 1e-9       # not 500k / 10k


def test_spot_gains_are_not_trading_returns():
    ms = lambda w: int((START + timedelta(weeks=w, hours=-1)).timestamp() * 1000)
    rows = []
    for w, (av, total, perp) in enumerate([(10_000.0, 0.0, 0.0), (60_000.0, 50_000.0, 5_000.0)]):
        rows.append({"user": "0xa", "period": "allTime", "time_ms": ms(w), "account_value": av, "pnl": total})
        rows.append({"user": "0xa", "period": "perpAllTime", "time_ms": ms(w), "account_value": av, "pnl": perp})
    [ret] = period_returns(pl.DataFrame(rows), step_weeks=1).drop_nulls("ret")["ret"].to_list()
    assert abs(ret - 5_000 / 10_000) < 1e-9     # $45k of spot/airdrop gains are not perp skill


def test_losses_beyond_the_starting_capital_imply_a_deposit():
    ms = lambda w: int((START + timedelta(weeks=w, hours=-1)).timestamp() * 1000)
    rows = [{"user": "0xa", "period": p, "time_ms": ms(0), "account_value": 10_000.0, "pnl": 0.0} for p in ("allTime", "perpAllTime")]
    # Lost $30k on a $10k account: $21k must have been deposited, so the base is $31k
    rows += [{"user": "0xa", "period": p, "time_ms": ms(1), "account_value": 1_000.0, "pnl": -30_000.0} for p in ("allTime", "perpAllTime")]
    [ret] = period_returns(pl.DataFrame(rows), step_weeks=1).drop_nulls("ret")["ret"].to_list()
    assert abs(ret - (-30_000 / 31_000)) < 1e-9


def test_returns_are_floored_at_minus_100_percent():
    ms = lambda w: int((START + timedelta(weeks=w, hours=-1)).timestamp() * 1000)
    rows = [{"user": "0xa", "period": p, "time_ms": ms(0), "account_value": 10_000.0, "pnl": 0.0} for p in ("allTime", "perpAllTime")]
    # Perp PnL -30k offset by +21k of spot gains: total PnL -9k, no flow, so the base stays $10k
    rows += [{"user": "0xa", "period": "allTime", "time_ms": ms(1), "account_value": 1_000.0, "pnl": -9_000.0},
             {"user": "0xa", "period": "perpAllTime", "time_ms": ms(1), "account_value": 1_000.0, "pnl": -30_000.0}]
    [ret] = period_returns(pl.DataFrame(rows), step_weeks=1).drop_nulls("ret")["ret"].to_list()
    assert ret == -1.0


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
