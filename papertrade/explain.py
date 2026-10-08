"""`copy-trader explain <address>`: why does this trader rank where they do? (plan section 47)

Everything comes from the same functions the engine uses, so the explanation cannot drift from
the decision: candidate_signals (pool filters, curve signals, TraderScore, v2 exclusions) plus
behavior_features and copyability from fills when we have them.
"""

from __future__ import annotations

import polars as pl

from analysis.behavior import behavior_features
from analysis.score import WEIGHTS
from collector.storage import utcnow

from . import selection
from .store import DB_PATH, Store


def _fmt(value, kind: str = "num") -> str:
    if value is None:
        return "—"
    if kind == "pct":
        return f"{value:+.1%}"
    if kind == "share":
        return f"{value:.0%}"
    if isinstance(value, float):
        return f"{value:.3g}"
    return str(value)


def explain(address: str) -> str:
    address = address.lower()
    now = utcnow()
    out = [f"trader {address}"]
    pool = selection.candidate_signals(now)
    row = pool.filter(pl.col("user") == address)
    if row.is_empty():
        out.append("  no está en el pool elegible: puede faltar historia (≥4 pasos de 2 semanas), tener\n"
                   "  cuenta < $10k, un paso de ±100 % (leverage no replicable), ser vault, o ser HFT.")
        return "\n".join(out)
    r = row.to_dicts()[0]
    scored = pool.filter(pl.col("trader_score").is_not_null()).sort("trader_score", descending=True)
    rank = scored["user"].to_list().index(address) + 1 if address in scored["user"].to_list() else None
    sharpe_rank = (pool.filter(pl.col("sharpe").is_finite()).sort("sharpe", descending=True)["user"]
                   .to_list().index(address) + 1) if r["sharpe"] is not None and r["sharpe"] == r["sharpe"] else None

    out.append(f"  capital ${r['account_value']:,.0f} · pool elegible: {pool.height:,} traders")
    out.append(f"  TraderScore v1: {_fmt(r['trader_score'])} (puesto {rank or '—'}) · "
               f"Sharpe: puesto {sharpe_rank or '—'}")
    out.append("  componentes (12 semanas):")
    labels = {"sharpe": ("Sharpe", "num"), "low_dd": ("max drawdown", "pct"), "consistency": ("pasos con ganancia", "share"),
              "n_obs": ("pasos observados", "num"), "stability": ("estabilidad", "pct")}
    for c, w in WEIGHTS.items():
        name, kind = labels[c]
        out.append(f"    {name:20} {_fmt(r[c], kind):>10}   peso {w:.0%}")
    out.append(f"    {'retorno 12 sem':20} {_fmt(r['ret'], 'pct'):>10}")
    if r.get("behavior_known"):
        out.append(f"  penalización de comportamiento: −{r.get('behavior_penalty') or 0:.0f} pts")
    else:
        out.append("  comportamiento: sin fills todavía (penalización neutra)")
    if r.get("behavior_excluded"):
        out.append(f"  v2 (inactiva): EXCLUIDO por {r['exclusion_reason']}")

    fills = selection._read("fills")
    if fills is not None and fills.filter(pl.col("user") == address).height:
        tables = [t for t in (selection._read("equity_history"), selection._read("equity_census")) if t is not None]
        equity = pl.concat(tables, how="diagonal_relaxed").unique(subset=["user", "period", "time_ms"])
        b = behavior_features(fills.filter(pl.col("user") == address), equity.filter(pl.col("user") == address), now)
        if b.height:
            f = b.to_dicts()[0]
            out.append("  comportamiento (90 días, desde fills):")
            out.append(f"    operaciones {_fmt(f.get('n_trades'))} · win rate {_fmt(f.get('win_rate'), 'share')} · "
                       f"duración mediana {_fmt(f.get('median_duration_h'))} h")
            out.append(f"    leverage mediano {_fmt(f.get('median_leverage'))}x · p95 {_fmt(f.get('p95_leverage'))}x · "
                       f"liquidaciones {_fmt(f.get('liquidations'))}")
            out.append(f"    martingala {_fmt(f.get('martingale_share'), 'share')} · promedia a la baja "
                       f"{_fmt(f.get('avg_down_share'), 'share')} · moneda principal {_fmt(f.get('top_coin_share'), 'share')}")
            out.append(f"    copiabilidad estimada {_fmt(f.get('copyability_estimate'))}/100 · invisibles al sondeo "
                       f"{_fmt(f.get('invisible_share'), 'share')} · cortas (<15 min) {_fmt(f.get('short_trade_share'), 'share')}")

    if DB_PATH.exists():
        store = Store()
        try:
            books = store.db.execute(
                "select strategy, opened_at from books where trader = ? and closed_at is null", (address,)).fetchall()
            flags = store.db.execute(
                "select ts, rule, value from flags where trader = ? order by ts desc limit 5", (address,)).fetchall()
        finally:
            store.close()
        if books:
            out.append("  copiado ahora por: " + ", ".join(f"{b['strategy']} (desde {b['opened_at'][:10]})" for b in books))
        for fl in flags:
            out.append(f"  señal {fl['ts'][:16]}: {fl['rule']} = {fl['value']:.3g}")
    return "\n".join(out)


def main(address: str) -> int:
    print(explain(address))
    return 0
