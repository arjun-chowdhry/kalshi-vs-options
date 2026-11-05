"""Same-day cleaning and fitting, on the real 2026-11-05 chain and on synthetic chains.

The real chain (tests/fixtures/spx_0dte_2026-11-05T142350.*) is the regression case: Yahoo's
put bid/asks from 7305 up were corrupted, and the old cleaning fitted it with a forward of
7438.75 (index 7367.90) and an RMSE of 20.6 vol points.
"""

import numpy as np
import pandas as pd
import pytest
from optdesk.data.clean import clean_chain, year_fraction
from optdesk.data.rates import RateCurve
from optdesk.pricing.black_scholes import bs_price
from scipy.stats import norm

from kvo import options

EXPIRY = "2026-11-05"
CLOCK = pd.Timestamp("2026-11-05T19:08:45Z")  # latest trade in the fixture chain
INDEX = 7367.89990234375  # 1-minute SPX bar starting 19:08 UTC


@pytest.fixture(scope="module")
def day(spx_snapshot):
    raw, curve, _ = spx_snapshot
    return options.same_day_fit(raw, curve, EXPIRY, INDEX, CLOCK)


def _reason(day, strike, side):
    q = day.quotes
    return q.loc[(q["strike"] == strike) & (q["option_type"] == side), "reason"].iloc[0]


# --- clock, index, time to expiry ------------------------------------------------------------


def test_quote_clock_is_the_latest_trade(spx_snapshot):
    raw, _, _ = spx_snapshot
    assert options.quote_time(raw, EXPIRY) == CLOCK
    assert options.quote_age_minutes(raw, EXPIRY) == pytest.approx(15.1, abs=0.05)


def test_index_at_takes_the_bar_covering_the_clock():
    bars = pd.DataFrame(
        {
            "time": pd.to_datetime(["2026-11-05T19:07Z", "2026-11-05T19:08Z", "2026-11-05T19:09Z"]),
            "close": [7360.0, 7367.9, 7375.0],
        }
    )
    assert options.index_at(bars, CLOCK) == (pd.Timestamp("2026-11-05T19:08Z"), 7367.9)
    with pytest.raises(ValueError, match="no 1-minute SPX bar"):
        options.index_at(bars, pd.Timestamp("2026-11-05T19:30Z"))  # latest bar 21 min old
    with pytest.raises(ValueError):
        options.index_at(bars, pd.Timestamp("2026-11-05T19:00Z"))  # before the first bar


def test_forward_and_time_to_expiry_come_from_the_quote_clock(day):
    assert day.forward == INDEX
    assert day.T * 365 * 24 == pytest.approx(1.854, abs=0.001)  # 14:08:45 -> 16:00 ET
    assert (day.quotes["T"] == day.T).all()


# --- the regression: what the old cleaning did, and what we do now ---------------------------


def test_old_cleaning_is_fooled_by_the_bad_puts(spx_snapshot):
    raw, curve, _ = spx_snapshot
    old = clean_chain(raw, curve, american=False, min_days=0)
    assert old["forward"].iloc[0] == pytest.approx(7438.75, abs=0.01)


def test_fit_is_tight_and_atm_vol_sensible(day):
    f = day.fit
    assert f["success"]
    assert f["n"] >= 15
    assert f["rmse"] < 0.02  # under 2 vol points (was 20.6)
    assert 0.50 < f["atm_vol"] < 0.60


def test_only_out_of_the_money_quotes_are_fitted(day):
    used = day.used
    puts, calls = used[used["option_type"] == "put"], used[used["option_type"] == "call"]
    assert (puts["strike"] < INDEX).all() and (calls["strike"] >= INDEX).all()
    assert (used["source"] == "quote").all()


@pytest.mark.parametrize("strike", range(7305, 7370, 5))
def test_puts_off_their_own_tape_are_dropped(day, strike):
    # mids 1-14 points below trades in the same contract from under a minute before the clock
    assert _reason(day, strike, "put") == "off_tape"


@pytest.mark.parametrize("strike", [7460, 7465, 7470, 7480, 7485, 7490])
def test_calls_untraded_for_over_15_minutes_are_stale(day, strike):
    assert _reason(day, strike, "call") == "stale"


def test_no_arbitrage_alone_catches_the_worst_puts(spx_snapshot):
    """Second line of defence: even without the tape check, 7330-7365 break monotonicity."""
    raw, _, _ = spx_snapshot
    q = raw[(raw["bid"] > 0) & (CLOCK - raw["last_trade"] <= pd.Timedelta(minutes=15))]
    otm = q[np.where(q["option_type"] == "call", q["strike"] >= INDEX, q["strike"] < INDEX)]
    bad = options.otm_arbitrage(
        otm["strike"].to_numpy(),
        otm["bid"].to_numpy(),
        otm["ask"].to_numpy(),
        (otm["option_type"] == "call").to_numpy(),
        INDEX,
        1.0,
    )
    flagged = set(otm.loc[bad, "strike"])
    assert set(range(7330, 7370, 5)) <= flagged
    assert not flagged & {7290.0, 7295.0, 7300.0, 7390.0, 7400.0}  # good quotes kept


def test_parity_check_ignores_quotes_below_intrinsic(day):
    F, n = options.parity_check(day)
    assert n >= 1
    assert abs(F - INDEX) < 10  # the old rule said 7438.75


