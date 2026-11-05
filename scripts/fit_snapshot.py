"""Re-clean and re-fit a saved snapshot and print the same report as ``snapshot.py``.

Usage, from the repo folder::

    .venv\\Scripts\\python.exe scripts\\fit_snapshot.py                       # latest snapshot
    .venv\\Scripts\\python.exe scripts\\fit_snapshot.py data\\snapshots\\2026-11-05T142350
    .venv\\Scripts\\python.exe scripts\\fit_snapshot.py --fetch-kalshi        # add Kalshi prices

Needs no network unless ``--fetch-kalshi`` is given. That flag is for snapshots saved before
Kalshi prices at the options' quote clock were recorded: it downloads Kalshi's 1-minute candles
for that minute (public, read-only GET requests) and adds them to the snapshot folder as
``kalshi_at_quote.parquet``. It never overwrites a file already in the snapshot.
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import replace
from pathlib import Path

from kvo import kalshi, options
from kvo.report import kalshi_strikes_near, same_day_report
from kvo.snapshot import DEFAULT_ROOT, add_to_snapshot, list_snapshots, load_snapshot


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("folder", type=Path, nargs="?", help="snapshot folder (default: latest)")
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT, help="where snapshots live")
    parser.add_argument(
        "--fetch-kalshi",
        action="store_true",
        help="download Kalshi prices at the quote clock if the snapshot lacks them",
    )
    args = parser.parse_args(argv)

    folder = args.folder
    if folder is None:
        found = list_snapshots(args.root)
        if not found:
            print(f"no snapshots under {args.root}")
            return 1
        folder = found[-1]
    snap = load_snapshot(folder)
    expiry = snap.meta["options_expiry"]
    print(f"snapshot {snap.path}")

    if args.fetch_kalshi and snap.kalshi_at_quote.empty:
        t_quote = options.quote_time(snap.options, expiry)
        _, index = options.index_at(snap.spx_bars, t_quote)
        prices = kalshi.prices_at(kalshi_strikes_near(snap.kalshi, index), t_quote)
        print(f"added {add_to_snapshot(snap.path, 'kalshi_at_quote', prices)}")
        snap = replace(snap, kalshi_at_quote=prices)

    bars, quotes = snap.spx_bars, snap.kalshi_at_quote
    _, lines = same_day_report(snap.options, snap.curve, expiry, bars, quotes)
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    sys.exit(main())
