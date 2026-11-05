"""Read-only access to Kalshi's public market data for the same-day S&P 500 contracts.

Safety: this module only ever sends HTTP GET requests to the public market-data endpoints.
There is no login, no account, no key, and no function that could place or cancel an order.
``tests/test_safety.py`` scans the source code and fails if that ever changes.

Which contracts
---------------
Kalshi's series ``KXINXU`` ("S&P 500 above/below") lists, for every trading day, one event per
hour from 10am to 4pm New York time. We use only the 4pm event (e.g. ``KXINXU-26NOV05H1600``),
because it settles on the end-of-day S&P 500 value, the same number SPX options settle on.
Each event has 60-80 markets, one per strike, 5 index points apart. A market such as
``KXINXU-26NOV05H1600-T7744.9999`` pays $1 if the index closes above 7744.9999, i.e. at or
above 7745.00 (the index has two decimals). Kalshi reports that level as ``floor_strike``.

Prices come as strings in dollars (``"0.2300"``). A bid of 0 means nobody is bidding, and an
ask of 0 or 1 means nobody is offering. We store both as missing (NaN), not as real prices.

Range contracts
---------------
The sister series ``KXINX`` ("S&P 500 range") splits the same 4pm close into 30 contracts:
28 buckets 25 points wide ("7,675 to 7,699.9999"), plus one tail below the lowest bucket and
one above the highest. Exactly one of them pays $1, so their prices are separate, independent
estimates of probabilities that should add up to about 100%. That makes them a consistency
check that the "above" contracts can't give (see the M2 checks). We store each one as a
half-open band ``lower <= close < upper``, with ``-inf`` / ``inf`` for the tails.

Rate limits: Kalshi's basic tier allows about 20 requests per second. A snapshot makes 3
requests (open events, "above" markets, range markets). Every request also waits until at
least ``MIN_INTERVAL`` seconds have passed since the previous one, so even page loops or
candle downloads stay at 5 requests per second or fewer.
"""

from __future__ import annotations

import math
import time

import numpy as np
import pandas as pd
import requests

__all__ = [
    "BASE_URL",
    "RANGE_SERIES",
    "SERIES",
    "candle_at",
    "candles_table",
    "fetch_candles",
    "fetch_markets",
    "fetch_open_events",
    "markets_table",
    "next_close_event",
    "range_event",
    "prices_at",
    "ranges_table",
]

BASE_URL = "https://api.elections.kalshi.com/trade-api/v2"
SERIES = "KXINXU"
RANGE_SERIES = "KXINX"
CLOSE_SUFFIX = "H1600"  # the 4pm New York event
TIMEOUT = 30  # seconds
MIN_INTERVAL = 0.2  # seconds between requests: at most 5 per second, a quarter of the limit

_COMMON_COLUMNS = [
    "yes_bid",
    "yes_ask",
    "yes_bid_size",
    "yes_ask_size",
    "last",
    "volume",
    "open_interest",
    "status",
    "result",  # "yes" / "no" once settled, else ""
    "settle_value",  # the S&P 500 value Kalshi settled on, NaN before settlement
    "close_time",
]
_ID_COLUMNS = ["asof", "event", "ticker"]  # asof: when we downloaded the market (UTC)
# "above" contracts: YES pays if the S&P 500 closes at or above ``strike``
MARKET_COLUMNS = [*_ID_COLUMNS, "strike", *_COMMON_COLUMNS]
# range contracts: YES pays if ``lower <= close < upper``
RANGE_COLUMNS = [*_ID_COLUMNS, "lower", "upper", *_COMMON_COLUMNS]

_last_request = 0.0


def _get(path: str, params: dict | None = None) -> dict:
    """One GET request to the public API, spaced ``MIN_INTERVAL`` apart; raises on HTTP errors."""
    global _last_request
    wait = _last_request + MIN_INTERVAL - time.monotonic()
    if wait > 0:
        time.sleep(wait)
    _last_request = time.monotonic()
    response = requests.get(BASE_URL + path, params=params, timeout=TIMEOUT)
    response.raise_for_status()
    return response.json()


