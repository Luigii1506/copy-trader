"""Hyperliquid client: public info endpoint + leaderboard, with weight-based rate limiting.

Sources:
- Info endpoint: https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/info-endpoint
- Rate limits:   https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/rate-limits-and-user-limits
- Leaderboard / vaults: stats-data.hyperliquid.xyz (used by the official frontend; NOT in the API docs)
"""

from __future__ import annotations

import logging
import os
import threading
import time
from typing import Any

import httpx

log = logging.getLogger(__name__)

INFO_URL = "https://api.hyperliquid.xyz/info"
LEADERBOARD_URL = "https://stats-data.hyperliquid.xyz/Mainnet/leaderboard"
VAULTS_URL = "https://stats-data.hyperliquid.xyz/Mainnet/vaults"

# Documented: 1200 weight/min per IP, shared by every process on the machine. Each job gets its own
# share through COPY_TRADER_WEIGHT_PER_MINUTE (set per job by scripts/install_launchd.sh) so jobs
# running at the same time stay under the limit together.
WEIGHT_PER_MINUTE = int(os.environ.get("COPY_TRADER_WEIGHT_PER_MINUTE", "1000"))

# Documented weights. Everything not listed weighs 20.
LIGHT_TYPES = {"l2Book", "allMids", "clearinghouseState", "orderStatus", "spotClearinghouseState", "exchangeStatus"}
# These add 1 weight per 20 items returned (candleSnapshot: per 60).
PER_ITEM_TYPES = {"userFills", "userFillsByTime", "historicalOrders", "userFunding", "fundingHistory"}
PER_60_ITEM_TYPES = {"candleSnapshot"}

FILLS_PAGE_SIZE = 2000  # documented max per userFillsByTime response


def _version(headers: httpx.Headers) -> dict[str, str]:
    return {"etag": headers.get("etag", ""), "last_modified": headers.get("last-modified", "")}


def base_weight(request_type: str) -> int:
    if request_type in LIGHT_TYPES:
        return 2
    if request_type == "userRole":
        return 60
    return 20


class WeightLimiter:
    """Token bucket measured in API weight. Balance may go negative after a heavy response."""

    def __init__(self, per_minute: int = WEIGHT_PER_MINUTE):
        self.capacity = per_minute
        self.rate = per_minute / 60.0
        self.tokens = float(per_minute)
        self.updated = time.monotonic()
        self.lock = threading.Lock()

    def _refill(self) -> None:
        now = time.monotonic()
        self.tokens = min(self.capacity, self.tokens + (now - self.updated) * self.rate)
        self.updated = now

    def acquire(self, weight: int) -> None:
        with self.lock:
            self._refill()
            if self.tokens < weight:
                time.sleep((weight - self.tokens) / self.rate)
                self._refill()
            self.tokens -= weight

    def charge(self, weight: int) -> None:
        """Charge extra weight known only after the response (per-item weights)."""
        with self.lock:
            self._refill()
            self.tokens -= weight


class HyperliquidClient:
    def __init__(self, limiter: WeightLimiter | None = None, timeout: float = 60.0):
        self.limiter = limiter or WeightLimiter()
        self.http = httpx.Client(timeout=timeout, headers={"Content-Type": "application/json"})

    def close(self) -> None:
        self.http.close()

    def info(self, body: dict[str, Any], retries: int = 5) -> Any:
        request_type = body["type"]
        self.limiter.acquire(base_weight(request_type))
        for attempt in range(retries):
            try:
                resp = self.http.post(INFO_URL, json=body)
                if resp.status_code == 429 or resp.status_code >= 500:
                    raise httpx.HTTPStatusError(f"HTTP {resp.status_code}", request=resp.request, response=resp)
                resp.raise_for_status()
                data = resp.json()
                if request_type in PER_ITEM_TYPES and isinstance(data, list):
                    self.limiter.charge(len(data) // 20)
                elif request_type in PER_60_ITEM_TYPES and isinstance(data, list):
                    self.limiter.charge(len(data) // 60)
                return data
            except (httpx.TransportError, httpx.HTTPStatusError) as exc:
                if attempt == retries - 1:
                    raise
                wait = 2 ** attempt * 5
                log.warning("%s failed (%s); retrying in %ss", request_type, exc, wait)
                time.sleep(wait)

    def _stats(self, url: str) -> tuple[Any, dict[str, str]]:
        """GET a stats-data file. Returns (payload, version), where version carries the file's
        ETag and Last-Modified: the time the data was produced, not the time we fetched it."""
        resp = self.http.get(url, timeout=180.0)
        resp.raise_for_status()
        return resp.json(), _version(resp.headers)

    def stats_version(self, url: str) -> dict[str, str]:
        """HEAD only: cheap check for whether a stats-data file changed."""
        resp = self.http.head(url, timeout=30.0)
        resp.raise_for_status()
        return _version(resp.headers)

    def leaderboard(self) -> tuple[dict[str, Any], dict[str, str]]:
        return self._stats(LEADERBOARD_URL)

    def vaults(self) -> tuple[list[dict[str, Any]], dict[str, str]]:
        return self._stats(VAULTS_URL)

    def clearinghouse_state(self, user: str, dex: str = "") -> dict[str, Any]:
        """dex "" is the main perp dex; others are HIP-3 dexs (e.g. "xyz": equity and index perps)."""
        body = {"type": "clearinghouseState", "user": user}
        if dex:
            body["dex"] = dex
        return self.info(body)

    def candles(self, coin: str, interval: str, start_ms: int = 0, end_ms: int | None = None) -> list[dict[str, Any]]:
        """OHLCV candles. Docs: only the most recent 5000 are available (daily: back to 2020)."""
        req = {"coin": coin, "interval": interval, "startTime": start_ms,
               "endTime": end_ms if end_ms is not None else int(time.time() * 1000) + 86_400_000}
        return self.info({"type": "candleSnapshot", "req": req})

    def perp_dexs(self) -> list[str]:
        """Names of all perp dexs, "" for the main one first."""
        return [d["name"] if d else "" for d in self.info({"type": "perpDexs"})]

    def portfolio(self, user: str) -> list[Any]:
        return self.info({"type": "portfolio", "user": user})

    def fills_since(self, user: str, start_ms: int) -> list[dict[str, Any]]:
        """All fills with time >= start_ms, paginated. Only the 10,000 most recent fills are available."""
        fills: list[dict[str, Any]] = []
        seen: set[tuple[Any, Any]] = set()
        cursor = start_ms
        while True:
            page = self.info({"type": "userFillsByTime", "user": user, "startTime": cursor})
            new = [f for f in page if (f["tid"], f["oid"]) not in seen]
            seen.update((f["tid"], f["oid"]) for f in new)
            fills.extend(new)
            if len(page) < FILLS_PAGE_SIZE or not new:
                return fills
            last_time = page[-1]["time"]
            # Docs: use the last returned timestamp as the next startTime (dedup handles overlap).
            cursor = last_time if last_time > cursor else cursor + 1
