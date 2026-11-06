"""Check that Kalshi's settlement value equals Yahoo's ^GSPC close, day by day.

Usage, from the repo folder (after about 7pm New York, when Kalshi has settled)::

    .venv\\Scripts\\python.exe scripts\\check_settlement.py             # snapshot days + today
    .venv\\Scripts\\python.exe scripts\\check_settlement.py 2026-11-06   # one day

Results go to ``data/settlements.csv``, one row per day; a day checked again replaces its
row, except that a day already matched is not downloaded again. Days not settled yet are
printed but not saved. Exit code 1 if any day's numbers disagree.
"""

from __future__ import annotations

import argparse
import datetime as dt
import sys
from pathlib import Path

import pandas as pd
import requests

from kvo.settlement import COLUMNS, check_day
from kvo.snapshot import DEFAULT_ROOT, NEW_YORK, list_snapshots

OUT = Path("data/settlements.csv")


def _snapshot_days(root: Path) -> set[dt.date]:
    return {dt.date.fromisoformat(p.name[:10]) for p in list_snapshots(root)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("days", nargs="*", type=dt.date.fromisoformat, help="YYYY-MM-DD")
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT, help="where snapshots live")
    parser.add_argument("--out", type=Path, default=OUT, help="results file")
    args = parser.parse_args(argv)

    today = pd.Timestamp.now(tz=NEW_YORK).date()
    days = sorted(set(args.days) or (_snapshot_days(args.root) | {today}))
    days = [d for d in days if d.weekday() < 5]
    old = (
        pd.read_csv(args.out, dtype={"date": str})
        if args.out.exists()
        else pd.DataFrame(columns=COLUMNS)
    )
    done = set(old.loc[old["match"].astype(str) == "True", "date"])

    rows, bad = [], False
    for day in days:
        if day.isoformat() in done and not args.days:
            continue
        try:
            row = check_day(day)
        except requests.RequestException as err:
            print(f"{day}: Kalshi download failed ({err})")
            continue
        if row["match"] is None:
            why = "no such event" if not row["kalshi_status"] else f"status {row['kalshi_status']}"
            print(
                f"{day} {row['event']}: not settled yet ({why}; Kalshi {row['kalshi_value']}, "
                f"^GSPC {row['gspc_close']})"
            )
            continue
        verdict = "match" if row["match"] else "MISMATCH"
        print(
            f"{day} {row['event']}: Kalshi {row['kalshi_value']:.2f}, ^GSPC "
            f"{row['gspc_close']:.2f}, diff {row['diff']:+.2f}: {verdict}"
        )
        bad |= not row["match"]
        rows.append(row)

    if rows:
        new = pd.DataFrame(rows, columns=COLUMNS)
        keep = old[~old["date"].isin(new["date"])]
        table = pd.concat([keep, new], ignore_index=True) if len(keep) else new
        args.out.parent.mkdir(parents=True, exist_ok=True)
        table.sort_values("date").to_csv(args.out, index=False)
        print(f"saved {args.out}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
