"""copy-trader exec-* commands. Real orders need BOTH a credentials file and --live; default is dry run.

    copy-trader exec-step            # one step, dry run: prints the orders it would send
    copy-trader exec-step --live     # one step, sends orders (network from the credentials file)
    copy-trader exec-run [--live]    # loop every 60 s
    copy-trader exec-status          # account, targets vs positions, recent orders
    copy-trader exec-halt            # kill switch: close everything reduce-only, stay halted
"""

from __future__ import annotations

import logging
import time

from collector.hyperliquid import HyperliquidClient
from collector.storage import utcnow
from papertrade.book import Market

from .client import HyperliquidExecClient, SecretsError, load_secrets
from .config import DB_PATH, KILL_FILE, ExecConfig
from .executor import Executor

log = logging.getLogger(__name__)


def mainnet_markets() -> dict[str, Market]:
    """Reference prices for valuing the paper portfolio: testnet prices are not real prices."""
    client = HyperliquidClient()
    try:
        meta, ctxs = client.info({"type": "metaAndAssetCtxs"})
    finally:
        client.close()
    return {a["name"]: Market(mid=float(c["midPx"]), oracle=float(c["oraclePx"]), funding=float(c["funding"]),
                              sz_decimals=a.get("szDecimals"))
            for a, c in zip(meta["universe"], ctxs) if c.get("midPx")}


def build(live: bool) -> Executor:
    try:
        secrets = load_secrets()
    except SecretsError as exc:
        raise SystemExit(f"execution not configured: {exc}")
    client = HyperliquidExecClient(secrets)
    reference = mainnet_markets if secrets["network"] == "testnet" else None
    executor = Executor(client, ExecConfig(dry_run=not live), reference_markets=reference)
    print(f"network: {secrets['network']} · account {secrets['account_address'][:10]}… · "
          f"{'LIVE ORDERS' if live else 'dry run'} · mirroring '{executor.config.source_strategy}'")
    return executor


def print_result(result) -> None:
    print(f"equity ${result.equity:,.2f}{' · HALTED' if result.halted else ''}")
    for coin, target in sorted(result.targets.items()):
        print(f"  target {coin:10} {target:+12,.2f} USD")
    for o in result.orders:
        print(f"  order  {o['coin']:10} {o['size']:+.6g} (~${o['notional']:,.0f}) "
              f"{'reduce-only ' if o['reduce_only'] else ''}{o['status']}")
    for b in result.blocked:
        print(f"  guard  {b}")


def step(live: bool) -> int:
    print_result(build(live).step(utcnow()))
    return 0


def run(live: bool) -> int:
    executor = build(live)
    while True:
        started = utcnow()
        try:
            result = executor.step(started)
            log.info("exec step: equity %.2f, %d orders, halted=%s", result.equity, len(result.orders), result.halted)
        except Exception:
            log.exception("exec step failed; retrying next interval")
        time.sleep(max(1.0, 60 - (utcnow() - started).total_seconds()))


def halt() -> int:
    KILL_FILE.parent.mkdir(parents=True, exist_ok=True)
    KILL_FILE.write_text(f"{utcnow().isoformat()} manual\n")
    print(f"kill switch set ({KILL_FILE}); the next exec step closes every position reduce-only.")
    return 0


def status() -> int:
    if not DB_PATH.exists():
        print("execution has not run yet")
        return 0
    import sqlite3
    db = sqlite3.connect(DB_PATH)
    last = db.execute("select ts, equity, gross from equity order by ts desc limit 1").fetchone()
    if last:
        print(f"last step {last[0][:16]} UTC · equity ${last[1]:,.2f} · gross ${last[2]:,.0f}")
    print("halted" if KILL_FILE.exists() else "running (no kill file)")
    for row in db.execute("select ts, coin, size, notional, dry_run, status from orders order by id desc limit 10"):
        print(f"  {row[0][:16]} {row[1]:10} {row[2]:+.6g} ~${row[3]:,.0f} {'dry' if row[4] else 'LIVE'} {row[5]}")
    return 0
