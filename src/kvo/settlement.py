"""After the close: does Kalshi's settlement value equal the S&P 500 close on Yahoo?

Kalshi publishes the index value it settled on as ``expiration_value`` on every market of the
event (``settle_value`` in ``kalshi.markets_table``). On 2026-11-03 and 11-04 it equalled
Yahoo's ``^GSPC`` close to the cent. From Friday 2026-11-06 Kalshi's source agency for this
event is S&P Global Inc. instead (see docs/FEASIBILITY.md), so this check is repeated for every
day we have a snapshot, to catch any mismatch the change brings.

When it can run: Kalshi settled the 2026-11-04 event at 7:01pm New York (``settlement_ts``),
three hours after the close, so a check before then reports "not settled yet". Read-only: two
public GETs to Kalshi (the event's markets) and one Yahoo download.
"""

from __future__ import annotations

import datetime as dt

import numpy as np
import pandas as pd
import yfinance as yf

from kvo import kalshi

__all__ = [
    "MATCH_TOLERANCE",
    "check_day",
    "compare",
    "event_for",
    "gspc_close",
    "kalshi_settlement",
]

MATCH_TOLERANCE = 0.005  # index points: both sides have two decimals, so equal means equal
INDEX_TICKER = "^GSPC"
CLOSE_FINAL = dt.time(16, 15)  # New York: Yahoo's daily bar is the close only after this
COLUMNS = [
    "date",
    "event",
    "kalshi_status",
    "kalshi_value",
    "gspc_close",
    "diff",
    "match",
    "checked_at",
]


def event_for(day: dt.date) -> str:
    """The 4pm "above" event that settles on ``day``: 2026-11-06 -> ``KXINXU-26NOV06H1600``."""
    return f"{kalshi.SERIES}-{day:%y}{day:%b}{day:%d}{kalshi.CLOSE_SUFFIX}".upper()


def kalshi_settlement(markets: pd.DataFrame) -> tuple[str, float]:
    """``(status, settlement value)`` from an event's ``markets_table``.

    The value is NaN until settled. Raises if the markets disagree on it (they never should).
    """
    values = markets["settle_value"].dropna().round(2).unique()
    if len(values) > 1:
        raise ValueError(f"markets of one event settled on different values: {sorted(values)}")
    statuses = sorted(set(markets["status"]))
    status = statuses[0] if len(statuses) == 1 else "/".join(statuses)
    return status, float(values[0]) if len(values) else float("nan")


def gspc_close(day: dt.date) -> float:
    """Yahoo's ``^GSPC`` daily close for ``day``, rounded to cents; NaN if not published.

    Before 4:15pm New York on ``day`` itself Yahoo's daily bar holds the live price, not the
    close, so that returns NaN too.
    """
    now = pd.Timestamp.now(tz="America/New_York")
    if day > now.date() or (day == now.date() and now.time() < CLOSE_FINAL):
        return float("nan")
    bars = yf.Ticker(INDEX_TICKER).history(start=day, end=day + dt.timedelta(days=1))
    if bars.empty:
        return float("nan")
    dates = bars.index.tz_convert("America/New_York").date if bars.index.tz else bars.index.date
    hit = bars["Close"].to_numpy()[np.asarray(dates) == day]
    return round(float(hit[0]), 2) if len(hit) else float("nan")


def compare(
    day: dt.date, event: str, status: str, value: float, close: float, checked_at=None
) -> dict:
    """One result row. ``match`` is True/False when both numbers exist, else None."""
    both = np.isfinite(value) and np.isfinite(close)
    diff = round(value - close, 2) if both else float("nan")
    return {
        "date": day.isoformat(),
        "event": event,
        "kalshi_status": status,
        "kalshi_value": value,
        "gspc_close": close,
        "diff": diff,
        "match": bool(abs(diff) < MATCH_TOLERANCE) if both else None,
        "checked_at": pd.Timestamp(checked_at or pd.Timestamp.now(tz="UTC")).isoformat(),
    }


def check_day(day: dt.date) -> dict:
    """Download both numbers for ``day`` and compare them."""
    event = event_for(day)
    now = pd.Timestamp.now(tz="UTC")
    status, value = kalshi_settlement(kalshi.markets_table(kalshi.fetch_markets(event), now))
    return compare(day, event, status, value, gspc_close(day), now)
