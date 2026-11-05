"""Same-day SPX options: download, clean and fit with options-desk's code.

Why SPX, not SPY
----------------
Kalshi settles on the S&P 500 index itself. SPX options are written on that same index,
are European (no early exercise to strip out), and the daily SPXW expiries settle on the 4pm
closing value, the same number Kalshi uses. SPY is an ETF worth about a tenth of the index,
with dividends and American exercise, so it would need a mapping step that adds error. Yahoo
serves SPX chains with daily expiries for free (checked 2026-11-04, see docs/FEASIBILITY.md),
so we don't need SPY.

Reused, not rewritten
---------------------
- ``optdesk.data.fetch.fetch_chain`` and ``fetch_rate_curve`` download the chain and the
  Treasury curve from Yahoo.
- ``optdesk.data.clean.clean_chain`` filters bad quotes and computes the forward, the
  log-moneyness and the implied vols. By default it drops same-day options (in options-desk
  they distort a multi-month surface). Here the same-day expiry is the whole point, so we pass
  ``min_days=0``.
- ``optdesk.surface.svi.fit_chain`` fits the SVI smile to that one expiry.
"""

from __future__ import annotations

import pandas as pd
import yfinance as yf
from optdesk.data.clean import clean_chain
from optdesk.data.fetch import fetch_chain, fetch_rate_curve
from optdesk.data.rates import RateCurve
from optdesk.surface.svi import fit_chain

__all__ = ["TICKER", "fetch_spx", "quote_age_minutes", "same_day_fit", "spx_last_minute"]

TICKER = "^SPX"
NEW_YORK = "America/New_York"


def fetch_spx(n_expiries: int = 2) -> tuple[pd.DataFrame, RateCurve]:
    """Raw SPX chain for the nearest ``n_expiries`` (today's first) and the Treasury curve."""
    return fetch_chain(TICKER, n_expiries), fetch_rate_curve()


def spx_last_minute() -> tuple[pd.Timestamp, float]:
    """Time and value of the latest 1-minute SPX bar on Yahoo: a check of how delayed it is."""
    bars = yf.Ticker(TICKER).history(period="1d", interval="1m")
    if bars.empty:
        return pd.NaT, float("nan")
    return bars.index[-1].tz_convert("UTC"), float(bars["Close"].iloc[-1])


def same_day_fit(
    raw: pd.DataFrame, curve: RateCurve, expiry: str | pd.Timestamp
) -> tuple[pd.DataFrame, pd.Series | None]:
    """Clean quotes and SVI fit for one expiry: ``(clean quotes, fit row)``.

    The fit row has ``T``, ``forward``, the SVI parameters, ``rmse`` and ``n``. It is None when
    fewer than 5 quotes survive cleaning (after hours, when every bid is zero).
    """
    day = pd.Timestamp(expiry).normalize()
    chain = raw[pd.to_datetime(raw["expiry"]).dt.normalize() == day]
    if chain.empty:
        return chain, None
    clean = clean_chain(chain, curve, american=False, min_days=0)
    if len(clean) < 5:
        return clean, None
    return clean, fit_chain(clean).iloc[0]


def quote_age_minutes(raw: pd.DataFrame, expiry: str | pd.Timestamp) -> float:
    """Minutes between the download and the most recent trade in that expiry.

    If the most active contracts traded seconds ago in reality but the latest trade we see is
    15 minutes old, the feed is about 15 minutes delayed. So this is an estimate of the delay
    (and an upper bound on it).
    """
    day = pd.Timestamp(expiry).normalize()
    chain = raw[pd.to_datetime(raw["expiry"]).dt.normalize() == day]
    if chain.empty or chain["last_trade"].isna().all():
        return float("nan")
    age = chain["asof"].iloc[0] - chain["last_trade"].max()
    return age / pd.Timedelta(minutes=1)
