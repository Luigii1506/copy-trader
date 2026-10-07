"""Book accounting and copy logic. Pure functions: no network, no database.

A book follows one trader inside one strategy. Perp accounting with signed sizes:
    equity = cash + sum(size * mark)
Buying moves notional out of cash (cash can go negative: that is the leverage), so PnL is linear
in price exactly as on a perp exchange. Fees and funding are charged to cash.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .config import MIN_ORDER_USD, MIN_SLIPPAGE, MIN_TRADE_USD, REBALANCE_BAND, TAKER_FEE


@dataclass
class Market:
    """One perp market snapshot (from metaAndAssetCtxs)."""
    mid: float
    oracle: float
    funding: float            # hourly rate; longs pay when positive
    impact_bid: float | None = None
    impact_ask: float | None = None
    sz_decimals: int | None = None   # lot precision from meta; None = no rounding

    def lot(self, size: float) -> float:
        """Size rounded to the asset's lot precision (docs: sizes are rounded to szDecimals)."""
        return round(size, self.sz_decimals) if self.sz_decimals is not None else size

    def fill_price(self, buying: bool) -> float:
        """Impact price for the side, never better than mid +/- MIN_SLIPPAGE."""
        if buying:
            floor = self.mid * (1 + MIN_SLIPPAGE)
            return max(self.impact_ask or floor, floor)
        floor = self.mid * (1 - MIN_SLIPPAGE)
        return min(self.impact_bid or floor, floor)


@dataclass
class Book:
    strategy: str
    trader: str
    cash: float
    positions: dict[str, float] = field(default_factory=dict)  # coin -> signed size

    def equity(self, markets: dict[str, Market]) -> float:
        return self.cash + sum(size * markets[c].mid for c, size in self.positions.items() if c in markets)

    def gross(self, markets: dict[str, Market]) -> float:
        return sum(abs(size) * markets[c].mid for c, size in self.positions.items() if c in markets)


@dataclass
class Fill:
    coin: str
    size: float          # signed: + buy, - sell
    price: float
    fee: float
    slippage_cost: float  # vs mid, in USD
    reason: dict


def target_notionals(trader_notionals: dict[str, float], trader_equity: float, book_equity: float,
                     max_leverage: float) -> tuple[dict[str, float], float]:
    """Copy the trader's exposure as a fraction of their equity, scaled to the book's equity.

    Returns (targets, scale): scale < 1 when the trader's leverage exceeds max_leverage and the
    whole book was shrunk proportionally (same direction and mix, less leverage)."""
    if trader_equity <= 0 or book_equity <= 0:
        return {}, 0.0
    exposure = {c: n / trader_equity for c, n in trader_notionals.items() if n}
    gross_lev = sum(abs(x) for x in exposure.values())
    scale = min(1.0, max_leverage / gross_lev) if gross_lev > 0 else 1.0
    return {c: x * scale * book_equity for c, x in exposure.items()}, scale


def plan_trades(book: Book, targets: dict[str, float], markets: dict[str, Market]) -> list[tuple[str, float, float]]:
    """(coin, size_delta, target_notional) for positions whose gap to target is worth trading.

    Trade when closing, flipping sides, or when the gap exceeds both REBALANCE_BAND of the larger
    of target/current and MIN_TRADE_USD. Coins without a market price are left untouched."""
    trades = []
    for coin in sorted(set(targets) | set(book.positions)):
        market = markets.get(coin)
        if market is None:
            continue
        current = book.positions.get(coin, 0.0) * market.mid
        target = targets.get(coin, 0.0)
        gap = target - current
        closing = target == 0 and current != 0
        if abs(gap) < MIN_TRADE_USD and not closing:
            continue
        flipping = current * target < 0
        if closing or flipping or abs(gap) > REBALANCE_BAND * max(abs(target), abs(current)):
            delta = -book.positions.get(coin, 0.0) if closing else market.lot(gap / market.mid)
            # Exchange rule: orders under $10 are rejected. Closing a residual is still allowed here
            # (a real close of dust needs a reduce-only order; this is the one optimistic assumption).
            if delta == 0 or (not closing and abs(delta) * market.mid < MIN_ORDER_USD):
                continue
            trades.append((coin, delta, target))
    return trades


def unreplicable(targets: dict[str, float], markets: dict[str, Market]) -> dict[str, float]:
    """Targets the exchange's lot size or $10 minimum make impossible to hold: coin -> target notional.

    Small books cannot mirror small slices of a big trader's portfolio; this is where tracking
    error comes from with little capital, so it is reported rather than silently dropped."""
    out = {}
    for coin, target in targets.items():
        market = markets.get(coin)
        if market is None or target == 0:
            continue
        if abs(target) < MIN_ORDER_USD or market.lot(target / market.mid) == 0:
            out[coin] = target
    return out


def execute(book: Book, coin: str, size: float, market: Market, reason: dict) -> Fill:
    """Simulated taker fill: impact price, taker fee, all charged to the book's cash."""
    price = market.fill_price(buying=size > 0)
    notional = abs(size) * price
    fee = notional * TAKER_FEE
    book.cash -= size * price + fee
    new_size = book.positions.get(coin, 0.0) + size
    if abs(new_size * market.mid) < 1e-6:
        book.positions.pop(coin, None)
    else:
        book.positions[coin] = new_size
    return Fill(coin, size, price, fee, abs(price - market.mid) * abs(size), reason)


def funding_payments(book: Book, markets: dict[str, Market]) -> dict[str, float]:
    """One hour of funding (official formula: size * oracle price * rate). Positive = book pays."""
    paid = {}
    for coin, size in book.positions.items():
        market = markets.get(coin)
        if market is None:
            continue
        payment = size * market.oracle * market.funding
        book.cash -= payment
        paid[coin] = payment
    return paid
