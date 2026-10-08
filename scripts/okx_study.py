"""Independent replication on OKX copy-trading lead traders (anti-overfitting test).

Usage: COPY_TRADER_DATA=... python scripts/okx_study.py

Same frozen methodology as Hyperliquid (ADR-003): 12-week lookback, 4-week hold, top-N by the
same signals, same TraderScore. Only the data source differs: weekly returns from OKX's daily
*accumulated* pnl ratio, r_w = (1 + R_t) / (1 + R_{t-1}) - 1. How OKX's ratio treats deposits is
not documented; it is their number, used as published. Size filter uses the latest AUM.
"""

import sys
from datetime import timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import polars as pl  # noqa: E402

from analysis.backtest import copy_backtest, everyone, random_baseline, summarize_backtest, top_by  # noqa: E402
from analysis.persistence import retroactive_persistence, summarize  # noqa: E402
from analysis.score import top_by_score  # noqa: E402
from papertrade.selection import _read  # noqa: E402


def weekly_returns(pnl: pl.DataFrame, traders: pl.DataFrame) -> pl.DataFrame:
    daily = (pnl.unique(subset=["user", "time_ms"], keep="last")
             .with_columns(day=pl.from_epoch("time_ms", time_unit="ms").dt.replace_time_zone("UTC"))
             .sort("user", "day"))
    weekly = (daily.with_columns(end=pl.col("day").dt.truncate("1w") + pl.duration(days=7))
              .group_by("user", "end").agg(ratio=pl.col("pnl_ratio").last(), pnl=pl.col("pnl").last())
              .sort("user", "end"))
    aum = (traders.sort("snapshot_at").group_by("user").agg(account_value=pl.col("aum").last()))
    return (weekly.join(aum, on="user", how="left")
            .with_columns(dpnl=pl.col("pnl").diff().over("user"),
                          ret=(1 + pl.col("ratio")) / (1 + pl.col("ratio").shift(1).over("user")) - 1)
            .with_columns(ret=pl.when(pl.col("ret").is_finite()).then(pl.col("ret")))
            .with_columns(pl.col("end").dt.cast_time_unit("ms"))
            .select("user", "end", "account_value", "pnl", "dpnl", "ret"))


def line(name: str, m: dict) -> str:
    return (f"{name:14} cagr {m['cagr']:+7.1%}  dd {m['max_drawdown']:7.1%}  sharpe {m['sharpe'] or 0:5.2f}  "
            f"periods {m['periods']}")


def main() -> int:
    pnl, traders = _read("okx_pnl"), _read("okx_traders")
    if pnl is None or traders is None:
        print("no OKX data yet"); return 1
    returns = weekly_returns(pnl, traders)
    print(f"OKX lead traders con retornos: {returns.drop_nulls('ret')['user'].n_unique()}  "
          f"semanas: {returns['end'].min():%Y-%m-%d} -> {returns['end'].max():%Y-%m-%d}\n")

    print("== persistencia (12 sem -> 4 sem) ==")
    print(summarize(retroactive_persistence(returns, 12, 4)).select(
        "signal", "periods", "wallets_avg", "mean_ic", "ic_tstat", "ic_positive"))

    kw = dict(hold_weeks=4, friction_per_step=0.0025, min_account=1_000.0)
    print("\n== backtest top-10 (con fricción supuesta) ==")
    for name, sel in [("top_sharpe", top_by("sharpe", 10)), ("top_score", top_by_score(10)),
                      ("top_ret", top_by("ret", 10)), ("top_pnl_usd", top_by("pnl_usd", 10)),
                      ("everyone", everyone())]:
        table = copy_backtest(returns, sel, **kw)
        print(line(name, summarize_backtest(table, 4)) if not table.is_empty() else f"{name:14} (sin datos)")
    rnd = random_baseline(returns, 10, seeds=12, **kw)
    print(f"{'random_10':14} cagr mediana {rnd['cagr'].median():+.1%}  p90 {rnd['cagr'].quantile(0.9):+.1%}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
