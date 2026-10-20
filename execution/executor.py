"""Mirror one paper strategy's portfolio into a real Hyperliquid account, behind an independent guard.

The executor never selects traders. Each step:
  1. read the paper strategy's open books (papertrade.db, read-only) and turn them into exposure
     fractions: coin notional / strategy equity, valued at reference (mainnet) prices
  2. scale those fractions to the real account's equity -> target notionals
  3. guard: kill file, daily-loss halt, main-dex-only, gross leverage cap, per-order cap
  4. plan orders with the same band/lot/minimum rules as the paper engine (papertrade.book)
  5. send them as IOC orders, or only log them in dry-run mode
Every intended order, sent or not, goes to execution.db with its reason.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from papertrade.book import Book, Market, plan_trades
from papertrade.store import DB_PATH as PAPER_DB_PATH

from .config import DB_PATH, KILL_FILE, ExecConfig

log = logging.getLogger(__name__)

SCHEMA = """
create table if not exists orders (
    id integer primary key, ts text not null, coin text not null, size real not null,
    mid real, notional real, reduce_only integer, dry_run integer, status text, detail text
);
create table if not exists equity (ts text primary key, equity real, gross real, halted integer);
create table if not exists state (key text primary key, value text);
"""


@dataclass
class StepResult:
    equity: float
    targets: dict[str, float]
    orders: list[dict] = field(default_factory=list)
    blocked: list[str] = field(default_factory=list)
    halted: bool = False


def paper_exposure(paper_db: Path, strategy: str, reference: dict[str, Market]) -> dict[str, float]:
    """coin -> signed notional / strategy equity, from the paper engine's current books."""
    db = sqlite3.connect(f"file:{paper_db}?mode=ro", uri=True)
    db.row_factory = sqlite3.Row
    try:
        row = db.execute("select cash_pool from strategies where name = ?", (strategy,)).fetchone()
        if row is None:
            raise RuntimeError(f"paper strategy '{strategy}' not found")
        books = db.execute("select id, cash from books where strategy = ? and closed_at is null", (strategy,)).fetchall()
        sizes: dict[str, float] = {}
        equity = row["cash_pool"]
        for b in books:
            equity += b["cash"]
            for p in db.execute("select coin, size from positions where book_id = ?", (b["id"],)):
                sizes[p["coin"]] = sizes.get(p["coin"], 0.0) + p["size"]
                if p["coin"] in reference:
                    equity += p["size"] * reference[p["coin"]].mid
    finally:
        db.close()
    if equity <= 0:
        return {}
    return {c: s * reference[c].mid / equity for c, s in sizes.items() if c in reference and s}


