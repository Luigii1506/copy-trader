import json
import os
from datetime import datetime, timedelta, timezone

import pytest

from execution.client import SecretsError, load_secrets
from execution.config import ExecConfig
from execution.executor import Executor, paper_exposure
from papertrade.book import Book, Market
from papertrade.store import Store

T0 = datetime(2026, 10, 21, 12, 0, tzinfo=timezone.utc)


def mkt(mid):
    return Market(mid=mid, oracle=mid, funding=0.0, impact_bid=mid * 0.999, impact_ask=mid * 1.001, sz_decimals=4)


class FakeExchange:
    def __init__(self, equity=1_000.0, positions=None):
        self.equity, self.positions = equity, dict(positions or {})
        self.prices = {"BTC": 100.0, "ETH": 50.0, "xyz:MU": 20.0}
        self.sent = []

    def account_state(self):
        return self.equity, dict(self.positions)

    def markets(self):
        return {c: mkt(p) for c, p in self.prices.items()}

    def market_order(self, coin, size, slippage, reduce_only):
        self.sent.append((coin, round(size, 6), reduce_only))
        self.positions[coin] = self.positions.get(coin, 0.0) + size
        if abs(self.positions[coin]) < 1e-12:
            del self.positions[coin]
        return {"status": "ok"}


@pytest.fixture
def paper(tmp_path):
    """A paper DB with strategy 'src': $10k equity, a $2k BTC long and a $1k ETH short, plus an HIP-3 coin."""
    store = Store(tmp_path / "paper.db")
    store.ensure_strategy("src", {}, 5_000.0, T0)
    book_id = store.create_book("src", "0xa", 5_000.0, T0, {})
    store.save_book(book_id, Book("src", "0xa", 5_000.0 - 2_000 + 1_000 - 200,
                                  {"BTC": 20.0, "ETH": -20.0, "xyz:MU": 10.0}))
    store.commit()
    store.close()
    return tmp_path / "paper.db"


def make(tmp_path, paper, exchange, **cfg):
    return Executor(exchange, ExecConfig(source_strategy="src", **cfg), db_path=tmp_path / "exec.db",
                    paper_db=paper, kill_file=tmp_path / "KILL")


def test_paper_exposure_fractions(paper):
    fractions = paper_exposure(paper, "src", {c: mkt(p) for c, p in {"BTC": 100.0, "ETH": 50.0, "xyz:MU": 20.0}.items()})
    assert fractions == {"BTC": pytest.approx(0.2), "ETH": pytest.approx(-0.1), "xyz:MU": pytest.approx(0.02)}


def test_dry_run_logs_but_sends_nothing(tmp_path, paper):
    ex = FakeExchange()
    result = make(tmp_path, paper, ex).step(T0)
    assert ex.sent == []
    assert {o["coin"] for o in result.orders} == {"BTC", "ETH"}            # HIP-3 skipped
    assert any("HIP-3" in b for b in result.blocked)
    assert result.targets == {"BTC": pytest.approx(200.0), "ETH": pytest.approx(-100.0)}


def test_live_mirrors_scaled_portfolio_and_is_idempotent(tmp_path, paper):
    ex = FakeExchange()
    executor = make(tmp_path, paper, ex, dry_run=False)
    executor.step(T0)
    assert ex.positions == {"BTC": pytest.approx(2.0), "ETH": pytest.approx(-2.0)}
    executor.step(T0 + timedelta(minutes=1))                               # already on target: no orders
    assert len(ex.sent) == 2


def test_guard_caps_leverage_and_order_size(tmp_path, paper):
    ex = FakeExchange(equity=10_000.0)
    result = make(tmp_path, paper, ex, dry_run=False, max_gross_leverage=0.15, max_order_usd=500.0).step(T0)
    assert any("cap" in b for b in result.blocked)
    assert all(o["notional"] <= 500.0 + 1e-6 for o in result.orders)       # per-order cap holds


def test_kill_file_closes_everything_reduce_only(tmp_path, paper):
    ex = FakeExchange(positions={"BTC": 3.0, "ETH": -1.0})
    executor = make(tmp_path, paper, ex, dry_run=False)
    (tmp_path / "KILL").touch()
    result = executor.step(T0)
    assert result.halted and ex.positions == {}
    assert all(reduce_only for _, _, reduce_only in ex.sent)
    assert executor.step(T0 + timedelta(minutes=1)).halted                 # stays halted until the file is removed


def test_daily_loss_halt(tmp_path, paper):
    ex = FakeExchange(equity=1_000.0)
    executor = make(tmp_path, paper, ex, dry_run=False)
    executor.step(T0)
    ex.equity = 900.0                                                      # -10% in the same UTC day
    assert executor.step(T0 + timedelta(hours=2)).halted
    assert (tmp_path / "KILL").exists() and ex.positions == {}


def test_secrets_must_be_private_and_complete(tmp_path):
    path = tmp_path / "agent.json"
    path.write_text(json.dumps({"network": "testnet", "account_address": "0xa", "agent_secret_key": "0xk"}))
    os.chmod(path, 0o644)
    with pytest.raises(SecretsError, match="chmod 600"):
        load_secrets(path)
    os.chmod(path, 0o600)
    assert load_secrets(path)["network"] == "testnet"
    path.write_text(json.dumps({"network": "devnet", "account_address": "0xa", "agent_secret_key": "0xk"}))
    with pytest.raises(SecretsError):
        load_secrets(path)
