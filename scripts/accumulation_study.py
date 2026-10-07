"""Track-2 accumulation comparison on real candles (ROADMAP Línea 2).

Usage: COPY_TRADER_DATA=... python scripts/accumulation_study.py
Prints the rule comparison that decides between momentum ("strong"), the buy-the-dip
hypothesis ("fallen"), accumulating BTC only, and luck (random baseline).
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import polars as pl  # noqa: E402

from analysis.accumulate import accumulate_backtest, daily_closes  # noqa: E402
from analysis.backtest import summarize_backtest  # noqa: E402
from papertrade.selection import _read  # noqa: E402


def line(name: str, m: dict) -> str:
    return (f"{name:14} cagr {m['cagr']:+7.1%}  dd {m['max_drawdown']:7.1%}  "
            f"sharpe {m['sharpe'] or 0:5.2f}  calmar {m['calmar'] or 0:5.2f}  "
            f"turnover {m['avg_turnover'] or 0:4.0%}  worst {m['worst_period']:+.1%}  "
            f"missing {m['missing_share']:.1%}")


def main() -> int:
    candles = _read("candles")
    if candles is None:
        print("no candles table yet"); return 1
    closes = daily_closes(candles)
    print(f"coins: {closes['coin'].n_unique()}  days: {closes['date'].min()} -> {closes['date'].max()}  "
          f"rows: {closes.height:,}\n")
    for name, rule, n in [("strong_5", "strong", 5), ("strong_10", "strong", 10),
                          ("fallen_5", "fallen", 5), ("fallen_10", "fallen", 10),
                          ("btc_only", "btc_only", 1), ("everything", "everything", 0)]:
        table = accumulate_backtest(closes, rule, n=n)
        if table.is_empty():
            print(f"{name:14} (no data)"); continue
        print(line(name, summarize_backtest(table, 4)))
    rnd = pl.DataFrame([summarize_backtest(accumulate_backtest(closes, "random", n=5, seed=s), 4)
                        for s in range(12)])
    print(f"\nrandom_5 (12 semillas): cagr mediana {rnd['cagr'].median():+.1%}  "
          f"p10 {rnd['cagr'].quantile(0.1):+.1%}  p90 {rnd['cagr'].quantile(0.9):+.1%}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
