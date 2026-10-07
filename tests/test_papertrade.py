from datetime import datetime, timedelta, timezone

import polars as pl
import pytest

from papertrade import engine as engine_mod
from papertrade import selection, watch
from papertrade.book import Book, Market, execute, funding_payments, plan_trades, target_notionals, unreplicable
from papertrade.config import TAKER_FEE, Strategy
from papertrade.store import Store

T0 = datetime(2026, 10, 7, 12, 0, 30, tzinfo=timezone.utc)


def mkt(mid, funding=0.0):
    return Market(mid=mid, oracle=mid, funding=funding, impact_bid=mid * 0.999, impact_ask=mid * 1.001)


# --- book: pure accounting ---

def test_targets_copy_exposure_and_cap_leverage():
    targets, scale = target_notionals({"BTC": 20_000, "ETH": -10_000}, 10_000, 1_000, max_leverage=5)
    assert scale == 1 and targets == {"BTC": 2_000, "ETH": -1_000}
    targets, scale = target_notionals({"BTC": 100_000}, 10_000, 1_000, max_leverage=5)  # trader at 10x
    assert scale == 0.5 and targets == {"BTC": 5_000}


def test_plan_trades_ignores_noise_but_closes_and_flips():
    m = {"BTC": mkt(100.0)}
    book = Book("s", "t", 0.0, {"BTC": 10.0})  # $1,000 long
    assert plan_trades(book, {"BTC": 1_050}, m) == []                 # 5% gap: inside the band
    assert plan_trades(book, {"BTC": 1_200}, m)[0][1] == pytest.approx(2.0)
    assert plan_trades(book, {}, m)[0][1] == -10.0                     # trader closed: close exactly
    assert plan_trades(book, {"BTC": -500}, m)[0][1] == pytest.approx(-15.0)  # flip to short
    assert plan_trades(book, {"DOGE": 5}, {"BTC": mkt(100.0), "DOGE": mkt(0.1)}) == [("BTC", -10.0, 0.0)]


def test_lot_rounding_and_exchange_minimum():
    btc = Market(mid=100_000.0, oracle=100_000.0, funding=0.0, sz_decimals=5)
    book = Book("s", "t", 0.0)
    [(coin, delta, _)] = plan_trades(book, {"BTC": 1_234.567}, {"BTC": btc})
    assert delta == 0.01235                                             # 5 lot decimals
    assert plan_trades(book, {"BTC": 9.0}, {"BTC": btc}) == []          # under the $10 minimum
    dust = Book("s", "t", 0.0, {"BTC": 0.00005})                        # $5 position the trader closed
    assert plan_trades(dust, {}, {"BTC": btc}) == [("BTC", -0.00005, 0.0)]
    assert unreplicable({"BTC": 9.0, "ETH": 500.0}, {"BTC": btc, "ETH": mkt(2_000.0)}) == {"BTC": 9.0}


def test_execute_charges_impact_and_fee_and_pnl_is_linear():
    m = mkt(100.0)
    book = Book("s", "t", 1_000.0)
    fill = execute(book, "BTC", 10.0, m, {})
    assert fill.price == pytest.approx(100.1)                          # impact ask
    cost = 10 * 0.1 + 10 * 100.1 * TAKER_FEE
    assert book.equity({"BTC": m}) == pytest.approx(1_000 - cost)
    assert book.equity({"BTC": mkt(110.0)}) == pytest.approx(1_000 - cost + 100)


def test_funding_longs_pay_positive_rate():
    book = Book("s", "t", 0.0, {"BTC": 2.0, "ETH": -1.0})
    paid = funding_payments(book, {"BTC": mkt(100, 0.001), "ETH": mkt(50, 0.001)})
    assert paid == {"BTC": pytest.approx(0.2), "ETH": pytest.approx(-0.05)}
    assert book.cash == pytest.approx(-0.15)


# --- engine against a fake exchange ---

