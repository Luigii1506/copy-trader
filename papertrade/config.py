"""Paper-trading parameters. Rationale for each choice: docs/decisions/ADR-002-paper-trading.md."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import timedelta


@dataclass(frozen=True)
class Strategy:
    name: str
    signal: str                  # column produced by papertrade.selection.candidate_signals
    n_traders: int = 10
    capital: float = 10_000.0
    rebalance_days: int = 28
    max_leverage: float = 5.0    # per book: gross notional / book equity
    halt_drawdown: float = 0.30  # stop the strategy after this fall from its peak equity

    def to_dict(self) -> dict:
        return asdict(self)


STRATEGIES = [
    Strategy("leaderboard_pnl", "leaderboard_month_pnl"),
    Strategy("top_return", "ret"),
    Strategy("top_sharpe", "sharpe"),
    Strategy("low_drawdown", "low_dd"),
    Strategy("random", "random"),
]

# Costs (Hyperliquid docs, 2026-10-06)
TAKER_FEE = 0.00045          # base tier perps taker fee
MIN_SLIPPAGE = 0.0002        # floor over mid when impact prices are tighter (2 bps)

# Copy mechanics
POLL_INTERVAL = timedelta(seconds=60)
EQUITY_REFRESH = timedelta(minutes=15)    # trader total equity via portfolio() (weight 20)
DEX_RESCAN = timedelta(minutes=30)        # look for positions on every HIP-3 dex
SNAPSHOT_INTERVAL = timedelta(minutes=5)
REBALANCE_BAND = 0.10        # trade only if the change exceeds 10% of the position...
MIN_TRADE_USD = 10.0         # ...and at least $10
MIN_ORDER_USD = 10.0         # exchange rule: "Order must have minimum value of $10" (docs, exchange endpoint)

# Selection pool
MIN_TRADER_EQUITY = 10_000.0           # don't copy accounts smaller than this
MIN_BOOK_TRADER_EQUITY = 1_000.0       # stop copying a trader whose account falls below this
MAX_FILLS_PER_DAY = 500                # above this a 60 s poll can't follow them (HFT / market makers)
LOOKBACK_WEEKS = 12

# Behavior watch (papertrade/watch.py): stop copying when a followed trader's recent behavior
# crosses a limit. (rule, feature column, comparison, limit). Starting points, to be calibrated.
WATCH_INTERVAL = timedelta(hours=6)
WATCH_WINDOW_DAYS = 60
WATCH_MIN_TRADES = 5                    # fewer closed trades than this: not enough evidence
FLAG_TTL = timedelta(days=14)           # a flagged trader stays ineligible this long
EXIT_RULES = [
    ("liquidated", "liquidations", ">", 0),             # any forced liquidation in the window
    ("martingale", "martingale_share", ">", 0.6),        # sizes up after losses most of the time
    ("leverage", "p95_leverage", ">", 15.0),             # routinely near the exchange maximum
    ("leverage_escalation", "change_leverage", ">", 2.0),  # recent leverage doubled vs. before
    ("size_escalation", "change_size", ">", 3.0),        # recent trades 3x bigger than before
]
