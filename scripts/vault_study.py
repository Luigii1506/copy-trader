"""Vault study: does risk-adjusted selection work on vaults, net of the leader's commission?

Usage: COPY_TRADER_DATA=... python scripts/vault_study.py

Vaults are Hyperliquid's native copy trading: a deposit mirrors the leader exactly, so there is
no replication friction, but the leader keeps `leader_commission` of depositor profits. Returns
come from the same period_returns as traders (perp PnL over Dietz capital), then net of
commission per step: r_net = r - c * max(r, 0). That ignores the high-water mark (commission is
really charged on cumulative profit at withdrawal), which overstates the fee after losing steps:
a conservative simplification.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import polars as pl  # noqa: E402

from analysis.backtest import (  # noqa: E402
    buy_and_hold, copy_backtest, everyone, random_baseline, summarize_backtest, top_by,
)
from analysis.persistence import period_returns, retroactive_persistence, summarize  # noqa: E402
from analysis.score import top_by_score  # noqa: E402
from papertrade.selection import _read  # noqa: E402

DEFAULT_COMMISSION = 0.10


def line(name: str, m: dict) -> str:
    return (f"{name:16} cagr {m['cagr']:+7.1%}  dd {m['max_drawdown']:7.1%}  sharpe {m['sharpe'] or 0:5.2f}  "
            f"calmar {m['calmar'] or 0:5.2f}  periods {m['periods']}")


def main() -> int:
    equity = _read("vault_equity")
    meta = _read("vault_meta")
    if equity is None or meta is None:
        print("no vault data yet"); return 1
    equity = equity.unique(subset=["user", "period", "time_ms"])
    commission = (meta.sort("snapshot_at").group_by("vault_address")
                  .agg(c=pl.col("leader_commission").last()))
    returns = (period_returns(equity)
               .join(commission.rename({"vault_address": "user"}), on="user", how="left")
               .with_columns(c=pl.col("c").fill_null(DEFAULT_COMMISSION))
               .with_columns(ret=pl.col("ret") - pl.col("c") * pl.col("ret").clip(lower_bound=0.0))
               .drop("c"))
    users = returns.drop_nulls("ret")["user"].n_unique()
    print(f"vaults con retornos: {users}  pasos: {returns['end'].min():%Y-%m} -> {returns['end'].max():%Y-%m}")
    print(f"comisión mediana del líder: {commission['c'].median():.0%}\n")

    print("== persistencia (neta de comisión) ==")
    print(summarize(retroactive_persistence(returns, 12, 4)).select("signal", "periods", "wallets_avg",
                                                                     "mean_ic", "ic_tstat", "ic_positive"))

    kw = dict(hold_weeks=4, friction_per_step=0.0, rebalance_cost=0.0)   # deposits/withdrawals are free
    print("\n== backtest top-5 (neto de comisión, sin fricción de copia) ==")
    runs = {
        "top_score": copy_backtest(returns, top_by_score(5), **kw),
        "top_sharpe": copy_backtest(returns, top_by("sharpe", 5), **kw),
        "top_ret": copy_backtest(returns, top_by("ret", 5), **kw),
        "everyone": copy_backtest(returns, everyone(), **kw),
    }
    candles = _read("candles")
    if candles is not None:
        btc = (candles.filter(pl.col("coin") == "BTC").sort("snapshot_at")
               .unique(subset=["time_ms"], keep="last").select("time_ms", "close"))
        runs["buy_hold_btc"] = buy_and_hold(btc, runs["everyone"])
    for name, table in runs.items():
        if table.is_empty():
            print(f"{name:16} (sin datos)"); continue
        print(line(name, summarize_backtest(table, 4)))
    rnd = random_baseline(returns, 5, seeds=12, **kw)
    print(f"{'random_5':16} cagr mediana {rnd['cagr'].median():+.1%}  p90 {rnd['cagr'].quantile(0.9):+.1%}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