class FakeExchange:
    def __init__(self):
        self.prices = {"BTC": 100.0, "xyz:MU": 50.0}
        self.funding = 0.0
        self.positions = {"0xa": {"BTC": 20.0}, "0xb": {"xyz:MU": -10.0}}  # sizes
        self.equity = {"0xa": 1_000.0, "0xb": 1_000.0}

    def perp_dexs(self):
        return ["", "xyz"]

    def info(self, body):
        dex = body.get("dex", "")
        coins = [c for c in self.prices if (c.split(":")[0] if ":" in c else "") == dex]
        ctxs = [{"midPx": str(self.prices[c]), "oraclePx": str(self.prices[c]), "funding": str(self.funding),
                 "impactPxs": [str(self.prices[c] * 0.999), str(self.prices[c] * 1.001)]} for c in coins]
        return [{"universe": [{"name": c, "szDecimals": 4} for c in coins]}, ctxs]

    def clearinghouse_state(self, user, dex=""):
        held = {c: s for c, s in self.positions.get(user, {}).items()
                if (c.split(":")[0] if ":" in c else "") == dex}
        return {"assetPositions": [{"position": {"coin": c, "szi": str(s)}} for c, s in held.items()]}

    def portfolio(self, user):
        return [["allTime", {"accountValueHistory": [[1, str(self.equity[user])]]}]]


@pytest.fixture
def setup(tmp_path, monkeypatch):
    monkeypatch.setattr(engine_mod, "KILL_FILE", tmp_path / "KILL")
    monkeypatch.setattr(watch, "run", lambda traders, now: [])
    candidates = pl.DataFrame({"user": ["0xa", "0xb", "0xc"], "ret": [0.5, 0.4, 0.1]})
    monkeypatch.setattr(selection, "candidate_signals", lambda now: candidates)
    exchange = FakeExchange()
    store = Store(tmp_path / "pt.db")
    strategy = Strategy("test", "ret", n_traders=2, capital=10_000.0)
    return engine_mod.Engine(exchange, store, [strategy]), exchange, store


def equity(store):
    return store.db.execute("select equity from equity order by ts desc limit 1").fetchone()[0]


def test_engine_opens_books_and_mirrors_positions_on_all_dexs(setup):
    engine, ex, store = setup
    engine.step(T0)
    books = {b.trader: b for _, b in store.open_books("test")}
    assert set(books) == {"0xa", "0xb"}
    # 30% cap per trader (plan): $3,000 books, 40% cash.
    # 0xa: 2x long BTC on $1k equity -> 2x of the $3k book; 0xb: 0.5x short MU on an HIP-3 dex.
    assert books["0xa"].positions["BTC"] * 100 == pytest.approx(6_000, rel=1e-6)
    assert books["0xb"].positions["xyz:MU"] * 50 == pytest.approx(-1_500, rel=1e-6)
    assert 9_980 < equity(store) < 10_000                              # only costs so far


def test_book_snapshots_record_trader_equity(setup):
    engine, ex, store = setup
    engine.step(T0)
    rows = store.db.execute("select trader_equity from book_equity").fetchall()
    assert len(rows) == 2 and all(r[0] == 1_000.0 for r in rows)


def test_engine_follows_closes_and_price_moves(setup):
    engine, ex, store = setup
    engine.step(T0)
    ex.prices["BTC"] = 110.0
    ex.positions["0xa"] = {}                                           # trader closes BTC
    engine.step(T0 + timedelta(minutes=6))
    books = {b.trader: b for _, b in store.open_books("test")}
    assert books["0xa"].positions == {}
    assert books["0xa"].cash > 3_500                                   # +$600 on the 60 BTC... minus costs


def test_funding_charged_once_per_hour(setup):
    engine, ex, store = setup
    engine.step(T0)
    ex.funding = 0.001
    engine.step(T0 + timedelta(minutes=10))                            # same hour: nothing
    assert store.db.execute("select count(*) from events where kind='funding'").fetchone()[0] == 0
    engine.step(T0 + timedelta(minutes=65))                            # crossed into the next hour
    rows = store.db.execute("select coin, cash_delta from events where kind='funding'").fetchall()
    assert {r[0] for r in rows} == {"BTC", "xyz:MU"}
    btc = [r[1] for r in rows if r[0] == "BTC"][0]
    assert btc == pytest.approx(-60 * 100 * 0.001, rel=1e-3)            # long pays


