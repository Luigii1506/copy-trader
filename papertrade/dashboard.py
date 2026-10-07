"""Static HTML status page (proyect.md section 31).

`copy-trader dashboard` writes DATA_DIR/dashboard.html every 30 min (launchd). The laptop backup
copies it, so the page opens locally without SSH: ~/data/copy-trader-backup/dashboard.html.
Self-contained: no external scripts, works offline, light and dark via prefers-color-scheme.
"""

from __future__ import annotations

import html
import json
from datetime import datetime, timedelta

from collector import health
from collector.storage import DATA_DIR, read_json, utcnow

from .store import DB_PATH, Store

OUT_PATH = DATA_DIR / "dashboard.html"
SPARK_DAYS = 7

STYLE = """
:root { --surface:#fcfcfb; --ink:#0b0b0b; --ink-2:#52514e; --grid:#e5e4e0;
        --series:#2a78d6; --good:#0ca30c; --warn:#b97b00; --bad:#d03b3b; }
@media (prefers-color-scheme: dark) { :root:not([data-theme="light"]) {
  --surface:#1a1a19; --ink:#ffffff; --ink-2:#c3c2b7; --grid:#383835;
  --series:#3987e5; --good:#27b327; --warn:#d99a1c; --bad:#e66767; } }
body { background:var(--surface); color:var(--ink); font:14px/1.5 -apple-system,system-ui,sans-serif;
       margin:0 auto; max-width:860px; padding:24px 16px; }
h1 { font-size:20px; margin:0 0 2px; } h2 { font-size:15px; margin:28px 0 8px; }
.sub { color:var(--ink-2); font-size:12px; }
table { border-collapse:collapse; width:100%; }
th { text-align:left; color:var(--ink-2); font-weight:500; font-size:12px; padding:6px 10px 6px 0; }
td { padding:6px 10px 6px 0; border-top:1px solid var(--grid); font-variant-numeric:tabular-nums; }
.num { text-align:right; } th.num { text-align:right; }
.good { color:var(--good); } .warn { color:var(--warn); } .bad { color:var(--bad); }
svg { display:block; } .muted { color:var(--ink-2); }
"""


def sparkline(values: list[float], width: int = 150, height: int = 34) -> str:
    """Single-series equity sparkline: a 2px line, no axes (the table column names it)."""
    if len(values) < 2:
        return '<span class="muted">—</span>'
    lo, hi = min(values), max(values)
    span = (hi - lo) or 1.0
    pad = 3
    points = " ".join(
        f"{pad + i * (width - 2 * pad) / (len(values) - 1):.1f},"
        f"{height - pad - (v - lo) * (height - 2 * pad) / span:.1f}"
        for i, v in enumerate(values)
    )
    return (f'<svg width="{width}" height="{height}" role="img" aria-label="equity {lo:,.0f} a {hi:,.0f}">'
            f'<title>{lo:,.0f} → {hi:,.0f}</title>'
            f'<polyline points="{points}" fill="none" stroke="var(--series)" '
            f'stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>')


def pct(x: float | None, signed: bool = True) -> str:
    if x is None:
        return "—"
    cls = "good" if x > 0.0005 else ("bad" if x < -0.0005 else "muted")
    sign = "+" if signed and x > 0 else ""
    return f'<span class="{cls}">{sign}{x:.2%}</span>'


def strategies_section(store: Store, now: datetime) -> str:
    since = (now - timedelta(days=SPARK_DAYS)).isoformat()
    rows_html = []
    rows = store.db.execute("""
        select s.name, s.status, json_extract(s.config,'$.capital') capital, s.peak_equity,
               e.equity, e.gross, e.books
        from strategies s left join equity e
          on e.strategy = s.name and e.ts = (select max(ts) from equity where strategy = s.name)
        order by e.equity desc""").fetchall()
    for r in rows:
        equity = r["equity"] if r["equity"] is not None else r["capital"]
        curve = [row[0] for row in store.db.execute(
            "select equity from equity where strategy=? and ts>=? order by ts", (r["name"], since))]
        status_cls = "good" if r["status"] == "active" else "bad"
        rows_html.append(
            f'<tr><td>{html.escape(r["name"])}</td>'
            f'<td class="{status_cls}">{r["status"]}</td>'
            f'<td class="num">{equity:,.2f}</td>'
            f'<td class="num">{pct(equity / r["capital"] - 1)}</td>'
            f'<td class="num">{pct(-(1 - equity / r["peak_equity"]), signed=False)}</td>'
            f'<td class="num">{(r["gross"] or 0) / equity if equity else 0:.2f}x</td>'
            f'<td class="num">{r["books"] or 0}</td>'
            f'<td>{sparkline(curve)}</td></tr>')
    trades, fees = store.db.execute(
        "select count(*), coalesce(sum(fee),0) from events where kind='trade'").fetchone()
    funding = store.db.execute(
        "select coalesce(sum(cash_delta),0) from events where kind='funding'").fetchone()[0]
    return (
        '<h2>Estrategias (paper trading)</h2><table><tr>'
        '<th>estrategia</th><th>estado</th><th class="num">equity</th><th class="num">retorno</th>'
        '<th class="num">drawdown</th><th class="num">leverage</th><th class="num">libros</th>'
        f'<th>últimos {SPARK_DAYS} días</th></tr>' + "".join(rows_html) + "</table>"
        f'<p class="sub">{trades} operaciones simuladas · fees ${fees:,.2f} · funding ${funding:,.2f}</p>')


