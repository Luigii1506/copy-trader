"""Tracking error: what copying actually costs (the open consequence in ADR-002).

For every book, its equity snapshots sit next to the copied trader's cumulative PnL and equity
at the same moments. Per hourly step:

    trader return = dPnL / trader_equity_at_start     (PnL diffs: deposits and withdrawals out)
    book return   = dEquity / book_equity_at_start

Their running difference is the cost of mirroring: polling lag, our taker fees vs their maker
fills and volume discounts, funding timing, and slices too small to replicate. This number is
what turns backtest returns into live expectations, and it calibrates the backtest's
`friction_per_step`. Snapshots from before 2026-10-07 lack trader_pnl and are skipped.
"""

from __future__ import annotations

from .store import DB_PATH, Store


def report(store: Store) -> list[dict]:
    """One row per book with enough clean history: compounded returns and the tracking gap."""
    rows = store.db.execute("""
        select b.id book_id, b.strategy, b.trader, e.ts, e.equity, e.trader_equity, e.trader_pnl
        from book_equity e join books b on b.id = e.book_id
        where e.trader_pnl is not null and e.trader_equity > 0 and e.equity > 0
        order by b.id, e.ts""").fetchall()
    series: dict[int, list] = {}
    for r in rows:
        series.setdefault(r["book_id"], []).append(r)
    out = []
    for book_id, points in series.items():
        hourly = {p["ts"][:13]: p for p in points}          # last snapshot of each UTC hour
        steps = sorted(hourly.values(), key=lambda p: p["ts"])
        if len(steps) < 3:
            continue
        book_growth, trader_growth, diffs = 1.0, 1.0, []
        for a, b in zip(steps, steps[1:]):
            book_ret = b["equity"] / a["equity"] - 1
            trader_ret = (b["trader_pnl"] - a["trader_pnl"]) / a["trader_equity"]
            book_growth *= 1 + book_ret
            trader_growth *= 1 + trader_ret
            diffs.append(book_ret - trader_ret)
        n = len(diffs)
        mean_gap = sum(diffs) / n
        te = (sum((d - mean_gap) ** 2 for d in diffs) / (n - 1)) ** 0.5 if n > 1 else 0.0
        first, last = steps[0], steps[-1]
        out.append({
            "strategy": first["strategy"], "trader": first["trader"], "hours": n,
            "book_ret": book_growth - 1, "trader_ret": trader_growth - 1,
            "gap": (book_growth - 1) - (trader_growth - 1),
            "gap_per_day": mean_gap * 24,
            "tracking_error_hourly": te,
            "since": first["ts"][:16], "until": last["ts"][:16],
        })
    return sorted(out, key=lambda r: (r["strategy"], r["trader"]))


def main() -> int:
    if not DB_PATH.exists():
        print("paper trading has not started yet")
        return 0
    store = Store()
    try:
        rows = report(store)
    finally:
        store.close()
    if not rows:
        print("aún no hay historia limpia (trader_pnl se captura desde 2026-10-07); reintenta en unos días")
        return 0
    print(f"{'estrategia':16} {'trader':14} {'horas':>5} {'libro':>8} {'trader':>8} {'brecha':>8} {'brecha/día':>10}")
    for r in rows:
        print(f"{r['strategy']:16} {r['trader'][:12]}… {r['hours']:5} {r['book_ret']:8.2%} "
              f"{r['trader_ret']:8.2%} {r['gap']:8.2%} {r['gap_per_day']:10.3%}")
    gaps = [r["gap_per_day"] for r in rows]
    print(f"\nbrecha mediana por día: {sorted(gaps)[len(gaps) // 2]:.3%} "
          f"(backtest asume friction_per_step 0.25% por 2 semanas ≈ 0.018%/día)")
    return 0
