"""Kalshi against the options fit: a sanity check that runs only after the fit is done.

Nothing in this module feeds back into the options side. The options fit (``kvo.options``) is
cleaned, windowed and fitted from option quotes and the index alone; Kalshi prices are never
used to choose quotes, forwards or parameters, so a later comparison of the two markets is not
circular. Here we only line the two up and report the difference.

Timing: Yahoo's option quotes are about 15 minutes delayed, Kalshi's API is live. So Kalshi
is taken at the options' quote clock, from its 1-minute candles (``kalshi.prices_at``), not
from the live book saved at download time.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from kvo.options import SameDay, prob_above

__all__ = ["kalshi_check"]


def kalshi_check(day: SameDay, kalshi_quotes: pd.DataFrame, lo: float = 0.03) -> pd.DataFrame:
    """Per strike: Kalshi's bid/ask for "close at or above K" and the options' probability.

    ``kalshi_quotes`` has ``strike``, ``yes_bid``, ``yes_ask`` (e.g. ``kalshi.prices_at`` at
    ``day.quote_time``). Keeps strikes with both sides quoted and a mid between ``lo`` and
    ``1 - lo``. Adds ``kalshi_mid``, ``p_options``, ``diff`` (options minus Kalshi mid) and
    ``outside`` (options probability outside Kalshi's bid-ask).
    """
    k = kalshi_quotes.dropna(subset=["yes_bid", "yes_ask"]).copy()
    k["kalshi_mid"] = (k["yes_bid"] + k["yes_ask"]) / 2
    k = k[(k["kalshi_mid"] > lo) & (k["kalshi_mid"] < 1 - lo)].sort_values("strike")
    if day.fit is None or k.empty:
        return k.assign(p_options=np.nan, diff=np.nan, outside=False)
    k["p_options"] = prob_above(day.fit, k["strike"].to_numpy(), day.r)
    k["diff"] = k["p_options"] - k["kalshi_mid"]
    k["outside"] = (k["p_options"] < k["yes_bid"]) | (k["p_options"] > k["yes_ask"])
    return k.reset_index(drop=True)