def test_kill_file_closes_everything(setup, tmp_path):
    engine, ex, store = setup
    engine.step(T0)
    (tmp_path / "KILL").touch()
    engine.step(T0 + timedelta(minutes=1))
    assert store.open_books("test") == []
    assert store.strategy("test")["status"] == "halted"


def test_drawdown_halts_strategy(setup):
    engine, ex, store = setup
    engine.step(T0)
    ex.prices["BTC"] = 30.0                                            # 2x long book loses ~70% of half the capital
    engine.step(T0 + timedelta(minutes=6))
    assert store.strategy("test")["status"] == "halted"


def test_rebalance_moves_capital_from_dropped_traders(setup, monkeypatch):
    engine, ex, store = setup
    engine.step(T0)
    swapped = pl.DataFrame({"user": ["0xa", "0xc"], "ret": [0.5, 0.4]})
    monkeypatch.setattr(selection, "candidate_signals", lambda now: swapped)
    ex.positions["0xc"], ex.equity["0xc"] = {"BTC": 5.0}, 1_000.0
    later = T0 + timedelta(days=29)
    engine.step(later)
    books = {b.trader: b for _, b in store.open_books("test")}
    assert set(books) == {"0xa", "0xc"}
    events = [r[0] for r in store.db.execute("select kind from events where ts = ?", (later.isoformat(),))]
    assert "close_book" in events and "open_book" in events


def test_evaluate_marks_hits_actionable_only_with_enough_trades():
    feats = pl.DataFrame({
        "user": ["mart", "quiet", "liq"],
        "n_trades": [20, 6, 2],
        "martingale_share": [0.9, 0.9, 0.1],
        "liquidations": [0, 0, 1],
        "p95_leverage": [3.0, 3.0, 3.0],
        "change_leverage": [1.0, 1.0, None],
        "change_size": [1.0, 1.0, 1.0],
    })
    hits = {(h["trader"], h["rule"]): h["actionable"] for h in watch.evaluate(feats)}
    assert hits == {("mart", "martingale"): True, ("quiet", "martingale"): False, ("liq", "liquidated"): True}


def test_non_actionable_hits_are_logged_but_do_not_close_books(setup, monkeypatch):
    engine, ex, store = setup
    engine.step(T0)
    monkeypatch.setattr(watch, "run", lambda traders, now: [
        {"trader": "0xa", "rule": "martingale", "column": "martingale_share", "value": 0.9, "limit": 0.6,
         "n_trades": 4, "actionable": False}])
    engine.step(T0 + timedelta(hours=7))
    assert {b.trader for _, b in store.open_books("test")} == {"0xa", "0xb"}
    assert store.db.execute("select rule from flags").fetchone()[0] == "watch:martingale"


def test_flagged_trader_is_closed_and_not_reselected(setup, monkeypatch):
    engine, ex, store = setup
    engine.step(T0)
    assert {b.trader for _, b in store.open_books("test")} == {"0xa", "0xb"}
    monkeypatch.setattr(watch, "run", lambda traders, now: [
        {"trader": "0xa", "rule": "liquidated", "column": "liquidations", "value": 1.0, "limit": 0,
         "n_trades": 8, "actionable": True}])
    engine.step(T0 + timedelta(hours=7))                 # watch interval elapsed
    assert {b.trader for _, b in store.open_books("test")} == {"0xb"}
    reasons = [r[0] for r in store.db.execute("select json_extract(detail, '$.reason') from events where kind='close_book'")]
    assert reasons == ["behavior: liquidated"]
    engine.step(T0 + timedelta(days=29))                 # rebalance: 0xa still ranks first but is flagged
    assert "0xa" not in {b.trader for _, b in store.open_books("test")}


def test_rebalance_applies_risk_weights_and_keeps_cash(setup, monkeypatch):
    engine, ex, store = setup
    monkeypatch.setattr(engine_mod.risk, "weights_for",
                        lambda users: ({u: 0.3 for u in users}, [sorted(users)]))
    engine.step(T0)
    assert store.strategy("test")["cash_pool"] == pytest.approx(4_000.0)
    detail = store.db.execute("select detail from events where kind='rebalance'").fetchone()[0]
    assert '"correlated"' in detail and '"weights"' in detail