def test_itm_calls_are_checked_and_rejected(day):
    itm = day.itm_calls
    assert not itm["sane"]
    assert "butterfly" in itm["why"]  # 7320 / 7325 / 7340 calls are not convex
    assert set(itm["table"]["strike"]) >= {7310.0, 7320.0, 7325.0, 7340.0, 7360.0}


def test_strike_gap_and_svi_kink_are_reported(day):
    lo, hi = options.largest_gap(day.used, INDEX, day.expected_move)
    assert (lo, hi) == (7300.0, 7390.0)
    vertex, width = options.svi_kink(day.fit)
    assert lo < vertex < hi and width < 5


def test_prob_above_is_a_decreasing_probability(day):
    K = np.arange(7250, 7500, 5.0)
    p = options.prob_above(day.fit, K, day.r)
    assert ((p >= 0) & (p <= 1)).all()
    assert (np.diff(p) <= 1e-9).all()


# --- small synthetic cases -----------------------------------------------------------------


def test_off_tape_needs_a_fresh_trade_and_a_real_gap():
    t = CLOCK
    chain = pd.DataFrame(
        {
            "bid": [3.2, 3.2, 3.2, 15.3],
            "ask": [3.3, 3.3, 3.3, 15.5],
            "last": [5.2, 5.2, 3.4, 15.3],
            "last_trade": [t, t - pd.Timedelta(minutes=5), t, t],
        }
    )
    # stale trade: no evidence; within max(0.5, 20%): fine
    assert options.off_tape(chain, t).tolist() == [True, False, False, False]


def test_arbitrage_needs_a_tradeable_violation():
    K = np.array([7290.0, 7295.0, 7300.0, 7400.0])
    bid = np.array([2.75, 2.65, 3.10, 12.1])
    ask = np.array([2.85, 2.75, 3.20, 12.3])
    call = np.array([False, False, False, True])
    # 7295 is cheaper than 7290 only inside the spread (its ask 2.75 >= 7290's bid 2.75)
    assert not options.otm_arbitrage(K, bid, ask, call, 7368.0, 1.0).any()
    ask[1] = 2.70
    assert options.otm_arbitrage(K, bid, ask, call, 7368.0, 1.0).tolist() == [
        False,
        True,
        False,
        False,
    ]


def _flat_chain(vol=0.5, F=7370.0, bad_puts=()):
    """A same-day chain priced at one flat vol, quoted 0.05 wide, every contract just traded.
    Puts in ``bad_puts`` are quoted at 1.00/1.10 while their last trade shows the true price."""
    curve = RateCurve.from_dict({"tenors": [0.25, 5.0], "rates": [0.04, 0.045]})
    T = float(year_fraction(CLOCK, pd.Timestamp(EXPIRY)))
    r = float(curve(np.array([T]))[0])
    rows = []
    for K in np.arange(7200.0, 7555.0, 5.0):
        for side in ("call", "put"):
            price = float(bs_price(F, K, T, r, vol, r, side == "call"))
            bid, ask = price - 0.025, price + 0.025
            if side == "put" and K in bad_puts:
                bid, ask = 1.0, 1.1
            rows.append(
                {
                    "ticker": "^SPX",
                    "asof": CLOCK + pd.Timedelta(minutes=15),
                    "expiry": pd.Timestamp(EXPIRY),
                    "option_type": side,
                    "contract": f"SPXW{side[0]}{K:.0f}",
                    "strike": K,
                    "bid": bid,
                    "ask": ask,
                    "last": price,
                    "last_trade": CLOCK - pd.Timedelta(seconds=10),
                }
            )
    return pd.DataFrame(rows), curve, T, r


def test_flat_smile_is_recovered():
    raw, curve, T, r = _flat_chain()
    day = options.same_day_fit(raw, curve, EXPIRY, 7370.0, CLOCK)
    assert day.fit["rmse"] < 1e-3
    assert day.fit["atm_vol"] == pytest.approx(0.5, abs=1e-3)
    K = np.array([7320.0, 7370.0, 7420.0])
    d2 = (np.log(7370.0 / K) - 0.5 * 0.5**2 * T) / (0.5 * np.sqrt(T))
    assert options.prob_above(day.fit, K, r) == pytest.approx(norm.cdf(d2), abs=0.01)


def test_sane_itm_calls_stand_in_for_bad_puts():
    bad = (7330.0, 7340.0, 7350.0, 7360.0)
    raw, curve, _, _ = _flat_chain(bad_puts=bad)
    day = options.same_day_fit(raw, curve, EXPIRY, 7370.0, CLOCK)
    assert day.itm_calls["sane"], day.itm_calls["why"]
    synth = day.used[day.used["source"] == "itm_call"]
    assert set(synth["strike"]) == set(bad)
    assert synth["iv"].to_numpy() == pytest.approx(0.5, abs=0.005)
    assert day.fit["rmse"] < 0.005


def test_itm_calls_not_used_when_disabled():
    raw, curve, _, _ = _flat_chain(bad_puts=(7340.0,))
    day = options.same_day_fit(raw, curve, EXPIRY, 7370.0, CLOCK, use_itm_calls=False)
    assert (day.used["source"] == "quote").all()
    assert 7340.0 not in set(day.used.loc[day.used["option_type"] == "put", "strike"])
