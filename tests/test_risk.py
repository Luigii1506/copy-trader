from datetime import date, timedelta

import polars as pl
import pytest

from papertrade import risk
from papertrade.risk import allocate, correlation_groups, daily_pnl_returns, weights_for


def test_allocate_caps_per_trader_and_leaves_cash():
    weights = allocate(["a", "b"], [])
    assert weights == {"a": 0.3, "b": 0.3}            # 50% each would breach the 30% cap; 40% stays cash


def test_allocate_caps_correlated_group():
    users = [f"u{i}" for i in range(10)]
    weights = allocate(users, [users[:8]])            # 8 of 10 move together: 0.8 scaled to 0.5
    assert sum(weights[u] for u in users[:8]) == pytest.approx(0.5)
    assert weights["u8"] == weights["u9"] == pytest.approx(0.1)
    assert sum(weights.values()) == pytest.approx(0.7)


def daily_frame(series: dict[str, list[float]]) -> pl.DataFrame:
    start = date(2026, 9, 1)
    rows = [{"user": u, "date": start + timedelta(days=i), "ret": r}
            for u, rets in series.items() for i, r in enumerate(rets)]
    return pl.DataFrame(rows)


def test_correlation_groups_join_mirrored_traders_only():
    base = [0.01, -0.02, 0.015, -0.01, 0.02, -0.005, 0.01, -0.02, 0.03, -0.01, 0.005, -0.015, 0.02, -0.01]
    other = [-0.01, 0.01, -0.02, 0.02, 0.01, -0.01, -0.02, 0.01, -0.01, 0.02, -0.005, 0.01, -0.02, 0.005]
    daily = daily_frame({"a": base, "b": [r * 2 for r in base], "c": other})
    assert correlation_groups(daily, ["a", "b", "c"]) == [["a", "b"], ["c"]]
    # Too little overlap: no grouping, however correlated the few common days are
    assert correlation_groups(daily_frame({"a": base[:5], "b": base[:5]}), ["a", "b"]) == [["a"], ["b"]]


def test_daily_pnl_returns_from_month_period():
    rows = [{"user": "u", "period": "month", "time_ms": 1_700_000_000_000 + i * 86_400_000,
             "account_value": 1_000.0, "pnl": 10.0 * i} for i in range(5)]
    rows.append({"user": "u", "period": "allTime", "time_ms": 1_700_000_000_000, "account_value": 1.0, "pnl": 999.0})
    out = daily_pnl_returns(pl.DataFrame(rows), ["u"])
    assert out["ret"].to_list() == pytest.approx([0.01] * 4)


def test_weights_for_falls_back_to_equal_capped_without_data(monkeypatch):
    monkeypatch.setattr(risk, "_read", lambda table: None)
    weights, correlated = weights_for(["a", "b", "c", "d"])
    assert weights == {u: 0.25 for u in "abcd"} and correlated == []
    weights, _ = weights_for(["a", "b", "c"])
    assert weights == {u: 0.3 for u in "abc"}          # 1/3 breaches the 30% cap
