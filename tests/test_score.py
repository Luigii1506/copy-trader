import sys
from pathlib import Path

import polars as pl
import pytest

sys.path.insert(0, str(Path(__file__).parent))
from test_persistence import equity_from_returns, world  # noqa: E402

from analysis.backtest import copy_backtest, random_baseline, summarize_backtest
from analysis.persistence import period_returns
from analysis.score import behavior_exclusions, explain, score_from_signals, top_by_score, top_by_sharpe_v2


def signals_frame():
    def row(user, sharpe, low_dd, consistency, n_obs=20, stability=-0.01, max_abs=0.3):
        return {"user": user, "n_obs": n_obs, "max_abs_ret": max_abs, "ret": sharpe / 10, "vol": 0.03,
                "sharpe": sharpe, "low_dd": low_dd, "pnl_usd": 1_000.0,
                "consistency": consistency, "stability": stability}
    return pl.DataFrame([
        row("good", sharpe=1.2, low_dd=-0.05, consistency=0.8),
        row("mid", sharpe=0.5, low_dd=-0.20, consistency=0.55),
        row("bad", sharpe=-0.2, low_dd=-0.60, consistency=0.35),
        row("levered", sharpe=2.0, low_dd=-0.10, consistency=0.9, max_abs=2.5),  # ineligible
    ])


def test_score_orders_by_quality_and_marks_ineligible():
    scored = score_from_signals(signals_frame())
    by = {r["user"]: r["trader_score"] for r in scored.to_dicts()}
    assert by["levered"] is None
    assert by["good"] > by["mid"] > by["bad"]
    assert 0 <= by["bad"] and by["good"] <= 100


def test_behavior_penalties_subtract_and_missing_is_neutral():
    behavior = pl.DataFrame({"user": ["good"], "liquidations": [2], "martingale_share": [0.7],
                             "p95_leverage": [20.0], "top_coin_share": [0.9]})
    clean = score_from_signals(signals_frame())
    scored = score_from_signals(signals_frame(), behavior)
    by = {r["user"]: r for r in scored.to_dicts()}
    clean_by = {r["user"]: r for r in clean.to_dicts()}
    assert by["good"]["behavior_penalty"] == 40.0
    assert by["good"]["trader_score"] == pytest.approx(clean_by["good"]["trader_score"] - 40.0)
    assert by["mid"]["behavior_penalty"] == 0.0 and by["mid"]["behavior_known"] is False
    assert by["mid"]["trader_score"] == pytest.approx(clean_by["mid"]["trader_score"])


def test_penalized_star_falls_below_a_clean_mid_trader():
    behavior = pl.DataFrame({"user": ["good"], "liquidations": [1], "martingale_share": [0.9],
                             "p95_leverage": [20.0], "top_coin_share": [0.2]})
    scored = score_from_signals(signals_frame(), behavior)
    by = {r["user"]: r["trader_score"] for r in scored.to_dicts()}
    assert by["good"] < by["mid"]          # ROI never fully buys back extreme risk (plan section 20)


def test_nan_sharpe_never_reaches_the_top():
    frame = pl.concat([signals_frame(), pl.DataFrame([{
        "user": "flat", "n_obs": 20, "max_abs_ret": 0.0, "ret": 0.0, "vol": 0.0, "sharpe": float("nan"),
        "low_dd": 0.0, "pnl_usd": 0.0, "consistency": 0.0, "stability": 0.0}])])
    by = {r["user"]: r["trader_score"] for r in score_from_signals(frame).to_dicts()}
    assert by["flat"] < by["good"]          # NaN sharpe must not rank as the best sharpe


def test_top_by_score_selector_and_explain():
    picked = top_by_score(2)(signals_frame(), None, 0)
    assert picked == ["good", "mid"]
    scored = score_from_signals(signals_frame())
    info = explain(scored, "good")
    assert info["eligible"] and set(info["components"]) == {"sharpe", "low_dd", "consistency", "n_obs", "stability"}
    assert explain(scored, "levered")["eligible"] is False


def test_walk_forward_score_beats_random_in_a_skilled_world():
    returns = period_returns(equity_from_returns(world(n_wallets=120, weeks=70), start_value=50_000.0), step_weeks=1)
    kw = dict(hold_weeks=4, rebalance_cost=0.0)
    score_run = summarize_backtest(copy_backtest(returns, top_by_score(10), **kw))
    rnd = random_baseline(returns, 10, seeds=8, **kw)
    assert score_run["total_return"] > rnd["total_return"].quantile(0.9)


def test_v2_excludes_by_behavior_and_ranks_by_sharpe():
    behavior = pl.DataFrame({"user": ["good", "mid"], "liquidations": [0, 3],
                             "martingale_share": [0.1, 0.1], "p95_leverage": [3.0, 3.0]})
    flagged = {r["user"]: r["exclusion_reason"] for r in behavior_exclusions(signals_frame(), behavior).to_dicts()}
    assert flagged == {"good": None, "mid": "liquidations", "bad": None, "levered": None}
    # mid is excluded (liquidated), levered is ineligible (max_abs_ret), unknown-behavior 'bad' stays.
    assert top_by_sharpe_v2(3, behavior)(signals_frame(), None, 0) == ["good", "bad"]


def test_v2_strategy_is_prepared_but_not_running():
    from papertrade.config import STRATEGIES, STRATEGIES_V2
    assert [s.name for s in STRATEGIES_V2] == ["sharpe_v2"]
    assert "sharpe_v2" not in [s.name for s in STRATEGIES]      # ADR-003 freeze


def test_v2_excludes_idle_accounts_that_v1_rewards():
    idle = pl.DataFrame([{"user": "idle", "n_obs": 6, "max_abs_ret": 0.0001, "ret": 0.0003, "vol": 0.00005,
                          "sharpe": 5.0, "low_dd": 0.0, "pnl_usd": 1.0, "consistency": 1.0, "stability": 0.0}])
    frame = pl.concat([signals_frame(), idle], how="diagonal_relaxed")
    v1 = score_from_signals(frame).sort("trader_score", descending=True, nulls_last=True)["user"].to_list()
    assert v1[0] == "idle"                                   # the v1 flaw, reproduced
    assert "idle" not in top_by_sharpe_v2(3)(frame, None, 0)  # v2 removes it before ranking
