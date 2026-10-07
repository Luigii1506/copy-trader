"""Paper-trading engine: mirrors followed traders into simulated books, one step per minute.

Each step: read followed traders' positions on every perp dex they use, compute each book's
target (papertrade.book.target_notionals), trade only where the gap is worth it, charge funding
every hour, snapshot equity, enforce kill switches, and re-select traders when a strategy's
rebalance is due. Everything is persisted per step (papertrade.store).
"""

from __future__ import annotations

import logging
import random
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta

import polars as pl

from collector.hyperliquid import HyperliquidClient
from collector.storage import DATA_DIR, utcnow

from . import risk, selection, watch
from .book import Book, Market, execute, funding_payments, plan_trades, target_notionals, unreplicable
from .config import (
    DAILY_LOSS_PAUSE,
    DEX_RESCAN,
    EQUITY_REFRESH,
    FLAG_TTL,
    WATCH_INTERVAL,
    MIN_BOOK_TRADER_EQUITY,
    POLL_INTERVAL,
    SNAPSHOT_INTERVAL,
    STRATEGIES,
    Strategy,
)
from .store import Store

log = logging.getLogger(__name__)

KILL_FILE = DATA_DIR / "papertrade" / "KILL"


def dex_of(coin: str) -> str:
    return coin.split(":", 1)[0] if ":" in coin else ""


@dataclass
class TraderView:
    sizes: dict[str, float] = field(default_factory=dict)       # coin -> signed size (as last read)
    notionals: dict[str, float] = field(default_factory=dict)   # coin -> signed notional at this step's mid
    dexs: set[str] = field(default_factory=lambda: {""})          # dexs where they hold positions
    equity: float | None = None                                   # total account value (portfolio)
    pnl: float | None = None                                      # cumulative all-time PnL (portfolio)
    equity_at: datetime | None = None
    scanned_at: datetime | None = None
    ok: bool = False                                              # this step's data is complete


