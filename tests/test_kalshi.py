"""Parsing Kalshi's public market JSON (real responses saved in tests/fixtures)."""

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from kvo import kalshi

FIXTURE = Path(__file__).parent / "fixtures" / "kalshi_markets.json"
ASOF = pd.Timestamp("2026-11-05T00:06:00Z")


@pytest.fixture
def table():
    return kalshi.markets_table(json.loads(FIXTURE.read_text())["markets"], ASOF)


def test_strikes_are_sorted_and_rounded_to_index_decimals(table):
    assert table["strike"].is_monotonic_increasing
    # KXINX lists 7899.9999, meaning "7,900 or above"
    assert 7900.0 in table["strike"].to_numpy()
    assert set(table["strike"]) >= {7685.0, 7690.0, 7695.0, 7745.0}


def test_empty_book_sides_are_missing_not_prices(table):
    settled = table[table["status"] == "finalized"]
    assert settled["yes_bid"].isna().all()  # bid 0.00
    assert settled["yes_ask"].isna().all()  # ask 1.00
    row = table[table["ticker"] == "KXINXU-26NOV05H1600-T7744.9999"].iloc[0]
    assert row["yes_bid"] == pytest.approx(0.03)
    assert row["yes_ask"] == pytest.approx(0.79)


def test_settlement_matches_strike(table):
    # Nov 4 settled at 7688.62: at-or-above 7685 is YES, 7690 and 7695 are NO
    settled = table[table["status"] == "finalized"]
    assert np.allclose(settled["settle_value"], 7688.62)
    expected = np.where(settled["settle_value"] >= settled["strike"], "yes", "no")
    assert (settled["result"] == expected).all()


def test_next_close_event_picks_earliest_4pm():
    events = [
        {"event_ticker": "KXINXU-26NOV06H1600", "strike_date": "2026-11-06T21:00:00Z"},
        {"event_ticker": "KXINXU-26NOV05H1500", "strike_date": "2026-11-05T20:00:00Z"},
        {"event_ticker": "KXINXU-26NOV05H1600", "strike_date": "2026-11-05T21:00:00Z"},
    ]
    assert kalshi.next_close_event(events) == "KXINXU-26NOV05H1600"
    with pytest.raises(ValueError):
        kalshi.next_close_event(events[1:2])


def test_fetch_markets_follows_the_cursor(monkeypatch):
    pages = iter([{"markets": [{"a": 1}], "cursor": "next"}, {"markets": [{"a": 2}], "cursor": ""}])
    seen = []

    def fake_get(path, params=None):
        seen.append(params.get("cursor"))
        return next(pages)

    monkeypatch.setattr(kalshi, "_get", fake_get)
    assert kalshi.fetch_markets("EVENT") == [{"a": 1}, {"a": 2}]
    assert seen == [None, "next"]


def test_candles_table():
    candles = [
        {
            "end_period_ts": 1793802600,
            "volume_fp": "3.00",
            "yes_bid": {"close_dollars": "0.2600"},
            "yes_ask": {"close_dollars": "0.3100"},
        }
    ]
    out = kalshi.candles_table(candles)
    assert out["time"].iloc[0] == pd.Timestamp("2026-11-04T14:30:00Z")
    assert out["yes_bid"].iloc[0] == pytest.approx(0.26)
    assert out["yes_ask"].iloc[0] == pytest.approx(0.31)