def events_section(store: Store) -> str:
    rows = store.db.execute(
        "select ts, strategy, trader, kind, detail from events "
        "where kind in ('halt','risk_pause','close_book','open_book','rebalance') or "
        "      (kind='trade' and 0) order by ts desc limit 12").fetchall()
    flags = store.db.execute("select ts, trader, rule, value from flags order by ts desc limit 8").fetchall()
    out = ['<h2>Eventos recientes</h2><table><tr><th>cuándo (UTC)</th><th>estrategia</th><th>evento</th><th>detalle</th></tr>']
    for r in rows:
        detail = ""
        if r["detail"]:
            d = json.loads(r["detail"])
            detail = d.get("reason") or d.get("rule") or (f"equity {d['equity']:,.0f}" if "equity" in d else "")
        trader = f' {r["trader"][:10]}…' if r["trader"] else ""
        out.append(f'<tr><td>{r["ts"][:16]}</td><td>{html.escape(r["strategy"])}</td>'
                   f'<td>{r["kind"]}{trader}</td><td class="muted">{html.escape(str(detail))}</td></tr>')
    out.append("</table>")
    if flags:
        out.append('<h2>Señales de comportamiento</h2><table><tr><th>cuándo</th><th>trader</th><th>regla</th><th class="num">valor</th></tr>')
        for f in flags:
            cls = "warn" if f["rule"].startswith("watch:") else "bad"
            out.append(f'<tr><td>{f["ts"][:16]}</td><td>{f["trader"][:12]}…</td>'
                       f'<td class="{cls}">{html.escape(f["rule"])}</td><td class="num">{f["value"]:.3g}</td></tr>')
        out.append("</table>")
    return "".join(out)


def collector_section() -> str:
    lines = []
    for level, message in health.check():
        cls = {"OK": "good", "WARN": "warn"}.get(level, "bad")
        lines.append(f'<tr><td class="{cls}">{level}</td><td>{html.escape(message)}</td></tr>')
    census = read_json(DATA_DIR / "state" / "census.json", None)
    census_line = ""
    if census:
        done, total = census.get("done", 0), len(census.get("wallets", []))
        census_line = f'<p class="sub">censo: {done:,}/{total:,} wallets ({done / max(total, 1):.0%})</p>'
    return "<h2>Collector</h2><table>" + "".join(lines) + "</table>" + census_line


def build(now: datetime) -> str:
    body = [f"<h1>copy-trader</h1><p class='sub'>generado {now:%Y-%m-%d %H:%M} UTC · "
            "parámetros congelados hasta 2026-12-01 (ADR-003)</p>"]
    if DB_PATH.exists():
        store = Store()
        try:
            body.append(strategies_section(store, now))
            body.append(events_section(store))
        finally:
            store.close()
    else:
        body.append("<p>El paper trading aún no inicia.</p>")
    body.append(collector_section())
    return ("<!doctype html><html lang='es'><head><meta charset='utf-8'>"
            "<meta name='viewport' content='width=device-width,initial-scale=1'>"
            f"<title>copy-trader</title><style>{STYLE}</style></head><body>"
            + "".join(body) + "</body></html>")


def main() -> int:
    page = build(utcnow())
    tmp = OUT_PATH.with_suffix(".html.tmp")
    tmp.write_text(page)
    tmp.replace(OUT_PATH)
    print(f"wrote {OUT_PATH} ({len(page):,} bytes)")
    return 0
