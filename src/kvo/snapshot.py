"""Save and load one timestamped snapshot of both markets.

Layout: ``data/snapshots/2026-11-05T120001/`` (New York time of the run) holding

- ``kalshi.parquet``: every strike of the 4pm "above" event (``kalshi.markets_table``),
- ``ranges.parquet``: every range contract for the same close (``kalshi.ranges_table``),
- ``options.parquet``: the raw SPX chain exactly as downloaded (``optdesk`` format),
- ``spx_bars.parquet``: today's 1-minute SPX bars up to the download (``options.spx_minutes``),
  so the index can be read at the options' quote clock,
- ``kalshi_at_quote.parquet``: Kalshi's bid/ask for the strikes near the index at the options'
  quote clock, from 1-minute candles (``kalshi.prices_at``): the time-matched Kalshi prices,
- ``meta.json``: both download times, the options' quote clock, the latest SPX bar, the
  Treasury curve, the Kalshi event and the option expiry.

Snapshots from before 2026-11-06 have no ``spx_bars`` (``load_snapshot`` rebuilds a one-bar
table from ``meta.json``) and no ``kalshi_at_quote`` (``scripts/fit_snapshot.py
--fetch-kalshi`` can add it while Kalshi still serves that day's candles).

Why raw data: cleaning and fitting choices may change later, and keeping the raw downloads lets
us re-run them on old days. Free option chains have no history (Yahoo is live only), so these
snapshots are the only option data this project will ever have. Each run gets its own folder,
written under a temporary name and renamed at the end, so a crash never leaves half a snapshot.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd
from optdesk.data.rates import RateCurve

__all__ = [
    "DEFAULT_ROOT",
    "Snapshot",
    "add_to_snapshot",
    "list_snapshots",
    "load_snapshot",
    "save_snapshot",
]

DEFAULT_ROOT = Path("data/snapshots")
NEW_YORK = "America/New_York"
STAMP = "%Y-%m-%dT%H%M%S"


@dataclass(frozen=True)
class Snapshot:
    kalshi: pd.DataFrame
    ranges: pd.DataFrame  # empty for a snapshot saved before range contracts were added
    options: pd.DataFrame
    curve: RateCurve
    meta: dict
    path: Path
    spx_bars: pd.DataFrame = field(default_factory=pd.DataFrame)  # time (bar start), close
    kalshi_at_quote: pd.DataFrame = field(default_factory=pd.DataFrame)  # empty if not saved


def save_snapshot(
    kalshi: pd.DataFrame,
    ranges: pd.DataFrame,
    options: pd.DataFrame,
    curve: RateCurve,
    meta: dict,
    root: Path | str = DEFAULT_ROOT,
    *,
    spx_bars: pd.DataFrame | None = None,
    kalshi_at_quote: pd.DataFrame | None = None,
) -> Path:
    """Write one snapshot folder named by the Kalshi download time (New York); return it."""
    asof = pd.Timestamp(kalshi["asof"].iloc[0]).tz_convert(NEW_YORK)
    folder = Path(root) / asof.strftime(STAMP)
    if folder.exists():
        raise FileExistsError(f"{folder} already exists")
    tmp = folder.with_name(folder.name + ".tmp")
    tmp.mkdir(parents=True)
    kalshi.to_parquet(tmp / "kalshi.parquet", index=False)
    ranges.to_parquet(tmp / "ranges.parquet", index=False)
    options.to_parquet(tmp / "options.parquet", index=False)
    if spx_bars is not None:
        spx_bars.to_parquet(tmp / "spx_bars.parquet", index=False)
    if kalshi_at_quote is not None:
        kalshi_at_quote.to_parquet(tmp / "kalshi_at_quote.parquet", index=False)
    note = {**meta, "rate_curve": curve.to_dict()}
    (tmp / "meta.json").write_text(json.dumps(note, indent=2, default=str))
    os.replace(tmp, folder)
    return folder


def load_snapshot(folder: Path | str) -> Snapshot:
    folder = Path(folder)
    meta = json.loads((folder / "meta.json").read_text())
    curve = RateCurve.from_dict(meta.pop("rate_curve"))
    return Snapshot(
        kalshi=pd.read_parquet(folder / "kalshi.parquet"),
        ranges=_optional(folder / "ranges.parquet"),
        options=pd.read_parquet(folder / "options.parquet"),
        curve=curve,
        meta=meta,
        path=folder,
        spx_bars=_bars(folder, meta),
        kalshi_at_quote=_optional(folder / "kalshi_at_quote.parquet"),
    )


def _optional(path: Path) -> pd.DataFrame:
    return pd.read_parquet(path) if path.exists() else pd.DataFrame()


def _bars(folder: Path, meta: dict) -> pd.DataFrame:
    """Saved 1-minute bars, or for older snapshots the single latest bar from ``meta.json``."""
    if (folder / "spx_bars.parquet").exists():
        return pd.read_parquet(folder / "spx_bars.parquet")
    if meta.get("spx_bar_time"):
        return pd.DataFrame(
            {"time": [pd.Timestamp(meta["spx_bar_time"])], "close": [meta["spx_bar_value"]]}
        )
    return pd.DataFrame({"time": pd.Series(dtype="datetime64[ns, UTC]"), "close": []})


def add_to_snapshot(folder: Path | str, name: str, table: pd.DataFrame) -> Path:
    """Add one missing table (e.g. ``kalshi_at_quote``) to an existing snapshot. Never
    overwrites: the raw downloads in a snapshot are kept exactly as they were taken."""
    path = Path(folder) / f"{name}.parquet"
    if path.exists():
        raise FileExistsError(f"{path} already exists")
    tmp = path.with_name(path.name + ".tmp")
    table.to_parquet(tmp, index=False)
    os.replace(tmp, path)
    return path


def list_snapshots(root: Path | str = DEFAULT_ROOT) -> list[Path]:
    """Complete snapshot folders under ``root``, oldest first."""
    root = Path(root)
    if not root.is_dir():
        return []
    return sorted(p for p in root.iterdir() if p.is_dir() and (p / "meta.json").exists())