def test_daily_loss_pauses_new_exposure_but_allows_reductions(setup):
    engine, ex, store = setup
    engine.step(T0)
    ex.prices["BTC"] = 90.0                                 # book 0xa loses ~$600 of $10k: > 5% day loss
    engine.step(T0 + timedelta(minutes=6))
    assert store.db.execute("select count(*) from events where kind='risk_pause'").fetchone()[0] == 1
    size_frozen = store.open_books("test")[0]
    frozen = {b.trader: dict(b.positions) for _, b in store.open_books("test")}
    ex.positions["0xa"] = {"BTC": 60.0}                     # trader triples up; we must not follow today
    engine.step(T0 + timedelta(minutes=12))
    books = {b.trader: b for _, b in store.open_books("test")}
    assert books["0xa"].positions["BTC"] <= frozen["0xa"]["BTC"] + 1e-9
    ex.positions["0xa"] = {}                                # trader closes: reduction goes through
    engine.step(T0 + timedelta(minutes=18))
    assert store.open_books("test")[0][1].positions.get("BTC") is None or         {b.trader: b for _, b in store.open_books("test")}["0xa"].positions == {}


def test_dashboard_builds_from_store(setup, monkeypatch, tmp_path):
    from collector import health
    from papertrade import dashboard
    engine, ex, store = setup
    engine.step(T0)
    engine.step(T0 + timedelta(minutes=6))          # second snapshot: sparklines have two points
    store.commit()
    monkeypatch.setattr(dashboard, "DB_PATH", tmp_path / "pt.db")
    monkeypatch.setattr(dashboard, "Store", lambda: store)
    fake_state = {"census.json": {"done": 10, "wallets": ["w"] * 40},
                  "ranking.json": {"generated_at": T0.isoformat(), "eligible": 123, "top": [{
                      "user": "0xabcdef1234", "trader_score": 88.5, "sharpe": 1.1, "low_dd": -0.06,
                      "consistency": 0.75, "n_obs": 12, "account_value": 45_000.0,
                      "behavior_known": True, "behavior_penalty": 0.0}]}}
    monkeypatch.setattr(dashboard, "read_json", lambda path, default: fake_state.get(path.name, default))
    monkeypatch.setattr(health, "check", lambda: [("OK", "leaderboard: fine"), ("FAIL", "wallets: stale")])
    store.close = lambda: None                      # build() must not close the fixture's connection
    page = dashboard.build(T0 + timedelta(minutes=10))
    assert ">test<" in page and "<svg" in page and "rebalance" in page
    assert 'class="bad">FAIL' in page and "wallets: stale" in page
    assert "congelados" in page and "censo: 10/40" in page
    assert "Ranking TraderScore" in page and "88.5" in page and "limpio" in page


def test_tracking_report_measures_the_copying_gap(setup):
    from papertrade import tracking
    engine, ex, store = setup
    engine.step(T0)
    [(book_id, _)] = [(i, b) for i, b in store.open_books("test") if b.trader == "0xa"]
    # Trader makes +1%/h on $1k equity; the book replicates it minus 0.1%/h of friction.
    for h in range(6):
        store.snapshot_book(T0 + timedelta(hours=h), book_id,
                            equity=3_000.0 * (1.009 ** h), gross=6_000.0,
                            trader_equity=1_000.0, trader_pnl=10.0 * h)
    store.commit()
    [row] = [r for r in tracking.report(store) if r["trader"] == "0xa"]
    assert row["hours"] == 5
    assert row["trader_ret"] == pytest.approx(1.01 ** 5 - 1)          # 5 compounded 1% steps
    assert row["book_ret"] == pytest.approx(1.009 ** 5 - 1)
    assert row["gap"] < 0 and row["gap_per_day"] == pytest.approx(-0.001 * 24, rel=0.2)


def test_tracking_skips_rows_without_trader_pnl(setup):
    from papertrade import tracking
    engine, ex, store = setup
    engine.step(T0)                                                   # engine snapshots carry pnl=None? (fake)
    store.commit()
    assert all(r["hours"] >= 3 for r in tracking.report(store))
