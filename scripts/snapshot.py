"""Save one snapshot of both markets and print what it contains.

Usage, from the repo folder (run it while the market is open, 9:30am-4pm New York)::

    .venv\\Scripts\\python.exe scripts\\snapshot.py
    .venv\\Scripts\\python.exe scripts\\snapshot.py --root some\\other\\folder

What it does, in order:
1. Asks Kalshi for the open 4pm S&P 500 event (today's, or the next one after the close).
2. Downloads every strike of that event (public data, no account).
3. Downloads the SPX option chain for that expiry and the next, the Treasury curve, and the
   latest 1-minute SPX bar (Yahoo, via options-desk).
4. Saves all of it as one folder (``kvo.snapshot``) and prints a short quality report: how many
   Kalshi strikes have both a bid and an ask, how many SPX quotes survive cleaning, how good the
   SVI fit is, and how delayed the option data looks.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

from kvo import kalshi, options
from kvo.snapshot import DEFAULT_ROOT, save_snapshot

NEW_YORK = "America/New_York"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT, help="snapshot folder")
    args = parser.parse_args(argv)

    event = kalshi.next_close_event(kalshi.fetch_open_events())
    kalshi_asof = pd.Timestamp.now(tz="UTC")
    markets = kalshi.markets_table(kalshi.fetch_markets(event), kalshi_asof)
    expiry = pd.Timestamp(markets["close_time"].iloc[0]).tz_convert(NEW_YORK).date()

    raw, curve = options.fetch_spx()
    bar_time, bar_value = options.spx_last_minute()
    options_asof = pd.Timestamp(raw["asof"].iloc[0])

    meta = {
        "kalshi_event": event,
        "kalshi_asof": kalshi_asof.isoformat(),
        "options_ticker": options.TICKER,
        "options_expiry": f"{expiry:%Y-%m-%d}",
        "options_asof": options_asof.isoformat(),
        "spx_bar_time": None if pd.isna(bar_time) else bar_time.isoformat(),
        "spx_bar_value": bar_value,
        "sources": {"kalshi": kalshi.BASE_URL, "options": "Yahoo Finance via yfinance"},
    }
    folder = save_snapshot(markets, raw, curve, meta, args.root)
    print(f"saved {folder}")

    # --- quality report -------------------------------------------------------------------
    two_sided = markets.dropna(subset=["yes_bid", "yes_ask"])
    mid = (two_sided["yes_bid"] + two_sided["yes_ask"]) / 2
    active = two_sided[(mid > 0.05) & (mid < 0.95)]
    spread = (active["yes_ask"] - active["yes_bid"]).median()
    print(
        f"Kalshi {event}: {len(markets)} strikes, {len(two_sided)} with a bid and an ask; "
        f"median spread {spread:.2f} on the {len(active)} strikes priced 5-95 cents"
    )

    today = raw[pd.to_datetime(raw["expiry"]).dt.date == expiry]
    print(
        f"SPX {expiry}: {len(today)} quotes, {(today['bid'] > 0).sum()} with a bid; "
        f"latest trade {options.quote_age_minutes(raw, expiry):.1f} min before download"
    )
    if not pd.isna(bar_time):
        lag = (options_asof - bar_time) / pd.Timedelta(minutes=1)
        print(f"SPX index: {bar_value:.2f}, latest 1-min bar {lag:.1f} min before download")

    clean, fit = options.same_day_fit(raw, curve, expiry)
    if fit is None:
        print(f"SVI: not fitted, only {len(clean)} clean quotes (market closed?)")
    else:
        print(
            f"SVI: {int(fit['n'])} quotes, RMSE {fit['rmse'] * 100:.2f} vol points, "
            f"forward {fit['forward']:.2f}, converged {bool(fit['success'])}"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
