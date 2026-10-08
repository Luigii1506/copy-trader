from datetime import datetime, timedelta, timezone

import polars as pl
import pytest

from analysis.behavior import behavior_features, gross_exposure, perp_fills, round_trips

NOW = datetime(2026, 10, 7, tzinfo=timezone.utc)
T0 = int((NOW - timedelta(days=60)).timestamp() * 1000)
H = 3_600_000


class Tape:
    """Builds a fills table from a sequence of (coin, signed size, price) per user, keeping the
    position bookkeeping (start_position, dir, closedPnl) consistent the way the exchange does."""

    def __init__(self):
        self.rows, self.t, self.tid = [], T0, 0
        self.pos: dict[tuple[str, str], tuple[float, float]] = {}  # (user, coin) -> (size, avg entry)

    def fill(self, user, coin, signed, px, hours=1.0, liquidated=False, spot=False):
        self.t += int(hours * H)
        self.tid += 1
        size, entry = self.pos.get((user, coin), (0.0, 0.0))
        after = size + signed
        pnl = 0.0
        if spot:
            d = "Buy" if signed > 0 else "Sell"
        elif size == 0:
            d = "Open Long" if signed > 0 else "Open Short"
        elif size * after < 0:
            d = "Long > Short" if size > 0 else "Short > Long"
            pnl = (px - entry) * size
        elif abs(after) > abs(size):
            d = "Open Long" if size > 0 else "Open Short"
        else:
            d = "Close Long" if size > 0 else "Close Short"
            pnl = (px - entry) * (-signed)
        if not spot:
            if after == 0:
                self.pos.pop((user, coin), None)
            elif size * after < 0 or size == 0:
                self.pos[(user, coin)] = (after, px)
            elif abs(after) > abs(size):
                self.pos[(user, coin)] = (after, (entry * abs(size) + px * abs(signed)) / abs(after))
            else:
                self.pos[(user, coin)] = (after, entry)
        self.rows.append({"user": user, "time_ms": self.t, "coin": coin, "side": "B" if signed > 0 else "A",
                          "dir": d, "px": px, "sz": abs(signed), "start_position": size, "closed_pnl": pnl,
                          "fee": abs(signed) * px * 0.00045, "liquidated": liquidated, "oid": self.tid, "tid": self.tid})
        return self

    def frame(self):
        return pl.DataFrame(self.rows)


def equity_curve(user, value):
    return pl.DataFrame({"user": [user] * 2, "period": ["allTime"] * 2,
                         "time_ms": [T0 - H, int(NOW.timestamp() * 1000)], "account_value": [value, value], "pnl": [0.0, 0.0]})


def test_round_trips_track_adds_and_label_averaging_down():
    tape = (Tape().fill("u", "BTC", 1, 100).fill("u", "BTC", 1, 90).fill("u", "BTC", 1, 110).fill("u", "BTC", -3, 95))
    [t] = round_trips(perp_fills(tape.frame())).to_dicts()
    assert t["n_adds"] == 2 and t["n_adds_losing"] == 1       # the add at 90 was below the running average
    assert t["avg_entry"] == pytest.approx(100.0)
    assert t["realized_pnl"] == pytest.approx((95 - 100) * 3)
    assert t["max_notional"] == pytest.approx(330.0)
    assert t["duration_h"] == pytest.approx(3.0)


def test_flip_splits_into_two_trades():
    tape = Tape().fill("u", "ETH", 2, 100).fill("u", "ETH", -5, 120).fill("u", "ETH", 3, 110)
    trades = round_trips(perp_fills(tape.frame()))
    assert trades["side"].to_list() == ["long", "short"]
    assert trades["realized_pnl"].to_list() == pytest.approx([40.0, 30.0])
    assert trades["closed_ms"].null_count() == 0


def test_spot_fills_are_ignored():
    tape = Tape().fill("u", "PURR/USDC", 10, 1, spot=True).fill("u", "BTC", 1, 100).fill("u", "BTC", -1, 101)
    assert round_trips(perp_fills(tape.frame())).height == 1


def test_gross_exposure_sums_coins_and_divides_by_equity():
    tape = Tape().fill("u", "BTC", 1, 100).fill("u", "ETH", -2, 50).fill("u", "BTC", -1, 100)
    exp = gross_exposure(perp_fills(tape.frame()), equity_curve("u", 50.0))
    assert exp["gross"].to_list() == pytest.approx([100.0, 200.0, 100.0])
    assert exp["leverage"].to_list() == pytest.approx([2.0, 4.0, 2.0])


def test_sparse_equity_uses_larger_neighbor_and_rejects_impossible_leverage():
    tape = Tape().fill("u", "BTC", 10, 100)            # $1,000 gross
    t = tape.rows[0]["time_ms"]
    # Equity sampled 10 days before ($20: implies 50x+) and 3 days after ($500, after a deposit)
    eq = pl.DataFrame({"user": ["u", "u"], "period": ["allTime", "allTime"],
                       "time_ms": [t - 10 * 24 * H, t + 3 * 24 * H], "account_value": [20.0, 500.0], "pnl": [0.0, 0.0]})
    [row] = gross_exposure(perp_fills(tape.frame()), eq).to_dicts()
    assert row["equity"] == 500.0 and row["leverage"] == pytest.approx(2.0)

    eq_tiny = eq.with_columns(pl.lit(2.0).alias("account_value"))     # both samples imply 500x
    [row] = gross_exposure(perp_fills(tape.frame()), eq_tiny).to_dicts()
    assert row["leverage"] is None


