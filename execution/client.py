"""Thin wrapper over the official hyperliquid-python-sdk (signing is never reimplemented here).

Only what the executor needs: account state, market snapshot, IOC orders, close-all. Kept small
so tests can swap it for a fake.
"""

from __future__ import annotations

import json
import os
import stat
from typing import Any

from papertrade.book import Market

from .config import SECRETS_PATH


class SecretsError(RuntimeError):
    pass


def load_secrets(path=SECRETS_PATH) -> dict[str, str]:
    if not path.exists():
        raise SecretsError(f"no credentials at {path}; see execution/config.py for the expected file")
    mode = os.stat(path).st_mode
    if mode & (stat.S_IRWXG | stat.S_IRWXO):
        raise SecretsError(f"{path} is readable by other users; run: chmod 600 {path}")
    secrets = json.loads(path.read_text())
    for key in ("network", "account_address", "agent_secret_key"):
        if not secrets.get(key):
            raise SecretsError(f"{path} is missing '{key}'")
    if secrets["network"] not in ("testnet", "mainnet"):
        raise SecretsError("network must be 'testnet' or 'mainnet'")
    return secrets


class HyperliquidExecClient:
    def __init__(self, secrets: dict[str, str]):
        import eth_account
        from hyperliquid.exchange import Exchange
        from hyperliquid.info import Info
        from hyperliquid.utils import constants

        url = constants.TESTNET_API_URL if secrets["network"] == "testnet" else constants.MAINNET_API_URL
        self.network = secrets["network"]
        self.account = secrets["account_address"]
        self.info = Info(url, skip_ws=True)
        self.exchange = Exchange(eth_account.Account.from_key(secrets["agent_secret_key"]), url,
                                 account_address=self.account)

    def account_state(self) -> tuple[float, dict[str, float]]:
        """(account value, coin -> signed size) for the master account on the main perp dex."""
        state = self.info.user_state(self.account)
        positions = {p["position"]["coin"]: float(p["position"]["szi"]) for p in state["assetPositions"]
                     if float(p["position"]["szi"])}
        return float(state["marginSummary"]["accountValue"]), positions

    def markets(self) -> dict[str, Market]:
        meta, ctxs = self.info.meta_and_asset_ctxs()
        out = {}
        for asset, ctx in zip(meta["universe"], ctxs):
            if not ctx.get("midPx"):
                continue
            impact = ctx.get("impactPxs") or [None, None]
            out[asset["name"]] = Market(mid=float(ctx["midPx"]), oracle=float(ctx["oraclePx"]),
                                        funding=float(ctx["funding"]),
                                        impact_bid=float(impact[0]) if impact[0] else None,
                                        impact_ask=float(impact[1]) if impact[1] else None,
                                        sz_decimals=asset.get("szDecimals"))
        return out

    def market_order(self, coin: str, size: float, slippage: float, reduce_only: bool) -> Any:
        """IOC limit at mid +/- slippage (how the SDK's market orders work), signed size."""
        if reduce_only:
            return self.exchange.market_close(coin, sz=abs(size), slippage=slippage)
        return self.exchange.market_open(coin, size > 0, abs(size), slippage=slippage)
