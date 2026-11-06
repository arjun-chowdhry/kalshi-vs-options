"""M3 paper trades: which strikes each rule trades, settlement, and the summary. Offline."""

import numpy as np
import pandas as pd
import pytest

from kvo import paper
from kvo.compare import BEYOND, NO_QUOTES


def _table():
    """Five strikes: one clear YES, one clear NO, one too small to beat the fee, one in the
    no-quote gap, one beyond the limit (strict trades it)."""
    t = pd.DataFrame(
        {
            "strike": [7400.0, 7410.0, 7420.0, 7430.0, 7440.0],
            "yes_bid": [0.48, 0.40, 0.30, 0.20, 0.10],
            "yes_ask": [0.50, 0.42, 0.32, 0.22, 0.12],
            "p_options": [0.55, 0.35, 0.325, 0.30, 0.30],
            "status": ["within limit", "within limit", "within limit", NO_QUOTES, "beyond limit"],
        }
    )
    t["kalshi_mid"] = (t["yes_bid"] + t["yes_ask"]) / 2
    t["diff"] = t["p_options"] - t["kalshi_mid"]
    return t


def test_naive_buys_past_the_fee_both_sides_and_strict_only_beyond_the_limit():
    book = paper.trades(_table(), "S", "2026-11-05")
    naive = book[book["rule"] == "naive"].set_index("strike")
    # 7400: 0.55 > 0.50 + 0.02 fee -> YES. 7410: 0.35 < 0.40 - 0.02 -> NO. 7420: 0.325 - 0.32
    # doesn't cover the 2-cent fee. 7430 (gap) and 7440 trade YES.
    assert naive["side"].to_dict() == {7400.0: "yes", 7410.0: "no", 7430.0: "yes", 7440.0: "yes"}
    assert naive.loc[7410.0, "price"] == pytest.approx(0.60)  # NO costs 1 - bid
    assert naive.loc[7430.0, "in_gap"] and not naive.loc[7400.0, "in_gap"]
    strict = book[book["rule"] == "strict"]
    assert strict["strike"].tolist() == [7440.0] and strict["side"].tolist() == ["yes"]
    yes = naive.loc[7400.0]
    assert yes["edge"] == pytest.approx(0.55 - 0.50 - 0.02)


def test_gap_and_beyond_strikes_never_trade_strictly_even_with_a_huge_gap():
    t = _table()
    t["status"] = [NO_QUOTES, BEYOND, NO_QUOTES, BEYOND, NO_QUOTES]
    t["p_options"] = 0.99
    t["diff"] = t["p_options"] - t["kalshi_mid"]
    book = paper.trades(t, "S", "2026-11-05")
    assert (book["rule"] == "strict").sum() == 0
    assert book.loc[book["rule"] == "naive", "in_gap"].all()


def test_settle_uses_at_or_above_and_leaves_unknown_days_open():
    book = pd.DataFrame(
        {
            "rule": "naive",
            "snapshot": "S",
            "day": ["d1", "d1", "d1", "d2"],
            "strike": [7400.0, 7400.0, 7401.0, 7400.0],
            "side": ["yes", "no", "yes", "yes"],
            "price": [0.50, 0.50, 0.50, 0.50],
            "fee": [0.02, 0.02, 0.02, 0.02],
            "edge": 0.0,
            "in_gap": False,
        }
    )
    out = paper.settle(book, {"d1": 7400.00})
    assert out["won"].iloc[:3].tolist() == [True, False, False]  # 7400.00 is "above 7399.9999"
    np.testing.assert_allclose(out["pnl"].iloc[:3], [0.48, -0.52, -0.52])
    assert np.isnan(out["pnl"].iloc[3])


def test_summary_standard_errors_and_one_day_honesty():
    rows = []
    for day, pnls in (("d1", [0.5, -0.5, 0.5]), ("d2", [-0.5, -0.5])):
        for x in pnls:
            rows.append(
                {
                    "rule": "naive",
                    "snapshot": day,
                    "day": day,
                    "side": "yes",
                    "won": x > 0,
                    "pnl": x,
                    "edge": 0.01,
                    "in_gap": False,
                }
            )
    settled = pd.DataFrame(rows)
    s = paper.summarise(settled).set_index("rule")
    naive = s.loc["naive"]
    assert naive["n_settled"] == 5 and naive["settled_days"] == 2 and naive["wins"] == 2
    assert naive["pnl_total"] == pytest.approx(-0.5)
    assert naive["se_iid"] == pytest.approx(np.std([0.5, -0.5, 0.5, -0.5, -0.5], ddof=1) / 5**0.5)
    day_means = np.array([1 / 6, -0.5])
    assert naive["se_day"] == pytest.approx(day_means.std(ddof=1) / 2**0.5)
    one_day = paper.summarise(settled[settled["day"] == "d1"]).set_index("rule")
    assert np.isnan(one_day.loc["naive", "se_day"])  # one day: no honest standard error
    assert s.loc["strict", "n_trades"] == 0
