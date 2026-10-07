"""Human-readable paper-trading status: `copy-trader papertrade-status`."""

from __future__ import annotations

from .store import DB_PATH, Store


def main() -> int:
    if not DB_PATH.exists():
        print("paper trading has not started yet")
        return 0
    store = Store()
    rows = store.db.execute("""
        select s.name, s.status, s.started_at, json_extract(s.config, '$.capital') capital, s.peak_equity,
               e.ts, e.equity, e.gross, e.books
        from strategies s
        left join equity e on e.strategy = s.name and e.ts = (select max(ts) from equity where strategy = s.name)
        order by e.equity desc""").fetchall()
    print(f"{'strategy':16} {'status':8} {'equity':>11} {'return':>8} {'drawdown':>9} {'leverage':>8} {'books':>5}")
    for r in rows:
        equity = r["equity"] if r["equity"] is not None else r["capital"]
        lev = (r["gross"] or 0) / equity if equity else 0
        print(f"{r['name']:16} {r['status']:8} {equity:11,.2f} {equity / r['capital'] - 1:8.2%} "
              f"{1 - equity / r['peak_equity']:9.2%} {lev:7.2f}x {r['books'] or 0:5}")
    trades, fees = store.db.execute("select count(*), coalesce(sum(fee), 0) from events where kind = 'trade'").fetchone()
    funding = store.db.execute("select coalesce(sum(cash_delta), 0) from events where kind = 'funding'").fetchone()[0]
    last = store.db.execute("select max(ts) from equity").fetchone()[0]
    print(f"\ntrades: {trades}   fees: ${fees:,.2f}   funding: ${funding:,.2f}   last snapshot: {last}")
    store.close()
    return 0
