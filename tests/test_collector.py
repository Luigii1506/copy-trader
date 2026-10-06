import gzip
import json
import os
from datetime import datetime, timedelta, timezone

import polars as pl

from collector import health, normalize, universe
from collector.hyperliquid import FILLS_PAGE_SIZE, HyperliquidClient
from collector.storage import write_json
from collector.sync import fill_gap_suspected


def fill(t, tid, oid=1, **kw):
    return {"coin": "BTC", "px": "100", "sz": "1", "side": "B", "time": t, "startPosition": "0",
            "dir": "Open Long", "closedPnl": "0", "hash": "0x", "oid": oid, "tid": tid,
            "fee": "0.1", "feeToken": "USDC", "crossed": True, **kw}


class FakeClient(HyperliquidClient):
    """Serves userFillsByTime from an in-memory list, oldest first, capped like the real API."""

    def __init__(self, fills):
        self.all_fills = sorted(fills, key=lambda f: f["time"])
        self.calls = []

    def info(self, body, retries=5):
        self.calls.append(body["startTime"])
        return [f for f in self.all_fills if f["time"] >= body["startTime"]][:FILLS_PAGE_SIZE]


def test_fills_since_paginates_and_dedups_same_millisecond_overlap():
    fills = [fill(t, tid=t) for t in range(1, 4501)]
    fills += [fill(4500, tid=10_000 + i) for i in range(5)]  # several fills in the last ms
    got = FakeClient(fills).fills_since("0xabc", 0)
    assert len(got) == len(fills)
    assert len({(f["tid"], f["oid"]) for f in got}) == len(fills)


def test_fills_since_terminates_when_a_full_page_shares_one_timestamp():
    client = FakeClient([fill(5, tid=i) for i in range(FILLS_PAGE_SIZE)])
    assert len(client.fills_since("0xabc", 0)) == FILLS_PAGE_SIZE


def test_fill_gap_detection():
    assert not fill_gap_suspected(0, [fill(10, 1)])           # first backfill
    assert not fill_gap_suspected(10, [fill(10, 1), fill(11, 2)])  # cursor fill returned again
    assert fill_gap_suspected(10, [fill(50, 3)])              # cursor fill aged out of the window
    assert not fill_gap_suspected(10, [])


def leaderboard_row(address, value, month_roi, alltime_pnl):
    perf = lambda pnl, roi: {"pnl": str(pnl), "roi": str(roi), "vlm": "1000"}
    return {
        "ethAddress": address, "accountValue": str(value), "displayName": None, "prize": 0,
        "windowPerformances": [["day", perf(0, 0)], ["week", perf(0, 0)],
                               ["month", perf(0, month_roi)], ["allTime", perf(alltime_pnl, 0)]],
    }


def test_universe_is_append_only_and_draws_random_cohort_once(data_dir):
    now = datetime(2026, 10, 6, tzinfo=timezone.utc)
    board = {"leaderboardRows": [leaderboard_row(f"0x{i:040x}", 50_000, i / 100, i) for i in range(500)]}
    u1, added1 = universe.refresh(board, now)
    assert added1 > 0 and u1["random_seed"] is not None
    cohorts = [c for w in u1["wallets"].values() for c in w["cohorts"]]
    assert cohorts.count("random") == universe.RANDOM_SIZE

    # Wallets that leave the leaderboard must stay tracked (no survivorship bias).
    u2, _ = universe.refresh({"leaderboardRows": board["leaderboardRows"][:10]}, now + timedelta(days=1))
    assert set(u1["wallets"]) <= set(u2["wallets"])
    assert u2["random_seed"] == u1["random_seed"]
    assert [c for w in u2["wallets"].values() for c in w["cohorts"]].count("random") == universe.RANDOM_SIZE


def test_leaderboard_rows_flatten_windows():
    record = {"fetched_at": "2026-10-06T00:00:00+00:00",
              "payload": {"leaderboardRows": [leaderboard_row("0xABC", 1234.5, 0.2, 99)]}}
    [row] = normalize.leaderboard_rows(record)
    assert row["user"] == "0xabc"
    assert row["account_value"] == 1234.5
    assert row["month_roi"] == 0.2 and row["alltime_pnl"] == 99


def test_clearinghouse_rows():
    record = {"fetched_at": "t", "request": {"user": "0xabc"}, "payload": {
        "marginSummary": {"accountValue": "100", "totalNtlPos": "50", "totalRawUsd": "0", "totalMarginUsed": "5"},
        "withdrawable": "95",
        "assetPositions": [{"type": "oneWay", "position": {
            "coin": "ETH", "szi": "-0.5", "leverage": {"type": "cross", "value": 20}, "entryPx": "2000",
            "positionValue": "1000", "unrealizedPnl": "-7", "liquidationPx": None, "marginUsed": "50",
            "cumFunding": {"sinceOpen": "-1.5"}}}]}}
    [account] = normalize.account_rows(record)
    assert account["account_value"] == 100 and account["open_positions"] == 1
    [pos] = normalize.position_rows(record)
    assert pos["size"] == -0.5 and pos["leverage"] == 20 and pos["liquidation_px"] is None
    assert pos["funding_since_open"] == -1.5


def test_equity_rows_join_value_and_pnl():
    record = {"request": {"user": "0xabc"}, "payload": [
        ["allTime", {"accountValueHistory": [[1, "10"], [2, "12"]], "pnlHistory": [[1, "0"], [2, "2"]], "vlm": "0"}]]}
    rows = normalize.equity_rows(record)
    assert [(r["time_ms"], r["account_value"], r["pnl"]) for r in rows] == [(1, 10, 0), (2, 12, 2)]


def test_normalize_run_tolerates_truncated_raw_file(data_dir):
    raw = data_dir / "raw" / "hyperliquid" / "fills" / "date=2026-10-06" / "20261006T000000Z.jsonl.gz"
    raw.parent.mkdir(parents=True)
    good = {"request": {"user": "0xabc"}, "payload": [fill(1, 1), fill(2, 2)]}
    with gzip.open(raw, "at") as fh:
        fh.write(json.dumps(good) + "\n")
    with open(raw, "ab") as fh:  # simulate a run killed mid-write
        fh.write(gzip.compress(b'{"request": {"user": "0xdef"}, "payload": [')[:-12])
    old = raw.stat().st_mtime - normalize.SETTLE_SECONDS - 1
    os.utime(raw, (old, old))

    normalize.run()
    out = data_dir / "processed" / "hyperliquid" / "fills" / "date=2026-10-06" / "20261006T000000Z.parquet"
    assert pl.read_parquet(out)["tid"].to_list() == [1, 2]


def test_health_fails_when_jobs_are_stale(data_dir):
    now = datetime.now(timezone.utc)
    write_json(data_dir / "state" / "last_run_leaderboard.json", {"finished_at": now.isoformat()})
    write_json(data_dir / "state" / "last_run_normalize.json", {"finished_at": now.isoformat()})
    write_json(data_dir / "state" / "last_run_wallets.json", {
        "finished_at": (now - timedelta(hours=30)).isoformat(), "wallets": 300, "failures": 0, "gap_suspected": []})
    failing = [msg for level, msg in health.check() if level == "FAIL"]
    assert len(failing) == 1 and failing[0].startswith("wallets: last finished 30.0h ago")
    assert health.main() == 1
