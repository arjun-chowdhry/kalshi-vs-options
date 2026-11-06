"""M2: the per-strike comparison table, the offset summary and the settlement check. Offline."""

import datetime as dt

import numpy as np
import pandas as pd
import pytest

from kvo import compare, options, settlement
from kvo.compare import BEYOND, NO_QUOTES

CLOCK = pd.Timestamp("2026-11-05T19:08:45Z")
INDEX = 7367.89990234375


@pytest.fixture(scope="module")
def day(spx_snapshot):
    raw, curve, _ = spx_snapshot
    return options.same_day_fit(raw, curve, "2026-11-05", INDEX, CLOCK)


def _bars(start_value=INDEX, step=0.0, minutes=31):
    times = pd.date_range(
        CLOCK.floor("min") - pd.Timedelta(minutes=minutes - 1), periods=minutes, freq="min"
    )
    close = start_value + step * np.arange(minutes)
    return pd.DataFrame({"time": times, "close": close})


def _kalshi_from_options(day, strikes, shift=0.0, half_spread=0.01):
    """Kalshi quotes that are exactly the options curve moved ``shift`` index points."""
    fit = day.fit.copy()
    fit["forward"] += shift
    mid = options.prob_above(fit, strikes, day.r)
    return pd.DataFrame(
        {
            "strike": strikes,
            "time": CLOCK.ceil("min"),
            "yes_bid": np.round(mid - half_spread, 4),
            "yes_ask": np.round(mid + half_spread, 4),
        }
    )


def test_no_quote_intervals_include_the_known_gap(day):
    gaps = compare.no_quote_intervals(day)
    assert (7300.0, 7390.0) in gaps  # the 2026-11-05T142350 gap (FEASIBILITY.md)
    assert all(b - a > compare.GRID for a, b in gaps)


def test_gap_and_beyond_strikes_are_never_assessed(day):
    strikes = np.arange(7200.0, 7500.0, 5.0)
    quotes = _kalshi_from_options(day, strikes, shift=-40.0)  # a huge disagreement everywhere
    table = compare.comparison_table(day, quotes, _bars())
    gap_rows = table[(table["strike"] > 7300) & (table["strike"] < 7390)]
    assert len(gap_rows) and (gap_rows["status"] == NO_QUOTES).all()
    used = day.used["strike"]
    out = table[(table["strike"] < used.min()) | (table["strike"] > used.max())]
    assert (out["status"] == BEYOND).all()
    assessed = table[~table["status"].isin([NO_QUOTES, BEYOND])]
    assert "beyond limit" in set(assessed["status"])  # a 40-point shift is detected somewhere


def test_limit_is_cost_plus_two_sigma_and_agreement_is_within(day):
    strikes = np.arange(7390.0, 7480.0, 5.0)
    table = compare.comparison_table(day, _kalshi_from_options(day, strikes), _bars())
    np.testing.assert_allclose(table["limit"], table["cost"] + 2 * table["sigma"])
    np.testing.assert_allclose(table["sigma"] ** 2, table["fit_se"] ** 2 + table["forward_se"] ** 2)
    assert (table["cost"] > (table["yes_ask"] - table["yes_bid"]) / 2).all()  # plus a fee
    assert not (table["status"] == "beyond limit").any()
    assert (table["fit_se"] > 0).all() and (table["forward_se"] > 0).all()


def test_fit_is_untouched_by_the_comparison(day):
    before = day.fit.copy()
    compare.comparison_table(day, _kalshi_from_options(day, [7400.0, 7420.0], shift=-20), _bars())
    pd.testing.assert_series_equal(day.fit, before)


def test_forward_error_takes_the_larger_of_parity_and_the_minute_move(day):
    fp, n = options.parity_check(day)
    calm, why = compare.forward_error(day, _bars(step=0.1))
    assert calm == pytest.approx(abs(fp - INDEX)) and "parity" in why
    wild, why = compare.forward_error(day, _bars(step=10.0))
    assert wild == pytest.approx(10.0) and "1-min" in why
    one_bar = _bars().tail(1)  # old snapshots: a single bar, so parity only
    assert compare.forward_error(day, one_bar)[0] == pytest.approx(abs(fp - INDEX))


def test_index_move_and_nan_without_history():
    bars = _bars(step=-1.0)
    assert compare.index_move(bars, CLOCK, 15) == pytest.approx(-15.0)
    assert np.isnan(compare.index_move(bars.tail(3), CLOCK, 15))


def test_offset_summary_recovers_a_known_shift_and_side(day):
    strikes = np.arange(7390.0, 7480.0, 5.0)
    quotes = _kalshi_from_options(day, strikes, shift=-3.0, half_spread=0.005)
    bars = _bars(step=-1.0)
    table = compare.comparison_table(day, quotes, bars)
    off = compare.offset_summary(day, table, bars, quotes)
    assert off.shift == pytest.approx(-3.0, abs=0.15)
    assert off.side == "options above"  # Kalshi lower, options above its ask
    assert off.below_bid == 0 and off.above_ask > 0
    assert off.move_15m == pytest.approx(-15.0)
    assert off.kalshi_lag_s == pytest.approx(15.0)


# --- settlement -------------------------------------------------------------------------------


def test_event_for_a_date():
    assert settlement.event_for(dt.date(2026, 11, 6)) == "KXINXU-26NOV06H1600"


def test_kalshi_settlement_reads_one_value_and_refuses_disagreement():
    m = pd.DataFrame({"settle_value": [7353.73, 7353.73], "status": ["finalized"] * 2})
    assert settlement.kalshi_settlement(m) == ("finalized", 7353.73)
    active = pd.DataFrame({"settle_value": [np.nan], "status": ["active"]})
    status, value = settlement.kalshi_settlement(active)
    assert status == "active" and np.isnan(value)
    with pytest.raises(ValueError):
        settlement.kalshi_settlement(m.assign(settle_value=[7353.73, 7353.74]))


def test_compare_match_mismatch_and_unsettled():
    d = dt.date(2026, 11, 5)
    assert settlement.compare(d, "E", "finalized", 7353.73, 7353.73)["match"] is True
    row = settlement.compare(d, "E", "finalized", 7353.73, 7353.75)
    assert row["match"] is False and row["diff"] == pytest.approx(-0.02)
    assert settlement.compare(d, "E", "active", np.nan, 7353.73)["match"] is None


def test_gspc_close_is_not_read_before_the_close():
    # Returns before any download, so the no-network guard is never hit.
    assert np.isnan(settlement.gspc_close(dt.date.today() + dt.timedelta(days=3)))
