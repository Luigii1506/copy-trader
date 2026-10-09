"""Tracking error: what copying actually costs (the open consequence in ADR-002).

For every book, its equity snapshots sit next to the copied trader's cumulative PnL and equity
at the same moments. Per hourly step:

    trader return = dPerpPnL / trader_equity_at_start (perp PnL diffs: deposits and spot out)
    target return = trader return x leverage_scale     (the cap shrinks copies of >5x traders on purpose)
    book return   = dEquity / book_equity_at_start

Their running difference is the cost of mirroring: polling lag, our taker fees vs their maker
fills and volume discounts, funding timing, and slices too small to replicate. This number is
what turns backtest returns into live expectations, and it calibrates the backtest's
`friction_per_step`. Only snapshots with trader_perp_pnl count (captured from 2026-10-08):
the earlier all-time PnL included spot tokens the book never holds.
"""

from __future__ import annotations

from .store import DB_PATH, Store


def report(store: Store) -> list[dict]:
    """One row per book with enough clean history: compounded returns and the tracking gap."""
    rows = store.db.execute("""
        select b.id book_id, b.strategy, b.trader, e.ts, e.equity, e.trader_equity,
               e.trader_perp_pnl trader_pnl, coalesce(e.leverage_scale, 1.0) leverage_scale
        from book_equity e join books b on b.id = e.book_id
        where e.trader_perp_pnl is not null and e.trader_equity > 0 and e.equity > 0
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
        book_growth, trader_growth, target_growth, diffs, scales = 1.0, 1.0, 1.0, [], []
        for a, b in zip(steps, steps[1:]):
            book_ret = b["equity"] / a["equity"] - 1
            trader_ret = (b["trader_pnl"] - a["trader_pnl"]) / a["trader_equity"]
            target_ret = trader_ret * a["leverage_scale"]
            book_growth *= 1 + book_ret
            trader_growth *= 1 + trader_ret
            target_growth *= 1 + target_ret
            diffs.append(book_ret - target_ret)
            scales.append(a["leverage_scale"])
        n = len(diffs)
        mean_gap = sum(diffs) / n
        te = (sum((d - mean_gap) ** 2 for d in diffs) / (n - 1)) ** 0.5 if n > 1 else 0.0
        first, last = steps[0], steps[-1]
        out.append({
            "strategy": first["strategy"], "trader": first["trader"], "hours": n,
            "book_ret": book_growth - 1, "trader_ret": trader_growth - 1, "target_ret": target_growth - 1,
            "gap": (book_growth - 1) - (target_growth - 1),
            "active": any(abs(x) > 1e-9 for x in diffs) or abs(trader_growth - 1) > 1e-4,
            "min_scale": min(scales),
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
        print("aún no hay historia limpia (PnL de perps del trader se captura desde 2026-10-08); reintenta en unos días")
        return 0
    active = [r for r in rows if r["active"]]
    print(f"{len(rows)} libros con historia limpia; {len(active)} con movimiento (los demás: trader sin posiciones)\n")
    print(f"{'estrategia':16} {'trader':14} {'horas':>5} {'escala':>6} {'libro':>8} {'objetivo':>9} {'brecha':>8} {'brecha/día':>10}")
    for r in active:
        print(f"{r['strategy']:16} {r['trader'][:12]}… {r['hours']:5} {r['min_scale']:6.2f} {r['book_ret']:8.2%} "
              f"{r['target_ret']:9.2%} {r['gap']:8.2%} {r['gap_per_day']:10.3%}")
    if active:
        gaps = sorted(r["gap_per_day"] for r in active)
        print(f"\nbrecha mediana por día (libros activos): {gaps[len(gaps) // 2]:.3%} "
              f"(backtest asume ≈ -0.018%/día). Objetivo = retorno del trader × escala del tope de leverage.")
    return 0