def test_equity_points_merge_periods():
    from analysis.behavior import equity_points
    eq = pl.DataFrame({"user": ["u"] * 3, "period": ["allTime", "month", "month"],
                       "time_ms": [1, 1, 2], "account_value": [10.0, 10.0, 12.0], "pnl": [0.0, 0.0, 2.0]})
    assert equity_points(eq)["time_ms"].to_list() == [1, 2]


def martingale_tape(user, double_after_loss):
    tape, size = Tape(), 1.0
    for i in range(12):
        win = i % 2 == 0
        tape.fill(user, "BTC", size, 100).fill(user, "BTC", -size, 101 if win else 99)
        if double_after_loss and not win:
            size *= 2
        elif not double_after_loss:
            size = 1.0
    return tape


def test_martingale_detected_against_constant_sizing():
    f = pl.concat([martingale_tape("mart", True).frame(), martingale_tape("flat", False).frame()])
    eq = pl.concat([equity_curve("mart", 1e6), equity_curve("flat", 1e6)])
    feats = behavior_features(f, eq, NOW).sort("user")
    by = {r["user"]: r for r in feats.to_dicts()}
    assert by["mart"]["post_loss_size_ratio"] == pytest.approx(2.0) and by["mart"]["martingale_share"] == 1.0
    assert by["mart"]["post_win_size_ratio"] == pytest.approx(1.0)
    assert by["flat"]["post_loss_size_ratio"] == pytest.approx(1.0) and by["flat"]["martingale_share"] == 0.0
    assert by["flat"]["win_rate"] == pytest.approx(0.5)


def test_features_report_concentration_liquidations_and_window_coverage():
    tape = Tape()
    for _ in range(5):
        tape.fill("u", "BTC", 10, 100).fill("u", "BTC", -10, 101)
    tape.fill("u", "DOGE", 100, 0.1).fill("u", "DOGE", -100, 0.05, liquidated=True)
    feats = behavior_features(tape.frame(), equity_curve("u", 500.0), NOW).to_dicts()[0]
    assert feats["n_coins"] == 2 and feats["top_coin_share"] > 0.99
    assert feats["liquidations"] == 1
    assert feats["max_leverage"] == pytest.approx(2.0)
    assert feats["window_complete"] is False   # first fill is inside the 90-day window


def style_change_tape():
    tape = Tape()
    for _ in range(10):                       # first ~20 h: small, 1-hour trades
        tape.fill("u", "BTC", 1, 100).fill("u", "BTC", -1, 100)
    tape.t = int((NOW - timedelta(days=10)).timestamp() * 1000)
    for _ in range(5):                        # last 10 days: 4x bigger, 4-hour trades
        tape.fill("u", "BTC", 4, 100).fill("u", "BTC", -4, 100, hours=4)
    return tape


def test_style_change_ratios():
    feats = behavior_features(style_change_tape().frame(), equity_curve("u", 1000.0), NOW).to_dicts()[0]
    assert feats["change_size"] == pytest.approx(4.0)
    assert feats["change_duration"] == pytest.approx(4.0)
    assert feats["coin_overlap"] == 1.0


def test_size_change_is_relative_to_equity():
    """4x bigger trades on 4x more capital is the same behavior."""
    cut = int((NOW - timedelta(days=10)).timestamp() * 1000)
    eq = pl.DataFrame({"user": ["u"] * 3, "period": ["allTime"] * 3,
                       "time_ms": [T0 - H, cut - H, int(NOW.timestamp() * 1000)],
                       "account_value": [1000.0, 4000.0, 4000.0], "pnl": [0.0, 0.0, 0.0]})
    feats = behavior_features(style_change_tape().frame(), eq, NOW).to_dicts()[0]
    assert feats["change_size"] == pytest.approx(1.0)


def test_copyability_penalizes_invisible_and_fragmented_trades():
    tape = Tape()
    for _ in range(6):                        # scalper: in and out within a minute -> invisible to a 60 s poll
        tape.fill("s", "BTC", 1, 100).fill("s", "BTC", -1, 100.1, hours=0.01)
    for _ in range(6):                        # swing trader: holds for a day, exits in three slices
        tape.fill("w", "ETH", 3, 100).fill("w", "ETH", -1, 101, hours=24).fill("w", "ETH", -1, 102).fill("w", "ETH", -1, 103)
    eq = pl.concat([equity_curve("s", 1e6), equity_curve("w", 1e6)])
    by = {r["user"]: r for r in behavior_features(tape.frame(), eq, NOW).to_dicts()}
    assert by["s"]["invisible_share"] == 1.0 and by["s"]["copyability_estimate"] == 0.0
    assert by["w"]["invisible_share"] == 0.0 and by["w"]["median_partial_exits"] == 2
    assert by["w"]["copyability_estimate"] == pytest.approx(100 / 1.2)
