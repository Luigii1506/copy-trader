"""SQLite persistence for paper trading: current state plus an append-only audit log.

Every state change happens inside one transaction per engine step, so a crash never leaves a
book half-updated. `events` answers "why did the system do this?" (proyect.md section 30).
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any

from collector.storage import DATA_DIR

from .book import Book

DB_PATH = DATA_DIR / "papertrade" / "papertrade.db"

SCHEMA = """
create table if not exists strategies (
    name text primary key,
    config text not null,
    started_at text not null,
    status text not null,               -- active | halted
    cash_pool real not null,            -- capital not assigned to any book
    peak_equity real not null,
    last_rebalance text
);
create table if not exists books (
    id integer primary key,
    strategy text not null,
    trader text not null,
    cash real not null,
    opened_at text not null,
    closed_at text,
    selection text                      -- json: signal value and rank when selected
);
create unique index if not exists one_open_book on books(strategy, trader) where closed_at is null;
create table if not exists positions (
    book_id integer not null references books(id),
    coin text not null,
    size real not null,
    primary key (book_id, coin)
);
create table if not exists events (
    id integer primary key,
    ts text not null,
    strategy text not null,
    trader text,
    kind text not null,                 -- trade | funding | open_book | close_book | rebalance | halt | unreplicable | risk_pause
    coin text,
    size real,
    price real,
    fee real,
    cash_delta real,
    detail text                         -- json
);
create index if not exists events_ts on events(ts);
create table if not exists book_equity (
    ts text not null,
    book_id integer not null references books(id),
    equity real not null,
    gross real not null,
    trader_equity real,                 -- the copied trader's total account value at the same time
    trader_pnl real,                    -- the trader's cumulative all-time PnL (includes spot)
    trader_perp_pnl real,               -- the trader's cumulative perp PnL: what the book copies
    primary key (ts, book_id)
);
create table if not exists flags (
    id integer primary key,
    ts text not null,
    trader text not null,
    rule text not null,
    value real,
    detail text
);
create index if not exists flags_trader on flags(trader, ts);
create table if not exists equity (
    ts text not null,
    strategy text not null,
    equity real not null,
    cash_pool real not null,
    gross real not null,
    books integer not null,
    primary key (ts, strategy)
);
"""


class Store:
    def __init__(self, path: Path = DB_PATH):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path)
        self.db.row_factory = sqlite3.Row
        self.db.execute("pragma journal_mode=wal")
        self.db.executescript(SCHEMA)
        # Migrations, each idempotent. 2026-10-07: trader cumulative PnL next to their equity.
        # 2026-10-08: perp-only PnL - allTime PnL includes spot holdings we never copy, which made
        # books look like they "beat" traders whose losses were really spot tokens falling.
        for column in ("trader_pnl", "trader_perp_pnl"):
            try:
                self.db.execute(f"alter table book_equity add column {column} real")
            except sqlite3.OperationalError:
                pass  # column already exists

    def close(self) -> None:
        self.db.close()

    # --- strategies ---

    def ensure_strategy(self, name: str, config: dict, capital: float, now: datetime) -> None:
        self.db.execute(
            "insert or ignore into strategies(name, config, started_at, status, cash_pool, peak_equity) "
            "values (?, ?, ?, 'active', ?, ?)", (name, json.dumps(config), now.isoformat(), capital, capital))

    def strategy(self, name: str) -> sqlite3.Row:
        return self.db.execute("select * from strategies where name = ?", (name,)).fetchone()

    def update_strategy(self, name: str, **fields: Any) -> None:
        cols = ", ".join(f"{k} = ?" for k in fields)
        self.db.execute(f"update strategies set {cols} where name = ?", (*fields.values(), name))

    # --- books ---

    def open_books(self, strategy: str) -> list[tuple[int, Book]]:
        rows = self.db.execute("select * from books where strategy = ? and closed_at is null", (strategy,)).fetchall()
        result = []
        for row in rows:
            positions = {p["coin"]: p["size"] for p in
                         self.db.execute("select coin, size from positions where book_id = ?", (row["id"],))}
            result.append((row["id"], Book(strategy, row["trader"], row["cash"], positions)))
        return result

    def create_book(self, strategy: str, trader: str, cash: float, now: datetime, selection: dict) -> int:
        cur = self.db.execute(
            "insert into books(strategy, trader, cash, opened_at, selection) values (?, ?, ?, ?, ?)",
            (strategy, trader, cash, now.isoformat(), json.dumps(selection)))
        return cur.lastrowid

    def save_book(self, book_id: int, book: Book) -> None:
        self.db.execute("update books set cash = ? where id = ?", (book.cash, book_id))
        self.db.execute("delete from positions where book_id = ?", (book_id,))
        self.db.executemany("insert into positions(book_id, coin, size) values (?, ?, ?)",
                            [(book_id, c, s) for c, s in book.positions.items()])

    def close_book(self, book_id: int, now: datetime) -> None:
        self.db.execute("update books set closed_at = ? where id = ?", (now.isoformat(), book_id))

    def followed_traders(self) -> set[str]:
        return {r[0] for r in self.db.execute(
            "select distinct trader from books b join strategies s on s.name = b.strategy "
            "where b.closed_at is null and s.status = 'active'")}

    # --- log ---

    def event(self, now: datetime, strategy: str, kind: str, trader: str | None = None, coin: str | None = None,
              size: float | None = None, price: float | None = None, fee: float | None = None,
              cash_delta: float | None = None, **detail: Any) -> None:
        self.db.execute(
            "insert into events(ts, strategy, trader, kind, coin, size, price, fee, cash_delta, detail) "
            "values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (now.isoformat(), strategy, trader, kind, coin, size, price, fee, cash_delta,
             json.dumps(detail) if detail else None))

    def day_start_equity(self, strategy: str, midnight_iso: str) -> float | None:
        """Equity at the UTC day boundary: the last snapshot at or before midnight, else the day's first."""
        row = self.db.execute("select equity from equity where strategy = ? and ts <= ? order by ts desc limit 1",
                              (strategy, midnight_iso)).fetchone()
        if row is None:
            row = self.db.execute("select equity from equity where strategy = ? and ts > ? order by ts limit 1",
                                  (strategy, midnight_iso)).fetchone()
        return row["equity"] if row else None

    def snapshot(self, now: datetime, strategy: str, equity: float, cash_pool: float, gross: float, books: int) -> None:
        self.db.execute("insert or replace into equity values (?, ?, ?, ?, ?, ?)",
                        (now.isoformat(), strategy, equity, cash_pool, gross, books))

    def add_flag(self, now: datetime, trader: str, rule: str, value: float, detail: dict) -> None:
        self.db.execute("insert into flags(ts, trader, rule, value, detail) values (?, ?, ?, ?, ?)",
                        (now.isoformat(), trader, rule, value, json.dumps(detail)))

    def flagged(self, since: datetime) -> dict[str, str]:
        """trader -> latest actionable rule, for flags raised at or after `since`.
        Rules prefixed `watch:` are observations below the evidence threshold and do not block."""
        rows = self.db.execute("select trader, rule from flags where ts >= ? and rule not like 'watch:%' order by ts",
                               (since.isoformat(),))
        return {r["trader"]: r["rule"] for r in rows}

    def snapshot_book(self, now: datetime, book_id: int, equity: float, gross: float,
                      trader_equity: float | None, trader_pnl: float | None = None,
                      trader_perp_pnl: float | None = None) -> None:
        """Per-book curve next to the trader's own: the tracking error of copying is their difference.
        trader_perp_pnl (cumulative, perps only) is the comparable side: equity moves with deposits,
        and all-time PnL includes spot holdings the book never mirrors."""
        self.db.execute(
            "insert or replace into book_equity(ts, book_id, equity, gross, trader_equity, trader_pnl, trader_perp_pnl) "
            "values (?, ?, ?, ?, ?, ?, ?)",
            (now.isoformat(), book_id, equity, gross, trader_equity, trader_pnl, trader_perp_pnl))

    def commit(self) -> None:
        self.db.commit()
