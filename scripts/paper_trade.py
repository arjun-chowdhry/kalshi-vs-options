"""Milestone 3: paper-trade the strict and the naive rule on every saved snapshot.

Usage, from the repo folder (no network needed)::

    .venv\\Scripts\\python.exe scripts\\paper_trade.py

Reads every snapshot, builds the M2 comparison table (``kvo.compare``), lists the trades both
rules would make (``kvo.paper``), and settles them with ``data/settlements.csv`` (run
``scripts\\check_settlement.py`` after each close to fill it). Days without a known close stay
unsettled. Writes every trade to ``data/m3/trades.csv`` and the summary to
``data/m3/summary.csv``.

Read this first: the sample is a few days. Every trade on one day settles on the same close,
so the trades are not independent, and the day is the real unit of evidence. A null result
(no reliable profit either way) is the expected outcome at this sample size.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

from kvo import options, paper
from kvo.compare import comparison_table
from kvo.snapshot import DEFAULT_ROOT, list_snapshots, load_snapshot

SETTLEMENTS = Path("data/settlements.csv")
OUT = Path("data/m3")


def closes(path: Path) -> dict[str, float]:
    """Settlement values Kalshi actually paid on, by day (only days Kalshi has settled)."""
    if not path.exists():
        return {}
    s = pd.read_csv(path, dtype={"date": str}).dropna(subset=["kalshi_value"])
    return dict(zip(s["date"], s["kalshi_value"].astype(float), strict=True))


def book_for(folder: Path) -> tuple[pd.DataFrame, str]:
    snap = load_snapshot(folder)
    expiry = snap.meta["options_expiry"]
    if snap.kalshi_at_quote.empty:
        return pd.DataFrame(), "no Kalshi prices at the quote clock"
    t = options.quote_time(snap.options, expiry)
    try:
        _, index = options.index_at(snap.spx_bars, t)
    except ValueError as err:
        return pd.DataFrame(), str(err)
    day = options.same_day_fit(snap.options, snap.curve, expiry, index, t)
    if day.fit is None:
        return pd.DataFrame(), "no fit"
    table = comparison_table(day, snap.kalshi_at_quote, snap.spx_bars)
    return paper.trades(table, snap.path.name, expiry), f"{len(table)} strikes compared"


def _money(x: float) -> str:
    return "     -" if pd.isna(x) else f"{x:+.3f}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT, help="where snapshots live")
    parser.add_argument("--settlements", type=Path, default=SETTLEMENTS)
    parser.add_argument("--out", type=Path, default=OUT)
    args = parser.parse_args(argv)

    known = closes(args.settlements)
    books, snap_days = [], set()
    print("Per snapshot (one contract per trade):")
    for folder in list_snapshots(args.root):
        book, note = book_for(folder)
        books.append(book)
        day = folder.name[:10]
        snap_days.add(day)
        close = f"close {known[day]:.2f}" if day in known else "close not known yet"
        counts = book.groupby("rule").size().to_dict() if len(book) else {}
        print(
            f"  {folder.name}: {note}; strict {counts.get('strict', 0)} trades, naive "
            f"{counts.get('naive', 0)}; {close}"
        )
    filled = [b for b in books if len(b)]
    book = (
        pd.concat(filled, ignore_index=True)
        if filled
        else pd.DataFrame(columns=paper.TRADE_COLUMNS)
    )
    settled = paper.settle(book, known)
    summary = paper.summarise(settled)

    args.out.mkdir(parents=True, exist_ok=True)
    settled.to_csv(args.out / "trades.csv", index=False)
    summary.to_csv(args.out / "summary.csv", index=False)

    print("\nSummary (P&L in dollars per $1 contract, after fees):")
    print(
        "  rule                          trades (yes/no)  settled  days  wins  total P&L  "
        "mean P&L  SE (iid)  SE (by day)  expected"
    )
    for _, r in summary.iterrows():
        count = f"{r['n_trades']} ({r['n_yes']}/{r['n_no']})"
        print(
            f"  {r['rule']:<29} {count:>15}  {r['n_settled']:7d}  "
            f"{r['settled_days']:4d}  {r['wins']:4d}  "
            f"{_money(r['pnl_total']):>9}  {_money(r['pnl_mean']):>8}  "
            f"{_money(r['se_iid']):>8}  {_money(r['se_day']):>11}  {_money(r['edge_mean']):>8}"
        )
    days = sorted(settled.loc[settled["pnl"].notna(), "day"].unique())
    pending = sorted(snap_days - set(known))
    print(
        f"\n  Days with settled trades: {', '.join(days) or 'none'}. Snapshot days not settled "
        f"yet: "
        f"{', '.join(pending) or 'none'}.\n"
        "  SE (by day) needs at least 2 settled days; with fewer it is blank, because one day's "
        "trades all\n  ride on one close and are not independent. SE (iid) ignores that and is "
        "too small.\n"
        "  This is a few days of data. A null result is the expected outcome; nothing here is "
        "evidence of an edge."
    )
    print(f"\nsaved {args.out / 'trades.csv'} and {args.out / 'summary.csv'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
