"""M2 comparison: options against Kalshi, strike by strike, with the resolution limit applied.

Usage, from the repo folder (no network needed)::

    .venv\\Scripts\\python.exe scripts\\compare_snapshots.py            # every saved snapshot
    .venv\\Scripts\\python.exe scripts\\compare_snapshots.py data\\snapshots\\2026-11-06T112037

For each snapshot it prints the per-strike table and writes it to
``data/m2/<snapshot>.csv``. Then one line per snapshot on the one-sided offset and the index's
move before the quote clock, merged into ``data/m2/offsets.csv`` (one row per snapshot).

Ground rules (README): Kalshi is never an input to the fit. A strike labelled "no usable
option quotes" or "beyond the fitted quotes" is never assessed. And the one-sided offset is
not a finding until it has been checked on at least ``OFFSET_MIN_DAYS`` trading days.
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import asdict
from pathlib import Path

import numpy as np
import pandas as pd

from kvo import options
from kvo.compare import NO_QUOTES, comparison_table, offset_summary
from kvo.snapshot import DEFAULT_ROOT, list_snapshots, load_snapshot

OUT = Path("data/m2")
OFFSET_MIN_DAYS = 5  # trading days before the offset can be called anything but an observation
MIN_SHIFT = 1.0  # index points: a smaller shift is not given a direction


def _pts(x: float) -> str:
    return "   -" if not np.isfinite(x) else f"{x * 100:+5.1f}"


def one(folder: Path, out: Path) -> dict | None:
    snap = load_snapshot(folder)
    expiry = snap.meta["options_expiry"]
    print(f"\n=== {snap.path.name} ===")
    if snap.kalshi_at_quote.empty:
        print("no Kalshi prices at the quote clock saved; skipped")
        return None
    t = options.quote_time(snap.options, expiry)
    try:
        _, index = options.index_at(snap.spx_bars, t)
    except ValueError as err:
        print(f"skipped: {err}")
        return None
    day = options.same_day_fit(snap.options, snap.curve, expiry, index, t)
    if day.fit is None:
        print("no fit (too few clean quotes); skipped")
        return None
    table = comparison_table(day, snap.kalshi_at_quote, snap.spx_bars)
    out.mkdir(parents=True, exist_ok=True)
    table.to_csv(out / f"{snap.path.name}.csv", index=False)

    print(
        f"quote clock {t.tz_convert('America/New_York'):%H:%M:%S} ET, index {index:.2f}; "
        f"forward error {table.attrs['forward_error']:.2f} points "
        f"({table.attrs['forward_error_source']})"
    )
    print("  strike  bid/ask     options   diff  sigma  cost  limit  status   (points)")
    for _, r in table.iterrows():
        print(
            f"  {r['strike']:6.0f}  {r['yes_bid']:.2f}/{r['yes_ask']:.2f}  {r['p_options']:.3f}  "
            f"{_pts(r['diff'])}  {r['sigma'] * 100:5.1f} {r['cost'] * 100:5.1f}  "
            f"{r['limit'] * 100:5.1f}  {r['status']}"
        )
    counts = table["status"].value_counts()
    print("  " + "; ".join(f"{n} {s}" for s, n in counts.items()))
    over = table[table["status"] == "beyond limit"]
    if len(over):
        print(f"  beyond the limit at: {', '.join(f'{k:.0f}' for k in over['strike'])}")
    if counts.get(NO_QUOTES, 0):
        print(f"  {NO_QUOTES}: inside the no-quote gap, not assessed")

    off = offset_summary(day, table, snap.spx_bars, snap.kalshi_at_quote)
    return {
        "snapshot": snap.path.name,
        "day": snap.path.name[:10],
        "quote_clock_et": f"{t.tz_convert('America/New_York'):%H:%M:%S}",
        **asdict(off),
        "side": off.side,
        "beyond_limit": int(len(over)),
    }


def timing_note(r: pd.Series) -> str:
    """Which way the shift points relative to the index's recent move."""
    if not np.isfinite(r["move_15m"]):
        return "no 15-min bars"
    if not np.isfinite(r["shift"]) or abs(r["shift"]) < MIN_SHIFT:
        return "no shift"
    return (
        "Kalshi further along the move"
        if np.sign(r["shift"]) == np.sign(r["move_15m"])
        else ("Kalshi behind the move")
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("folders", type=Path, nargs="*", help="snapshot folders (default: all)")
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT, help="where snapshots live")
    parser.add_argument("--out", type=Path, default=OUT, help="where to write the tables")
    args = parser.parse_args(argv)

    folders = args.folders or list_snapshots(args.root)
    rows = [r for f in folders if (r := one(f, args.out)) is not None]
    if not rows:
        return 1
    offs = pd.DataFrame(rows)
    offs["timing"] = offs.apply(timing_note, axis=1)
    path = args.out / "offsets.csv"
    if path.exists():  # keep rows of snapshots not run this time
        old = pd.read_csv(path, dtype={"snapshot": str, "day": str})
        old = old[~old["snapshot"].isin(offs["snapshot"])]
        if len(old):
            offs = pd.concat([old, offs], ignore_index=True)
    offs = offs.sort_values("snapshot").reset_index(drop=True)
    offs.to_csv(path, index=False)

    print("\n=== One-sided offset and the index's move (assessed strikes only) ===")
    print(
        "  snapshot           clock ET  n  >ask <bid  mean diff  shift  parity-idx  "
        "move 15m / 5m  Kalshi lag  side / timing"
    )
    for _, r in offs.iterrows():
        print(
            f"  {r['snapshot']}  {r['quote_clock_et']}  {r['n']:2d}  {r['above_ask']:3d}  "
            f"{r['below_bid']:3d}   {_pts(r['mean_diff'])}   {r['shift']:+5.1f}  "
            f"{r['parity_minus_index']:+8.2f}   {r['move_15m']:+6.1f} / {r['move_5m']:+5.1f}  "
            f"{r['kalshi_lag_s']:6.0f} s   {r['side']}; {r['timing']}"
        )
    days = offs["day"].nunique()
    print(
        f"\n  shift: index points the options' forward would move to best match Kalshi's mids "
        f"(negative: Kalshi prices the index lower).\n"
        f"  {len(offs)} snapshots on {days} trading days. The offset is an observation, not a "
        f"finding, until it has been checked on at least {OFFSET_MIN_DAYS} trading days "
        f"({max(OFFSET_MIN_DAYS - days, 0)} to go)."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
