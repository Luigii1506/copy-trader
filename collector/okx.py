"""OKX copy-trading lead traders: an independent universe to replicate the persistence result.

Official public endpoints (docs-v5, "Copy Trading", public): rate limit 5 requests per 2 seconds
per IP; we use 2 per second. Daily job:
- public-lead-traders (SWAP, all states, 20 per page): every lead trader and their headline stats
- public-pnl (lastDays=4): 365 days of daily *accumulated* pnl and pnl ratio per trader

Caveats, stated once: OKX computes these numbers (not verifiable on-chain), and only current lead
traders are listed. Daily snapshots from 2026-10-08 on record who disappears, so the forward part
of the OKX study is free of that survivorship bias even though the 365-day backfill is not.
"""

from __future__ import annotations

import logging
import time
from typing import Any

import httpx

from .storage import RawWriter, envelope, utcnow

log = logging.getLogger(__name__)

BASE = "https://www.okx.com/api/v5/copytrading"
MIN_INTERVAL = 0.5  # seconds between requests: 2/s, under the documented 5 per 2 s


class OkxClient:
    def __init__(self, timeout: float = 30.0):
        self.http = httpx.Client(timeout=timeout)
        self.last = 0.0

    def close(self) -> None:
        self.http.close()

    def get(self, path: str, params: dict[str, Any], retries: int = 4) -> list[dict[str, Any]]:
        for attempt in range(retries):
            wait = MIN_INTERVAL - (time.monotonic() - self.last)
            if wait > 0:
                time.sleep(wait)
            self.last = time.monotonic()
            try:
                resp = self.http.get(f"{BASE}/{path}", params=params)
                resp.raise_for_status()
                body = resp.json()
                if body.get("code") != "0":
                    raise RuntimeError(f"OKX {path}: code {body.get('code')} {body.get('msg')}")
                return body["data"]
            except (httpx.HTTPError, RuntimeError) as exc:
                if attempt == retries - 1:
                    raise
                log.warning("okx %s failed (%s); retrying", path, exc)
                time.sleep(2 ** attempt * 2)
        return []

    def lead_traders(self) -> list[dict[str, Any]]:
        pages, page, total = [], 1, 1
        while page <= total:
            data = self.get("public-lead-traders", {"instType": "SWAP", "state": "0", "limit": "20", "page": str(page)})
            if not data:
                break
            pages.append(data[0])
            total = int(data[0].get("totalPage") or 1)
            page += 1
        return pages

    def daily_pnl(self, unique_code: str) -> list[dict[str, Any]]:
        return self.get("public-pnl", {"instType": "SWAP", "uniqueCode": unique_code, "lastDays": "4"})


def sync_okx(client: OkxClient | None = None) -> None:
    own = client is None
    client = client or OkxClient()
    try:
        now = utcnow()
        pages = client.lead_traders()
        RawWriter("okx_lead_traders", now).write(
            envelope("okx_lead_traders", {"path": "public-lead-traders", "instType": "SWAP"}, pages, now))
        codes = sorted({r["uniqueCode"] for p in pages for r in p.get("ranks", [])})
        writer = RawWriter("okx_pnl", now)
        saved = 0
        for code in codes:
            try:
                pnl = client.daily_pnl(code)
                writer.write(envelope("okx_pnl", {"path": "public-pnl", "uniqueCode": code, "lastDays": "4"},
                                      pnl, utcnow()))
                saved += 1
            except Exception:
                log.exception("okx pnl %s failed; continuing", code)
        log.info("okx: %d lead traders, %d pnl histories saved", len(codes), saved)
    finally:
        if own:
            client.close()
