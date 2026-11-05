"""Save and load one timestamped snapshot of both markets.

Layout: ``data/snapshots/2026-11-05T120001/`` (New York time of the run) holding

- ``kalshi.parquet``: every strike of the 4pm event (``kalshi.markets_table``),
- ``options.parquet``: the raw SPX chain exactly as downloaded (``optdesk`` format),
- ``meta.json``: both download times, the SPX level and its time, the Treasury curve, the
  Kalshi event and the option expiry.

Why raw data: cleaning and fitting choices may change later, and keeping the raw downloads lets
us re-run them on old days. Free option chains have no history (Yahoo is live only), so these
snapshots are the only option data this project will ever have. Each run gets its own folder,
written under a temporary name and renamed at the end, so a crash never leaves half a snapshot.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

import pandas as pd
from optdesk.data.rates import RateCurve

__all__ = ["DEFAULT_ROOT", "Snapshot", "list_snapshots", "load_snapshot", "save_snapshot"]

DEFAULT_ROOT = Path("data/snapshots")
NEW_YORK = "America/New_York"
STAMP = "%Y-%m-%dT%H%M%S"


@dataclass(frozen=True)
class Snapshot:
    kalshi: pd.DataFrame
    options: pd.DataFrame
    curve: RateCurve
    meta: dict
    path: Path


def save_snapshot(
    kalshi: pd.DataFrame,
    options: pd.DataFrame,
    curve: RateCurve,
    meta: dict,
    root: Path | str = DEFAULT_ROOT,
) -> Path:
    """Write one snapshot folder named by the Kalshi download time (New York); return it."""
    asof = pd.Timestamp(kalshi["asof"].iloc[0]).tz_convert(NEW_YORK)
    folder = Path(root) / asof.strftime(STAMP)
    if folder.exists():
        raise FileExistsError(f"{folder} already exists")
    tmp = folder.with_name(folder.name + ".tmp")
    tmp.mkdir(parents=True)
    kalshi.to_parquet(tmp / "kalshi.parquet", index=False)
    options.to_parquet(tmp / "options.parquet", index=False)
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
        options=pd.read_parquet(folder / "options.parquet"),
        curve=curve,
        meta=meta,
        path=folder,
    )


def list_snapshots(root: Path | str = DEFAULT_ROOT) -> list[Path]:
    """Complete snapshot folders under ``root``, oldest first."""
    root = Path(root)
    if not root.is_dir():
        return []
    return sorted(p for p in root.iterdir() if p.is_dir() and (p / "meta.json").exists())
