"""Kalshi lookup at the quote clock, the after-the-fit comparison, the report, the snapshot
files. All offline."""

import json

import numpy as np
import pandas as pd
import pytest
from optdesk.data.rates import RateCurve

from kvo import kalshi, options
from kvo.compare import kalshi_check
from kvo.report import same_day_report
from kvo.snapshot import add_to_snapshot, load_snapshot, save_snapshot

CLOCK = pd.Timestamp("2026-11-05T19:08:45Z")
INDEX = 7367.89990234375


def test_candle_at_takes_the_minute_covering_the_clock():
    candles = pd.DataFrame(
        {
            "time": pd.to_datetime(["2026-11-05T19:08Z", "2026-11-05T19:09Z", "2026-11-05T19:10Z"]),
            "yes_bid": [0.44, 0.40, 0.48],
            "yes_ask": [0.45, 0.41, 0.49],
        }
    )
    row = kalshi.candle_at(candles, CLOCK)  # 19:08:45 is in the minute ending 19:09
    assert row["yes_bid"] == 0.40
    assert kalshi.candle_at(candles, pd.Timestamp("2026-11-05T19:20Z")) is None
    assert kalshi.candle_at(candles.iloc[2:], CLOCK) is None  # covering minute missing


def test_kalshi_check_compares_without_touching_the_fit(spx_snapshot):
    raw, curve, _ = spx_snapshot
    day = options.same_day_fit(raw, curve, "2026-11-05", INDEX, CLOCK)
    before = day.fit.copy()
    quotes = pd.DataFrame(
        {
            "strike": [7300.0, 7400.0, 7600.0],
            "yes_bid": [0.0, 0.20, np.nan],
            "yes_ask": [1.0, 0.30, 0.01],
        }
    )
    quotes.loc[0, ["yes_bid", "yes_ask"]] = [0.10, 0.12]  # far below the options probability
    table = kalshi_check(day, quotes)
    assert table["strike"].tolist() == [7300.0, 7400.0]  # one-sided 7600 dropped
    assert table["outside"].tolist() == [True, False]
    pd.testing.assert_series_equal(day.fit, before)


def test_report_lines_offline(spx_snapshot):
    raw, curve, meta = spx_snapshot
    bars = pd.DataFrame(
        {"time": [pd.Timestamp(meta["spx_bar_time"])], "close": [meta["spx_bar_value"]]}
    )
    day, lines = same_day_report(raw, curve, "2026-11-05", bars)
    text = "\n".join(lines)
    assert day.fit is not None
    for expected in (
        "quote clock 14:08:45 ET",
        "SPX index at the quote clock: 7367.90",
        "RMSE",
        "ATM vol",
        "Largest strike gap near the money: 7300 to 7390",
        "stale near the money",
        "Kalshi sanity check (after the fit, not used in it): no Kalshi prices",
    ):
        assert expected in text


def test_report_refuses_without_an_index_bar_near_the_clock(spx_snapshot):
    raw, curve, _ = spx_snapshot
    bars = pd.DataFrame({"time": [pd.Timestamp("2026-11-05T18:00Z")], "close": [7350.0]})
    day, lines = same_day_report(raw, curve, "2026-11-05", bars)
    assert day is None and "not fitting" in lines[-1]


def _tables():
    asof = pd.Timestamp("2026-11-05T19:23:50Z")
    kal = pd.DataFrame({"asof": [asof], "strike": [7370.0]})
    opts = pd.DataFrame({"asof": [asof], "strike": [7370.0]})
    curve = RateCurve.from_dict({"tenors": [0.25, 5.0], "rates": [0.04, 0.045]})
    return kal, opts, curve


def test_snapshot_round_trip_with_bars_and_kalshi_at_quote(tmp_path):
    kal, opts, curve = _tables()
    bars = pd.DataFrame({"time": [CLOCK.floor("min")], "close": [INDEX]})
    at_quote = pd.DataFrame(
        {"ticker": ["T"], "strike": [7370.0], "yes_bid": [0.47], "yes_ask": [0.49]}
    )
    folder = save_snapshot(
        kal, kal, opts, curve, {"x": 1}, tmp_path, spx_bars=bars, kalshi_at_quote=at_quote
    )
    snap = load_snapshot(folder)
    pd.testing.assert_frame_equal(snap.spx_bars, bars)
    pd.testing.assert_frame_equal(snap.kalshi_at_quote, at_quote)


def test_old_snapshot_gets_its_one_bar_from_meta_and_never_overwrites(tmp_path):
    kal, opts, curve = _tables()
    meta = {"spx_bar_time": "2026-11-05T19:08:00+00:00", "spx_bar_value": INDEX}
    folder = save_snapshot(kal, kal, opts, curve, meta, tmp_path)
    snap = load_snapshot(folder)
    assert snap.spx_bars["close"].tolist() == [INDEX]
    assert snap.kalshi_at_quote.empty
    extra = pd.DataFrame({"strike": [7370.0]})
    add_to_snapshot(folder, "kalshi_at_quote", extra)
    with pytest.raises(FileExistsError):
        add_to_snapshot(folder, "kalshi_at_quote", extra)
    with pytest.raises(FileExistsError):
        add_to_snapshot(folder, "options", extra)  # raw downloads are never replaced
    assert json.loads((folder / "meta.json").read_text())["spx_bar_value"] == INDEX