class Engine:
    def __init__(self, client: HyperliquidClient, store: Store, strategies: list[Strategy] = STRATEGIES):
        self.client, self.store, self.strategies = client, store, strategies
        self.traders: dict[str, TraderView] = {}
        self.all_dexs: list[str] = []
        self.last_snapshot: datetime | None = None
        self.last_funding_hour: datetime | None = self._last_funding_hour()
        self.candidates: tuple[str, pl.DataFrame] | None = None   # (day, signals)
        self.unreplicable_seen: dict[int, dict[str, float]] = {}  # book id -> last reported impossible targets
        self.last_watch: datetime | None = None
        self.pause_logged: set[tuple[str, str]] = set()           # (strategy, UTC day) already logged

    # --- market and trader data ---

    def markets(self, dexs: set[str]) -> dict[str, Market]:
        out = {}
        for dex in sorted(dexs):
            body = {"type": "metaAndAssetCtxs"} | ({"dex": dex} if dex else {})
            meta, ctxs = self.client.info(body)
            for asset, ctx in zip(meta["universe"], ctxs):
                if not ctx.get("midPx"):
                    continue
                impact = ctx.get("impactPxs") or [None, None]
                out[asset["name"]] = Market(
                    mid=float(ctx["midPx"]), oracle=float(ctx["oraclePx"]), funding=float(ctx["funding"]),
                    impact_bid=float(impact[0]) if impact[0] else None,
                    impact_ask=float(impact[1]) if impact[1] else None,
                    sz_decimals=asset.get("szDecimals"),
                )
        return out

    def refresh_trader(self, trader: str, now: datetime) -> None:
        view = self.traders.setdefault(trader, TraderView())
        view.ok = False
        rescan = view.scanned_at is None or now - view.scanned_at >= DEX_RESCAN
        dexs = set(self.all_dexs) if rescan else view.dexs
        sizes: dict[str, float] = {}
        held = {""}
        for dex in sorted(dexs):
            state = self.client.clearinghouse_state(trader, dex)
            for ap in state["assetPositions"]:
                size = float(ap["position"]["szi"])
                if size:
                    sizes[ap["position"]["coin"]] = size
                    held.add(dex)
        view.dexs = held
        first = view.equity_at is None
        if rescan:
            # Stagger the first refresh of each trader so the heavy calls don't all land on one step.
            view.scanned_at = now - (random.random() * DEX_RESCAN if first else timedelta(0))
        if first or now - view.equity_at >= EQUITY_REFRESH:
            all_time = dict(self.client.portfolio(trader))["allTime"]
            history = all_time["accountValueHistory"]
            pnl_history = all_time.get("pnlHistory") or []
            view.equity = float(history[-1][1]) if history else 0.0
            view.pnl = float(pnl_history[-1][1]) if pnl_history else None
            view.equity_at = now - (random.random() * EQUITY_REFRESH if first else timedelta(0))
        view.sizes = sizes
        view.ok = True

    # --- one step ---

    def step(self, now: datetime) -> None:
        for s in self.strategies:
            self.store.ensure_strategy(s.name, s.to_dict(), s.capital, now)

        if KILL_FILE.exists():
            for s in self.strategies:
                if self.store.strategy(s.name)["status"] == "active":
                    self.halt(s, now, reason="kill file")
            self.store.commit()
            return

        if not self.all_dexs:
            self.all_dexs = self.client.perp_dexs()

        # Rebalances first: they decide which traders we need to watch this step.
        due = [s for s in self.strategies if self._rebalance_due(s, now)]

        followed = self.store.followed_traders()
        if due:
            followed |= {t for s in due for t, _ in self._selection(s, now)}
        for trader in sorted(followed):
            try:
                self.refresh_trader(trader, now)
            except Exception:
                log.exception("trader %s: refresh failed; keeping the book unchanged this step", trader)
                self.traders.setdefault(trader, TraderView()).ok = False

        needed = {""} | {d for t in followed for d in self.traders.get(t, TraderView()).dexs}
        for s in self.strategies:
            for _, book in self.store.open_books(s.name):
                needed |= {dex_of(c) for c in book.positions}
        markets = self.markets(needed)
        for view in self.traders.values():
            view.notionals = {c: size * markets[c].mid for c, size in view.sizes.items() if c in markets}

        self._funding(now, markets)
        if self.last_watch is None or now - self.last_watch >= WATCH_INTERVAL:
            self._watch(followed, now, markets)
            self.last_watch = now
        for s in due:
            self.rebalance(s, now, markets)
        for s in self.strategies:
            if self.store.strategy(s.name)["status"] == "active":
                self._copy(s, now, markets)
        if self.last_snapshot is None or now - self.last_snapshot >= SNAPSHOT_INTERVAL:
            self._snapshot(now, markets)
            self.last_snapshot = now
        self.store.commit()

    # --- behavior watch ---

    def _watch(self, followed: set[str], now: datetime, markets: dict[str, Market]) -> None:
        try:
            hits = watch.run(followed, now)
        except Exception:
            log.exception("behavior watch failed; books unchanged")
            return
        for hit in hits:
            # Every hit is logged for calibration; only hits with enough trades block a trader.
            self.store.add_flag(now, hit["trader"], hit["rule"] if hit["actionable"] else f"watch:{hit['rule']}",
                                hit["value"], hit)
            log.warning("%s %s: %s (%s=%.3g > %s, %d trades)", "flag" if hit["actionable"] else "watch",
                        hit["trader"], hit["rule"], hit["column"], hit["value"], hit["limit"], hit["n_trades"])
        flagged = self.store.flagged(now - FLAG_TTL)
        for s in self.strategies:
            if self.store.strategy(s.name)["status"] != "active":
                continue
            for book_id, book in self.store.open_books(s.name):
                if book.trader in flagged:
                    self._close_book(s, book_id, book, now, markets, reason=f"behavior: {flagged[book.trader]}")

    # --- copying ---

    def _paused(self, s: Strategy, now: datetime, equity_now: float) -> bool:
        """Daily loss limit: after losing DAILY_LOSS_PAUSE in a UTC day, add no exposure until tomorrow."""
        midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
        base = self.store.day_start_equity(s.name, midnight.isoformat())
        if base is None or equity_now >= base * (1 - DAILY_LOSS_PAUSE):
            return False
        key = (s.name, f"{now:%Y-%m-%d}")
        if key not in self.pause_logged:
            self.pause_logged.add(key)
            self.store.event(now, s.name, "risk_pause", day_start_equity=base, equity=equity_now)
            log.warning("%s: daily loss %.1f%% exceeds %.0f%%; no new exposure until tomorrow",
                        s.name, (1 - equity_now / base) * 100, DAILY_LOSS_PAUSE * 100)
        return True

    def _copy(self, s: Strategy, now: datetime, markets: dict[str, Market]) -> None:
        books = self.store.open_books(s.name)
        equity_now = self.store.strategy(s.name)["cash_pool"] + sum(b.equity(markets) for _, b in books)
        paused = self._paused(s, now, equity_now)
        for book_id, book in books:
            view = self.traders.get(book.trader)
            if view is None or not view.ok:
                continue
            if (view.equity or 0) < MIN_BOOK_TRADER_EQUITY:
                self._close_book(s, book_id, book, now, markets, reason=f"trader equity {view.equity:.0f} below minimum")
                continue
            targets, scale = target_notionals(view.notionals, view.equity, book.equity(markets), s.max_leverage)
            impossible = unreplicable(targets, markets)
            if impossible != self.unreplicable_seen.get(book_id):
                self.unreplicable_seen[book_id] = impossible
                if impossible:
                    self.store.event(now, s.name, "unreplicable", book.trader, targets=impossible)
            for coin, delta, target in plan_trades(book, targets, markets):
                current = book.positions.get(coin, 0.0)
                if paused and abs(current + delta) > abs(current):
                    continue  # closes and reductions always go through; growth waits for tomorrow
                reason = {"trader_notional": view.notionals.get(coin, 0.0), "trader_equity": view.equity,
                          "target_notional": target, "leverage_scale": scale}
                fill = execute(book, coin, delta, markets[coin], reason)
                self.store.event(now, s.name, "trade", book.trader, coin, fill.size, fill.price, fill.fee,
                                 -(fill.size * fill.price + fill.fee), mid=markets[coin].mid,
                                 slippage_usd=fill.slippage_cost, **reason)
            self.store.save_book(book_id, book)

    def _close_book(self, s: Strategy, book_id: int, book: Book, now: datetime, markets: dict[str, Market],
                    reason: str) -> None:
        for coin, size in list(book.positions.items()):
            if coin not in markets:
                log.warning("%s/%s: no market for %s; position left open", s.name, book.trader, coin)
                continue
            fill = execute(book, coin, -size, markets[coin], {"close": reason})
            self.store.event(now, s.name, "trade", book.trader, coin, fill.size, fill.price, fill.fee,
                             -(fill.size * fill.price + fill.fee), mid=markets[coin].mid,
                             slippage_usd=fill.slippage_cost, close=reason)
        if book.positions:  # couldn't price something: keep the book open rather than lose the position
            self.store.save_book(book_id, book)
            return
        pool = self.store.strategy(s.name)["cash_pool"] + book.cash
        self.store.update_strategy(s.name, cash_pool=pool)
        book.cash = 0.0
        self.store.save_book(book_id, book)
        self.store.close_book(book_id, now)
        self.store.event(now, s.name, "close_book", book.trader, reason=reason)

    # --- selection and rebalancing ---

    def _selection(self, s: Strategy, now: datetime) -> list[tuple[str, float]]:
        day = f"{now:%Y-%m-%d}"
        if self.candidates is None or self.candidates[0] != day:
            self.candidates = (day, selection.candidate_signals(now))
        return selection.select(s, self.candidates[1], now)

    def _rebalance_due(self, s: Strategy, now: datetime) -> bool:
        row = self.store.strategy(s.name)
        if row is None or row["status"] != "active":
            return False
        last = row["last_rebalance"]
        return last is None or now - datetime.fromisoformat(last) >= timedelta(days=s.rebalance_days)

    def rebalance(self, s: Strategy, now: datetime, markets: dict[str, Market]) -> None:
        flagged = self.store.flagged(now - FLAG_TTL)
        chosen = [(t, v) for t, v in self._selection(s, now) if t not in flagged]
        if not chosen:
            log.warning("%s: no eligible traders; rebalance postponed", s.name)
            return
        chosen_set = {t for t, _ in chosen}
        books = self.store.open_books(s.name)
        for book_id, book in books:
            if book.trader not in chosen_set:
                self._close_book(s, book_id, book, now, markets, reason="not selected at rebalance")
        weights, correlated = risk.weights_for([t for t, _ in chosen])
        books = self.store.open_books(s.name)
        pool = self.store.strategy(s.name)["cash_pool"]
        total = pool + sum(b.equity(markets) for _, b in books)
        # Books that failed to close (unpriceable position) keep their equity; it is not reallocated.
        leftover = sum(b.equity(markets) for _, b in books if b.trader not in weights)
        allocatable = total - leftover
        for book_id, book in books:  # continuing traders: resize by moving cash
            weight = weights.get(book.trader)
            if weight is None:
                continue
            diff = allocatable * weight - book.equity(markets)
            book.cash += diff
            pool -= diff
            self.store.save_book(book_id, book)
        existing = {b.trader for _, b in books}
        for rank, (trader, value) in enumerate(chosen, 1):
            if trader in existing:
                continue
            cash = allocatable * weights[trader]
            self.store.create_book(s.name, trader, cash, now, {"signal": s.signal, "value": value, "rank": rank,
                                                               "weight": weights[trader]})
            pool -= cash
            self.store.event(now, s.name, "open_book", trader, cash_delta=cash, signal=s.signal, value=value,
                             rank=rank, weight=weights[trader])
        self.store.update_strategy(s.name, cash_pool=pool, last_rebalance=now.isoformat())
        self.store.event(now, s.name, "rebalance", traders=[t for t, _ in chosen], equity=total,
                         weights={u: round(w, 4) for u, w in weights.items()}, correlated=correlated)
        log.info("%s: rebalanced into %d traders, equity %.2f, cash %.0f%%, %d correlated groups",
                 s.name, len(chosen), total, max(0.0, 1 - sum(weights.values())) * 100, len(correlated))

    def halt(self, s: Strategy, now: datetime, reason: str, markets: dict[str, Market] | None = None) -> None:
        books = self.store.open_books(s.name)
        if markets is None:
            dexs = {""} | {dex_of(c) for _, b in books for c in b.positions}
            markets = self.markets(dexs)
        for book_id, book in books:
            self._close_book(s, book_id, book, now, markets, reason=f"halt: {reason}")
        self.store.update_strategy(s.name, status="halted")
        self.store.event(now, s.name, "halt", reason=reason)
        log.warning("%s: HALTED (%s)", s.name, reason)

    # --- funding and snapshots ---

    def _last_funding_hour(self) -> datetime | None:
        row = self.store.db.execute("select max(ts) from events where kind = 'funding'").fetchone()
        return datetime.fromisoformat(row[0]).replace(minute=0, second=0, microsecond=0) if row and row[0] else None

    def _funding(self, now: datetime, markets: dict[str, Market]) -> None:
        hour = now.replace(minute=0, second=0, microsecond=0)
        if self.last_funding_hour is None:
            self.last_funding_hour = hour  # start counting from the next full hour
            return
        hours = int((hour - self.last_funding_hour) / timedelta(hours=1))
        if hours <= 0:
            return
        # After downtime, missed hours are charged at the current rate; `hours` in the log flags it.
        for s in self.strategies:
            for book_id, book in self.store.open_books(s.name):
                if not book.positions:
                    continue
                paid: dict[str, float] = {}
                for _ in range(hours):
                    for coin, amount in funding_payments(book, markets).items():
                        paid[coin] = paid.get(coin, 0.0) + amount
                for coin, amount in paid.items():
                    self.store.event(now, s.name, "funding", book.trader, coin, book.positions.get(coin),
                                     markets[coin].oracle, None, -amount, rate=markets[coin].funding, hours=hours)
                self.store.save_book(book_id, book)
        self.last_funding_hour = hour

    def _snapshot(self, now: datetime, markets: dict[str, Market]) -> None:
        for s in self.strategies:
            row = self.store.strategy(s.name)
            open_books = self.store.open_books(s.name)
            for book_id, b in open_books:
                view = self.traders.get(b.trader)
                self.store.snapshot_book(now, book_id, b.equity(markets), b.gross(markets),
                                         view.equity if view else None, view.pnl if view else None)
            books = [b for _, b in open_books]
            equity = row["cash_pool"] + sum(b.equity(markets) for b in books)
            gross = sum(b.gross(markets) for b in books)
            self.store.snapshot(now, s.name, equity, row["cash_pool"], gross, len(books))
            peak = max(row["peak_equity"], equity)
            self.store.update_strategy(s.name, peak_equity=peak)
            if row["status"] == "active" and equity < peak * (1 - s.halt_drawdown):
                self.halt(s, now, f"drawdown {1 - equity / peak:.1%} from peak {peak:.2f}", markets)


def run_forever() -> None:
    client, store = HyperliquidClient(), Store()
    engine = Engine(client, store)
    log.info("papertrade: started with %d strategies", len(engine.strategies))
    try:
        while True:
            started = utcnow()
            try:
                engine.step(started)
            except Exception:
                log.exception("papertrade: step failed; retrying next interval")
                store.db.rollback()
            elapsed = (utcnow() - started).total_seconds()
            time.sleep(max(1.0, POLL_INTERVAL.total_seconds() - elapsed))
    finally:
        store.close()
        client.close()
