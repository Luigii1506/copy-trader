"""Real-execution settings. Everything defaults to the safe side: dry run, testnet, small limits.

Secrets never live in the repo: an API (agent) wallet key goes in
DATA_DIR/secrets/hyperliquid_agent.json with permissions 600:

    {"network": "testnet", "account_address": "0x<master account>", "agent_secret_key": "0x<agent key>"}

The agent key comes from app.hyperliquid.xyz/API: it can sign trades for the master account but
cannot withdraw (Hyperliquid docs, "Nonces and API wallets"). account_address is the master
account: querying with the agent address returns an empty account (same docs).
"""

from __future__ import annotations

from dataclasses import dataclass

from collector.storage import DATA_DIR

SECRETS_PATH = DATA_DIR / "secrets" / "hyperliquid_agent.json"
EXEC_DIR = DATA_DIR / "execution"
DB_PATH = EXEC_DIR / "execution.db"
KILL_FILE = EXEC_DIR / "KILL"


@dataclass(frozen=True)
class ExecConfig:
    source_strategy: str = "top_sharpe_pure"   # paper strategy whose portfolio is mirrored
    dry_run: bool = True                       # log intended orders, send nothing
    # Independent guard: applies on top of the paper engine's own limits.
    max_gross_leverage: float = 2.0            # gross notional / real account equity
    max_order_usd: float = 500.0               # any single order larger than this is cut down
    daily_loss_halt: float = 0.05              # close everything after losing 5% in a UTC day
    min_order_usd: float = 10.0                # exchange rule: orders under $10 are rejected
    slippage: float = 0.01                     # IOC limit at mid +/- 1% (the SDK default is 5%)
    main_dex_only: bool = True                 # HIP-3 coins skipped until tested separately