def fetch_open_events(series: str = SERIES) -> list[dict]:
    """Every event of ``series`` that is still open for trading."""
    return _get("/events", {"series_ticker": series, "status": "open", "limit": 200})["events"]


def next_close_event(events: list[dict]) -> str:
    """The earliest 4pm event among ``events`` (today's if the market is open, else the next)."""
    close = [e for e in events if e["event_ticker"].endswith(CLOSE_SUFFIX)]
    if not close:
        raise ValueError("no open 4pm S&P 500 event on Kalshi (weekend or holiday?)")
    return min(close, key=lambda e: e["strike_date"])["event_ticker"]


def fetch_markets(event: str) -> list[dict]:
    """Every market (strike) of one event, following Kalshi's page cursor."""
    markets, cursor = [], None
    while True:
        params = {"event_ticker": event, "limit": 200}
        if cursor:
            params["cursor"] = cursor
        page = _get("/markets", params)
        markets.extend(page["markets"])
        cursor = page.get("cursor")
        if not cursor:
            return markets


def _price(value, *, ask: bool = False) -> float:
    """Dollar string -> float; an empty side of the book becomes NaN."""
    if value in (None, ""):
        return float("nan")
    p = float(value)
    empty = p <= 0 or (ask and p >= 1)
    return float("nan") if empty else p


def range_event(event: str) -> str:
    """The range event for the same close: ``KXINXU-26NOV05H1600`` -> ``KXINX-26NOV05H1600``."""
    series, _, rest = event.partition("-")
    if series != SERIES or not rest:
        raise ValueError(f"not a {SERIES} event: {event!r}")
    return f"{RANGE_SERIES}-{rest}"


def _level(value) -> float:
    """A Kalshi boundary on the index's 2-decimal grid: 7744.9999 means 7745.00."""
    return round(float(value), 2)


def _row(m: dict, asof: pd.Timestamp) -> dict:
    """Fields every market has, whatever its strike structure."""
    settle = m.get("expiration_value") or ""
    return {
        "asof": pd.Timestamp(asof),
        "event": m["event_ticker"],
        "ticker": m["ticker"],
        "yes_bid": _price(m.get("yes_bid_dollars")),
        "yes_ask": _price(m.get("yes_ask_dollars"), ask=True),
        "yes_bid_size": float(m.get("yes_bid_size_fp") or 0),
        "yes_ask_size": float(m.get("yes_ask_size_fp") or 0),
        "last": _price(m.get("last_price_dollars")),
        "volume": float(m.get("volume_fp") or 0),
        "open_interest": float(m.get("open_interest_fp") or 0),
        "status": m.get("status", ""),
        "result": m.get("result", ""),
        "settle_value": float(settle) if settle else float("nan"),
        "close_time": pd.Timestamp(m["close_time"]),
    }


def markets_table(markets: list[dict], asof: pd.Timestamp) -> pd.DataFrame:
    """ "Above" contracts (``KXINXU``) as one tidy row per strike, sorted by strike."""
    rows = [{**_row(m, asof), "strike": _level(m["floor_strike"])} for m in markets]
    table = pd.DataFrame(rows, columns=MARKET_COLUMNS)
    return table.sort_values("strike").reset_index(drop=True)


def _bounds(m: dict) -> tuple[float, float]:
    """``(lower, upper)`` of a range contract, so that YES pays if ``lower <= close < upper``.

    Kalshi writes the three kinds as: "less" (cap 7175 = below 7175), "between" (floor 7175,
    cap 7199.9999 = 7175.00 to 7199.99) and "greater" (floor 7874.9999 = 7875.00 or above).
    On the 2-decimal grid, 7199.9999 rounds to 7200.00, the next bucket's lower bound.
    """
    kind = m["strike_type"]
    if kind == "less":
        return -math.inf, _level(m["cap_strike"])
    if kind == "between":
        return _level(m["floor_strike"]), _level(m["cap_strike"])
    if kind == "greater":
        return _level(m["floor_strike"]), math.inf
    raise ValueError(f"unknown strike_type {kind!r} for {m['ticker']}")


