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
    assert account["account_value"] == 100 and account["open_positions"] == 1 and account["dex"] == ""
    record["request"]["dex"] = "xyz"
    assert normalize.position_rows(record)[0]["dex"] == "xyz"
    [pos] = normalize.position_rows(record)
    assert pos["size"] == -0.5 and pos["leverage"] == 20 and pos["liquidation_px"] is None
    assert pos["funding_since_open"] == -1.5


def test_equity_rows_join_value_and_pnl():
    record = {"request": {"user": "0xabc"}, "payload": [
        ["allTime", {"accountValueHistory": [[1, "10"], [2, "12"]], "pnlHistory": [[1, "0"], [2, "2"]], "vlm": "0"}]]}
    rows = normalize.equity_rows(record)
    assert [(r["time_ms"], r["account_value"], r["pnl"]) for r in rows] == [(1, 10, 0), (2, 12, 2)]


def test_fill_rows_flag_own_liquidations_and_builder_fees():
    liq = fill(1, 1, liquidation={"liquidatedUser": "0xABC", "markPx": "1", "method": "market"}, builderFee="0.01")
    other = fill(2, 2, liquidation={"liquidatedUser": "0xdef", "markPx": "1", "method": "market"})
    rows = normalize.fill_rows({"request": {"user": "0xabc"}, "payload": [liq, other, fill(3, 3)]})
    assert [r["liquidated"] for r in rows] == [True, False, False]
    assert [r["builder_fee"] for r in rows] == [0.01, None, None]


def test_candle_rows():
    record = {"fetched_at": "t", "request": {"coin": "BTC", "interval": "1d"},
              "payload": [{"t": 1, "o": "1", "c": "2", "h": "3", "l": "0.5", "v": "9"}]}
    [row] = normalize.candle_rows(record)
    assert row["coin"] == "BTC" and row["close"] == 2.0 and row["volume"] == 9.0


def test_vault_rows():
    record = {"fetched_at": "t", "payload": [{"apr": 0.04, "pnls": [], "summary": {
        "name": "HLP", "vaultAddress": "0xDFC", "leader": "0xABC", "tvl": "1000.5", "isClosed": False,
        "relationship": {"type": "parent"}, "createTimeMillis": 1}}]}
    [row] = normalize.vault_rows(record)
    assert row["vault_address"] == "0xdfc" and row["leader"] == "0xabc"
    assert row["tvl"] == 1000.5 and row["relationship"] == "parent" and not row["is_closed"]


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


def test_normalize_rebuilds_processed_tables_when_schema_version_changes(data_dir):
    raw = data_dir / "raw" / "hyperliquid" / "fills" / "date=2026-10-06" / "20261006T000000Z.jsonl.gz"
    raw.parent.mkdir(parents=True)
    with gzip.open(raw, "wt") as fh:
        fh.write(json.dumps({"request": {"user": "0xabc"}, "payload": [fill(1, 1)]}) + "\n")
    old = raw.stat().st_mtime - normalize.SETTLE_SECONDS - 1
    os.utime(raw, (old, old))

    stale = normalize.PROCESSED_DIR / "fills" / "date=2026-10-06" / "stale.parquet"
    stale.parent.mkdir(parents=True)
    stale.write_bytes(b"old schema")
    normalize.VERSION_FILE.write_text("1\n")

    normalize.run()
    assert not stale.exists()
    assert (normalize.PROCESSED_DIR / "fills" / "date=2026-10-06" / "20261006T000000Z.parquet").exists()
    assert normalize.VERSION_FILE.read_text().strip() == str(normalize.SCHEMA_VERSION)


def test_health_fails_when_jobs_are_stale(data_dir):
    now = datetime.now(timezone.utc)
    write_json(data_dir / "state" / "last_run_leaderboard.json", {"finished_at": now.isoformat()})
    write_json(data_dir / "state" / "last_run_normalize.json", {"finished_at": now.isoformat()})
    write_json(data_dir / "state" / "last_run_wallets.json", {
        "finished_at": (now - timedelta(hours=30)).isoformat(), "wallets": 300, "failures": 0, "gap_suspected": []})
    failing = [msg for level, msg in health.check() if level == "FAIL"]
    assert len(failing) == 1 and failing[0].startswith("wallets: last finished 30.0h ago")
    assert health.main() == 1


class FakeStatsClient:
    def __init__(self):
        self.etag, self.downloads = "v1", 0

    def stats_version(self, url):
        return {"etag": self.etag, "last_modified": "Tue, 06 Oct 2026 23:21:14 GMT"}

    def leaderboard(self):
        self.downloads += 1
        board = {"leaderboardRows": [leaderboard_row("0xabc", 50_000, 0.1, 10)]}
        return board, self.stats_version(None)

    def vaults(self):
        return [], self.stats_version(None)

    def candles(self, coin, interval):
        self.candle_calls = getattr(self, "candle_calls", 0) + 1
        return [{"t": 1, "T": 2, "s": coin, "i": interval, "o": "1", "c": "2", "h": "3", "l": "0.5", "v": "9", "n": 1}]


