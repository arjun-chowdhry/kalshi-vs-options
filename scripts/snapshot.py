"""Save one snapshot of both markets and print what it contains.

Usage, from the repo folder (run it while the market is open, 9:30am-4pm New York)::

    .venv\\Scripts\\python.exe scripts\\snapshot.py
    .venv\\Scripts\\python.exe scripts\\snapshot.py --root some\\other\\folder

What it does, in order:
1. Asks Kalshi for the open 4pm S&P 500 event (today's, or the next one after the close).
2. Downloads every strike of that event and every range contract (``KXINX``) for the same
   close: 3 public read-only requests, no account.
3. Downloads the SPX option chain for that expiry and the next, the Treasury curve, and
   today's 1-minute SPX bars (Yahoo, via options-desk).
4. Finds the options' quote clock (their latest trade, about 15 minutes ago) and looks up
   Kalshi's bid and ask at that minute for the strikes within 150 points of the index (one
   1-minute candle request each, about 60 requests at 5 per second: roughly 15 seconds).
5. Saves all of it as one folder (``kvo.snapshot``) and prints a quality report: Kalshi's book,
   the options' clock and staleness, what the cleaning dropped, the SVI fit, the largest
   strike gap near the money, then (separately, after the fit) the Kalshi comparison.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd
import requests

from kvo import kalshi, options
from kvo.report import kalshi_strikes_near, same_day_report
from kvo.snapshot import DEFAULT_ROOT, save_snapshot

NEW_YORK = "America/New_York"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT, help="snapshot folder")
    args = parser.parse_args(argv)

    event = kalshi.next_close_event(kalshi.fetch_open_events())
    kalshi_asof = pd.Timestamp.now(tz="UTC")
    markets = kalshi.markets_table(kalshi.fetch_markets(event), kalshi_asof)
    ranges_event = kalshi.range_event(event)
    ranges = kalshi.ranges_table(kalshi.fetch_markets(ranges_event), kalshi_asof)
    expiry = pd.Timestamp(markets["close_time"].iloc[0]).tz_convert(NEW_YORK).date()

    raw, curve = options.fetch_spx()
    bars = options.spx_minutes()
    options_asof = pd.Timestamp(raw["asof"].iloc[0])
    t_quote = options.quote_time(raw, expiry)

    # Kalshi at the options' quote clock (Kalshi is live, the options are ~15 minutes old).
    kalshi_at_quote = None
    if not pd.isna(t_quote) and not bars.empty:
        try:
            _, index = options.index_at(bars, t_quote)
            kalshi_at_quote = kalshi.prices_at(kalshi_strikes_near(markets, index), t_quote)
        except ValueError as err:
            print(f"Kalshi at the quote clock: skipped ({err})")
        except requests.RequestException as err:
            print(f"Kalshi at the quote clock: download failed ({err}); continuing without it")

    last_bar = bars.iloc[-1] if not bars.empty else None
    meta = {
        "kalshi_event": event,
        "kalshi_range_event": ranges_event,
        "kalshi_asof": kalshi_asof.isoformat(),
        "options_ticker": options.TICKER,
        "options_expiry": f"{expiry:%Y-%m-%d}",
        "options_asof": options_asof.isoformat(),
        "options_quote_time": None if pd.isna(t_quote) else t_quote.isoformat(),
        "spx_bar_time": None if last_bar is None else pd.Timestamp(last_bar["time"]).isoformat(),
        "spx_bar_value": None if last_bar is None else float(last_bar["close"]),
        "sources": {"kalshi": kalshi.BASE_URL, "options": "Yahoo Finance via yfinance"},
    }
    folder = save_snapshot(
        markets, ranges, raw, curve, meta, args.root, spx_bars=bars, kalshi_at_quote=kalshi_at_quote
    )
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
    quoted = ranges.dropna(subset=["yes_bid", "yes_ask"])
    print(
        f"Kalshi {ranges_event}: {len(ranges)} range contracts, {len(quoted)} with a bid and "
        f"an ask (the sum-to-100% check comes in Milestone 2)"
    )
    _, lines = same_day_report(raw, curve, expiry, bars, kalshi_at_quote)
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    sys.exit(main())