def ranges_table(markets: list[dict], asof: pd.Timestamp) -> pd.DataFrame:
    """Range contracts (``KXINX``) as one row per band ``[lower, upper)``, sorted by band."""
    rows = []
    for m in markets:
        lower, upper = _bounds(m)
        rows.append({**_row(m, asof), "lower": lower, "upper": upper})
    table = pd.DataFrame(rows, columns=RANGE_COLUMNS)
    return table.sort_values(["lower", "upper"]).reset_index(drop=True)


def fetch_candles(
    ticker: str, start: pd.Timestamp, end: pd.Timestamp, minutes: int = 1
) -> list[dict]:
    """Bid/ask candlesticks of one market between ``start`` and ``end`` (1, 60 or 1440 minutes).

    These are public for recent markets, so we can look up the Kalshi price at the exact minute
    the (delayed) option quotes are from. Markets settled before Kalshi's archive cutoff live
    under ``/historical`` instead; we don't need those yet.
    """
    params = {
        "start_ts": int(pd.Timestamp(start).timestamp()),
        "end_ts": int(pd.Timestamp(end).timestamp()),
        "period_interval": minutes,
    }
    return _get(f"/series/{SERIES}/markets/{ticker}/candlesticks", params)["candlesticks"]


def candles_table(candles: list[dict]) -> pd.DataFrame:
    """Candlestick JSON -> ``time`` (end of the minute, UTC), closing ``yes_bid`` / ``yes_ask``."""
    rows = [
        {
            "time": pd.Timestamp(c["end_period_ts"], unit="s", tz="UTC"),
            "yes_bid": _price(c["yes_bid"].get("close_dollars")),
            "yes_ask": _price(c["yes_ask"].get("close_dollars"), ask=True),
            "volume": float(c.get("volume_fp") or 0),
        }
        for c in candles
    ]
    return pd.DataFrame(rows, columns=["time", "yes_bid", "yes_ask", "volume"])


def candle_at(candles: pd.DataFrame, t: pd.Timestamp) -> pd.Series | None:
    """The 1-minute candle covering ``t`` (the first one ending at or after it), else None.

    Its closing bid and ask are the book at the end of that minute, matching the close of the
    1-minute SPX bar that starts the same minute (``kvo.options.index_at``).
    """
    after = candles[candles["time"] >= t]
    if after.empty or after["time"].iloc[0] - t > pd.Timedelta(minutes=1):
        return None
    return after.iloc[0]


def prices_at(markets: pd.DataFrame, t: pd.Timestamp) -> pd.DataFrame:
    """Kalshi's bid and ask for each market at minute ``t``, from 1-minute candles.

    ``markets`` needs ``ticker`` and ``strike`` (a slice of ``markets_table``). One request per
    market, so pass only the strikes you need. Used to line Kalshi up with the delayed option
    quotes: Kalshi's live book at download time is about 15 minutes newer than the options.
    """
    rows = []
    for ticker, strike in zip(markets["ticker"], markets["strike"], strict=True):
        table = candles_table(
            fetch_candles(ticker, t - pd.Timedelta(minutes=2), t + pd.Timedelta(minutes=2))
        )
        c = candle_at(table, t)
        rows.append(
            {
                "ticker": ticker,
                "strike": strike,
                "time": c["time"] if c is not None else pd.NaT,
                "yes_bid": c["yes_bid"] if c is not None else np.nan,
                "yes_ask": c["yes_ask"] if c is not None else np.nan,
            }
        )
    return pd.DataFrame(rows, columns=["ticker", "strike", "time", "yes_bid", "yes_ask"])