def test_leaderboard_downloads_only_new_versions_and_respects_spacing(data_dir, monkeypatch):
    from collector import sync
    client = FakeStatsClient()
    sync.sync_leaderboard(client)
    sync.sync_leaderboard(client)  # same ETag -> no download
    assert client.downloads == 1
    client.etag = "v2"
    sync.sync_leaderboard(client)  # new version, but < 6h after the last snapshot
    assert client.downloads == 1
    monkeypatch.setattr(sync, "MIN_SNAPSHOT_SPACING", timedelta(0))
    sync.sync_leaderboard(client)
    assert client.downloads == 2
    versions = (data_dir / "state" / "leaderboard_versions.jsonl").read_text().splitlines()
    assert [json.loads(v)["etag"] for v in versions] == ["v1", "v2"]
    assert client.candle_calls == 2          # once per coin on the first run, then not for 20h


def test_leaderboard_rows_carry_source_time():
    record = {"fetched_at": "2026-10-07T00:05:00+00:00",
              "source_version": {"last_modified": "Tue, 06 Oct 2026 23:21:14 GMT"},
              "payload": {"leaderboardRows": [leaderboard_row("0xabc", 1, 0, 0)]}}
    [row] = normalize.leaderboard_rows(record)
    assert row["data_as_of"] == "2026-10-06T23:21:14+00:00"


class FakePortfolioClient:
    def __init__(self, fail=()):
        self.seen, self.fail = [], set(fail)

    def portfolio(self, user):
        if user in self.fail:
            raise RuntimeError("boom")
        self.seen.append(user)
        return [["allTime", {"accountValueHistory": [[1, "10"]], "pnlHistory": [[1, "0"]], "vlm": "0"}]]


def test_census_skips_vaults_and_small_volume_and_resumes(data_dir, monkeypatch):
    from collector import census
    from collector.storage import RawWriter, envelope, utcnow
    now = utcnow()
    rows = [leaderboard_row(f"0x{i:040x}", 1000, 0, 0) for i in range(120)]
    for row in rows:
        row["windowPerformances"][3][1]["vlm"] = "50000"
    rows[0]["windowPerformances"][3][1]["vlm"] = "5"          # below volume threshold
    RawWriter("leaderboard", now).write(envelope("leaderboard", {}, {"leaderboardRows": rows}, now))
    vault = {"summary": {"vaultAddress": f"0x{1:040x}"}}
    RawWriter("vaults", now).write(envelope("vaults", {}, [vault], now))

    monkeypatch.setattr(census, "SAVE_EVERY", 10)
    first = FakePortfolioClient(fail={f"0x{5:040x}"})
    census.run(first)
    assert census.progress() == (118, 118)
    assert f"0x{0:040x}" not in first.seen and f"0x{1:040x}" not in first.seen
    assert first.seen != sorted(first.seen)                     # random order

    second = FakePortfolioClient()
    census.run(second)                                          # already complete: nothing refetched
    assert second.seen == []


def test_universe_add_followed_traders_is_append_only(data_dir):
    now = datetime(2026, 10, 7, tzinfo=timezone.utc)
    assert universe.add(["0xAAA", "0xbbb"], "papertrade", now) == 2
    assert universe.add(["0xaaa"], "papertrade", now) == 0
    assert universe.add(["0xaaa"], "random", now) == 0
    assert universe.load()["wallets"]["0xaaa"]["cohorts"] == ["papertrade", "random"]


def test_candidate_funnel_adds_top_scored_wallets(data_dir, monkeypatch):
    import polars as pl
    from collector import sync

    pool = pl.DataFrame({"user": ["0xs1", "0xs2", "0xh1"],
                         "trader_score": [90.0, 80.0, None],
                         "sharpe": [0.1, 0.2, 3.5], "low_dd": [-0.1, -0.2, -0.3],
                         "consistency": [0.7, 0.6, 0.5], "n_obs": [10, 10, 10],
                         "account_value": [50_000.0] * 3, "behavior_known": [True, False, False],
                         "behavior_penalty": [15.0, 0.0, 0.0]})
    monkeypatch.setattr("papertrade.selection.candidate_signals", lambda now: pool)
    assert sync.candidate_wallets() == ["0xh1", "0xs1", "0xs2"]
    ranking = json.loads((data_dir / "state" / "ranking.json").read_text())
    assert ranking["eligible"] == 2 and ranking["top"][0]["user"] == "0xs1"
    assert ranking["top"][0]["behavior_penalty"] == 15.0

    monkeypatch.setattr("papertrade.selection.candidate_signals",
                        lambda now: (_ for _ in ()).throw(RuntimeError("no data")))
    assert sync.candidate_wallets() == []     # the funnel must never break the wallets job