class Executor:
    def __init__(self, client, config: ExecConfig = ExecConfig(), db_path: Path = DB_PATH,
                 paper_db: Path = PAPER_DB_PATH, kill_file: Path = KILL_FILE, reference_markets=None):
        self.client, self.config = client, config
        self.paper_db, self.kill_file = paper_db, kill_file
        self.reference_markets = reference_markets   # callable -> mainnet markets (testnet prices differ)
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(db_path)
        self.db.executescript(SCHEMA)

    # --- state helpers ---

    def _get(self, key: str) -> str | None:
        row = self.db.execute("select value from state where key = ?", (key,)).fetchone()
        return row[0] if row else None

    def _set(self, key: str, value: str) -> None:
        self.db.execute("insert or replace into state values (?, ?)", (key, value))

    def _log_order(self, now: datetime, coin: str, size: float, market: Market, reduce_only: bool,
                   status: str, detail: dict) -> None:
        self.db.execute(
            "insert into orders(ts, coin, size, mid, notional, reduce_only, dry_run, status, detail) "
            "values (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (now.isoformat(), coin, size, market.mid, abs(size) * market.mid, int(reduce_only),
             int(self.config.dry_run), status, json.dumps(detail, default=str)))

    # --- guard ---

    def _daily_loss_hit(self, now: datetime, equity: float) -> bool:
        day = f"{now:%Y-%m-%d}"
        if self._get("day") != day:
            self._set("day", day)
            self._set("day_start_equity", str(equity))
            return False
        start = float(self._get("day_start_equity") or equity)
        return equity < start * (1 - self.config.daily_loss_halt)

    def halt(self, now: datetime, reason: str) -> StepResult:
        """Close every position with reduce-only orders and leave the kill file in place."""
        equity, positions = self.client.account_state()
        markets = self.client.markets()
        result = StepResult(equity=equity, targets={}, halted=True)
        for coin, size in positions.items():
            market = markets.get(coin)
            if market is None:
                result.blocked.append(f"{coin}: no market to close")
                continue
            self._send(now, coin, -size, market, reduce_only=True, detail={"halt": reason}, result=result)
        self.kill_file.parent.mkdir(parents=True, exist_ok=True)
        self.kill_file.write_text(f"{now.isoformat()} {reason}\n")
        self._set("halted", reason)
        self.db.commit()
        log.warning("execution HALTED: %s", reason)
        return result

    # --- one step ---

    def step(self, now: datetime) -> StepResult:
        if self.kill_file.exists():
            if self._get("halted") is None:
                return self.halt(now, "kill file")
            equity, _ = self.client.account_state()
            return StepResult(equity=equity, targets={}, halted=True, blocked=["halted: remove the kill file to resume"])

        equity, positions = self.client.account_state()
        markets = self.client.markets()
        if self._daily_loss_hit(now, equity):
            return self.halt(now, f"daily loss over {self.config.daily_loss_halt:.0%}")

        reference = self.reference_markets() if self.reference_markets else markets
        fractions = paper_exposure(self.paper_db, self.config.source_strategy, reference)
        blocked: list[str] = []
        if self.config.main_dex_only:
            for coin in [c for c in fractions if ":" in c]:
                blocked.append(f"{coin}: HIP-3 skipped (main_dex_only)")
                fractions.pop(coin)
        targets = {c: f * equity for c, f in fractions.items() if c in markets}
        gross = sum(abs(t) for t in targets.values())
        cap = self.config.max_gross_leverage * equity
        if gross > cap > 0:
            blocked.append(f"gross {gross:,.0f} over {self.config.max_gross_leverage}x cap; scaled to {cap:,.0f}")
            targets = {c: t * cap / gross for c, t in targets.items()}

        result = StepResult(equity=equity, targets=targets, blocked=blocked)
        real = Book("real", "account", 0.0, dict(positions))
        for coin, delta, target in plan_trades(real, targets, markets):
            market = markets[coin]
            current = positions.get(coin, 0.0)
            reduce_only = abs(current + delta) < abs(current) and current * (current + delta) >= 0
            if abs(delta) * market.mid > self.config.max_order_usd:
                capped = market.lot(self.config.max_order_usd / market.mid) * (1 if delta > 0 else -1)
                result.blocked.append(f"{coin}: order {abs(delta) * market.mid:,.0f} USD capped at "
                                      f"{self.config.max_order_usd:,.0f} (rest next step)")
                delta = capped
            if delta == 0 or abs(delta) * market.mid < self.config.min_order_usd:
                continue
            self._send(now, coin, delta, market, reduce_only,
                       {"target_notional": target, "current_size": current}, result)
        self.db.execute("insert or replace into equity values (?, ?, ?, ?)",
                        (now.isoformat(), equity, sum(abs(s) * markets[c].mid for c, s in positions.items()
                                                      if c in markets), 0))
        self.db.commit()
        return result

    def _send(self, now: datetime, coin: str, size: float, market: Market, reduce_only: bool,
              detail: dict, result: StepResult) -> None:
        order = {"coin": coin, "size": size, "notional": abs(size) * market.mid, "reduce_only": reduce_only}
        if self.config.dry_run:
            self._log_order(now, coin, size, market, reduce_only, "dry_run", detail)
            result.orders.append(order | {"status": "dry_run"})
            return
        try:
            response = self.client.market_order(coin, size, self.config.slippage, reduce_only)
            status = "sent" if (response or {}).get("status") == "ok" else "rejected"
            self._log_order(now, coin, size, market, reduce_only, status, detail | {"response": response})
            result.orders.append(order | {"status": status})
        except Exception as exc:
            log.exception("order %s %s failed", coin, size)
            self._log_order(now, coin, size, market, reduce_only, "error", detail | {"error": str(exc)})
            result.orders.append(order | {"status": "error"})
