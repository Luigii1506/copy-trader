"""TraderScore v1 (proyect.md sections 19-20, 22): deterministic, reproducible, backtestable.

Score = 100 x weighted cross-sectional percentile of curve components, minus flat behavior
penalties where fills are available. Percentiles (not raw values) make components comparable
and immune to outliers; the same trader can score differently on different dates because the
score is relative to that date's eligible pool - by design, selection is always relative.

The weights are the plan's starting point renormalized over the curve components (behavior
enters as penalties instead of a weighted component, because fills only exist for a subset of
wallets and a missing feature must not move a score). They are a hypothesis: copy_backtest with
`top_by_score` is the test, and the walk-forward split in the research notes is the judge.

Eligibility before scoring (same spirit as the live pool):
- max_abs_ret <= 1.0: a +/-100% two-week step is leverage a capped copier cannot mirror
- n_obs minimum comes from formation_signals' caller
"""

from __future__ import annotations

import polars as pl

# Plan section 19 (25/20/20/15/10/10) with the 10% behavior weight converted into penalties.
WEIGHTS = {
    "sharpe": 0.25,       # risk-adjusted return
    "low_dd": 0.20,       # shallow maximum drawdown
    "consistency": 0.20,  # share of profitable steps
    "n_obs": 0.15,        # longevity: how long we have observed them
    "stability": 0.10,    # same results in both halves of the window
}

# Plan section 20: flat deductions, so extreme ROI can never fully buy back extreme risk.
PENALTIES = [
    ("liquidations", lambda c: pl.col(c) > 0, 15.0),
    ("martingale_share", lambda c: pl.col(c) > 0.6, 10.0),
    ("p95_leverage", lambda c: pl.col(c) > 15.0, 10.0),
    ("top_coin_share", lambda c: pl.col(c) > 0.85, 5.0),
]
MAX_STEP_ABS_RET = 1.0


def score_from_signals(signals: pl.DataFrame, behavior: pl.DataFrame | None = None) -> pl.DataFrame:
    """Adds `trader_score` (0-100) to a formation_signals frame; ineligible rows get null.

    behavior: optional behavior_features frame (analysis.behavior); joined on user. Wallets
    without behavior data get no penalty and behavior_known=False."""
    eligible = pl.col("max_abs_ret") <= MAX_STEP_ABS_RET
    ranked = signals.with_columns([
        # Rank only finite values of eligible rows: polars sorts NaN above every number, so a
        # zero-variance wallet with NaN sharpe would otherwise land in the top percentile.
        (pl.when(eligible & pl.col(c).is_finite()).then(pl.col(c)).rank("average")
         / pl.when(eligible & pl.col(c).is_finite()).then(pl.col(c)).count())
        .alias(f"_pct_{c}")
        for c in WEIGHTS
    ])
    # A missing component (e.g. NaN sharpe) contributes its weight at the worst percentile (0),
    # so incomplete evidence lowers a score instead of hiding it.
    base = sum(pl.col(f"_pct_{c}").fill_null(0.0) * w for c, w in WEIGHTS.items()) / sum(WEIGHTS.values())
    out = ranked.with_columns(trader_score=pl.when(eligible).then(100 * base))
    out = out.drop([f"_pct_{c}" for c in WEIGHTS])

    if behavior is not None and not behavior.is_empty():
        cols = ["user"] + [c for c, _, _ in PENALTIES if c in behavior.columns]
        out = out.join(behavior.select(cols), on="user", how="left")
        penalty = sum(
            pl.when(cond(c).fill_null(False)).then(points).otherwise(0.0)
            for c, cond, points in PENALTIES if c in behavior.columns
        )
        out = (out.with_columns(
                   behavior_known=pl.col(PENALTIES[0][0]).is_not_null() if PENALTIES[0][0] in behavior.columns else pl.lit(False),
                   behavior_penalty=penalty)
               .with_columns(trader_score=(pl.col("trader_score") - pl.col("behavior_penalty")).clip(lower_bound=0.0))
               .drop([c for c, _, _ in PENALTIES if c in behavior.columns]))
    else:
        out = out.with_columns(behavior_known=pl.lit(False), behavior_penalty=pl.lit(0.0))
    return out


def top_by_score(n: int, behavior: pl.DataFrame | None = None):
    """Backtest selector (analysis.backtest): rank by TraderScore at each formation date."""
    def pick(signals: pl.DataFrame, at, seed: int) -> list[str]:
        scored = score_from_signals(signals, behavior)
        return (scored.filter(pl.col("trader_score").is_not_null())
                .sort("trader_score", descending=True).head(n)["user"].to_list())
    return pick


def explain(scored: pl.DataFrame, user: str) -> dict:
    """Why did this trader get this score? (plan section 47). Deterministic, from the same row."""
    row = scored.filter(pl.col("user") == user)
    if row.is_empty():
        return {"user": user, "error": "not scored"}
    r = row.to_dicts()[0]
    return {
        "user": user,
        "trader_score": None if r["trader_score"] is None else round(r["trader_score"], 1),
        "components": {c: round(r[c], 4) if r[c] is not None else None for c in WEIGHTS},
        "behavior_penalty": r.get("behavior_penalty", 0.0),
        "behavior_known": r.get("behavior_known", False),
        "eligible": r["max_abs_ret"] <= MAX_STEP_ABS_RET,
    }
