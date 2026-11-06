"""Kalshi against the options fit: a comparison that runs only after the fit is done.

Nothing in this module feeds back into the options side. The options fit (``kvo.options``) is
cleaned, windowed and fitted from option quotes and the index alone; Kalshi prices are never
used to choose quotes, forwards or parameters, so a later comparison of the two markets is not
circular. Here we only line the two up and report the difference.

Timing: Yahoo's option quotes are about 15 minutes delayed, Kalshi's API is live. So Kalshi
is taken at the options' quote clock, from its 1-minute candles (``kalshi.prices_at``), not
from the live book saved at download time.

M2 adds, per strike (``comparison_table``):

- the options' own uncertainty: a jackknife over leave-one-out refits (fit error) combined
  with the effect of a forward error (``forward_error``);
- Kalshi's cost of acting: half the spread plus the taker fee;
- the resolution limit ``cost + 2 sigma``, and a status. Strikes with no option quote of
  their own (inside a gap between fitted strikes, or beyond the fitted range) are labelled and
  never assessed: there the probability is the fit's shape, not a measurement.

And per snapshot (``offset_summary``): whether the disagreement is one-sided, how many index
points it amounts to, and the index's move before the quote clock, to see whether timing
explains it. That summary is descriptive: one snapshot or one day decides nothing.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
from optdesk.surface.svi import fit_chain

from kvo import options
from kvo.fees import fee_per_contract
from kvo.options import SameDay, prob_above

__all__ = [
    "BEYOND",
    "GRID",
    "NO_QUOTES",
    "Offset",
    "comparison_table",
    "forward_error",
    "index_move",
    "kalshi_check",
    "no_quote_intervals",
    "offset_summary",
    "options_uncertainty",
]

GRID = 5.0  # SPX and Kalshi strike spacing near the money, index points
NO_QUOTES = "no usable option quotes"
BEYOND = "beyond the fitted quotes"
WITHIN = "within limit"
OVER = "beyond limit"
# Forward error when parity gives no forward: the 2026-11-05 parity gaps were 3.9 and 5.3.
NO_PARITY_FORWARD_ERROR = 5.0


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


# --- M2: the comparison table, strike by strike ---------------------------------------------


def no_quote_intervals(day: SameDay) -> list[tuple[float, float]]:
    """Open intervals ``(lo, hi)`` between neighbouring fitted strikes more than ``GRID``
    apart: every place where a Kalshi strike would have no option quote at its own strike.

    Wider than the report's single "largest gap near the money" on purpose: the README's rule
    is that a probability not backed by quotes is never a finding, wherever it is.
    """
    K = np.unique(day.used["strike"].to_numpy())
    return [(float(a), float(b)) for a, b in zip(K[:-1], K[1:], strict=True) if b - a > GRID + 1e-9]


def _shifted(fit: pd.Series, d: float) -> pd.Series:
    """The same smile around a forward ``d`` points higher (SVI is in log-moneyness)."""
    out = fit.copy()
    out["forward"] = float(fit["forward"]) + d
    return out


def forward_error(day: SameDay, bars: pd.DataFrame) -> tuple[float, str]:
    """How far the forward could be off, in index points, and where that number came from.

    The larger of: the parity forward's distance from the index (``NO_PARITY_FORWARD_ERROR``
    when parity gives none), and the median 1-minute index move over the 30 minutes before the
    quote clock (the index we use is a 1-minute bar close, and the quote clock falls somewhere
    inside that minute). Snapshots saved before the 1-minute bars were kept have only parity.
    """
    fp, n = options.parity_check(day)
    if n:
        parts = [(abs(fp - day.forward), f"parity {fp - day.forward:+.2f} ({n} pairs)")]
    else:
        parts = [(NO_PARITY_FORWARD_ERROR, "no parity forward, default")]
    t = day.quote_time
    recent = bars[(bars["time"] <= t) & (bars["time"] >= t - pd.Timedelta(minutes=30))]
    if len(recent) >= 5:
        step = float(recent["close"].diff().abs().median())
        parts.append((step, f"median 1-min index move {step:.2f}"))
    return max(parts, key=lambda x: x[0])


def options_uncertainty(
    day: SameDay, strikes, forward_err: float
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """``(fit_se, forward_se, sigma)`` of the options probability at each strike, as
    probabilities (0.01 = 1 point).

    ``fit_se``: jackknife standard error over leave-one-out refits, each dropping one fitted
    quote: ``sqrt((n-1)/n * sum (p_i - p_mean)^2)``. It is large next to a gap, where a single
    quote holds the curve up. ``forward_se``: the larger probability change from moving the
    forward ``forward_err`` points either way. ``sigma`` adds the two in quadrature.
    """
    K = np.asarray(strikes, dtype=float)
    used = day.used.reset_index(drop=True)
    loo = []
    for i in range(len(used)):
        fit = fit_chain(used.drop(index=i)).iloc[0]
        if bool(fit["success"]):
            loo.append(prob_above(fit, K, day.r))
    if len(loo) > 1:
        loo = np.array(loo)
        n = len(loo)
        fit_se = np.sqrt((n - 1) / n * ((loo - loo.mean(axis=0)) ** 2).sum(axis=0))
    else:
        fit_se = np.full(K.shape, np.nan)
    p0 = prob_above(day.fit, K, day.r)
    fwd = np.maximum(
        np.abs(prob_above(_shifted(day.fit, forward_err), K, day.r) - p0),
        np.abs(prob_above(_shifted(day.fit, -forward_err), K, day.r) - p0),
    )
    return fit_se, fwd, np.sqrt(fit_se**2 + fwd**2)


def comparison_table(day: SameDay, kalshi_quotes: pd.DataFrame, bars: pd.DataFrame) -> pd.DataFrame:
    """``kalshi_check`` plus, per strike, the options' uncertainty, Kalshi's cost, the
    resolution limit and a ``status``.

    - ``cost``: half Kalshi's spread plus the exact taker fee at the price you would pay (the
      ask to buy YES when the options are above the mid, else the bid, i.e. selling YES / buying
      NO; the fee formula is symmetric). Exact, not rounded to a cent: over an order of many
      contracts the rounding is rebated.
    - ``limit = cost + 2 * sigma``: the smallest gap the free data can credibly detect there.
    - ``status``: ``NO_QUOTES`` (strictly inside a ``no_quote_intervals`` interval) and
      ``BEYOND`` (outside the fitted strikes) are never assessed; otherwise ``"beyond limit"``
      when ``|diff| > limit``, else ``"within limit"``.

    ``table.attrs`` keeps the forward error used and where it came from.
    """
    table = kalshi_check(day, kalshi_quotes)
    if day.fit is None or table.empty:
        return table
    d, why = forward_error(day, bars)
    K = table["strike"].to_numpy()
    fit_se, fwd_se, sigma = options_uncertainty(day, K, d)
    half = (table["yes_ask"] - table["yes_bid"]) / 2
    paid = np.where(table["diff"] > 0, table["yes_ask"], table["yes_bid"])
    fee = fee_per_contract(np.clip(paid, 0.01, 0.99), round_to_cent=False)
    table = table.assign(fit_se=fit_se, forward_se=fwd_se, sigma=sigma, cost=half + fee)
    table["limit"] = table["cost"] + 2 * table["sigma"]
    used = day.used["strike"]
    gaps = no_quote_intervals(day)
    in_gap = np.array([any(a < k < b for a, b in gaps) for k in K], dtype=bool)
    beyond = (K < used.min()) | (K > used.max())
    table["status"] = np.select(
        [in_gap, beyond, (table["diff"].abs() > table["limit"]).to_numpy()],
        [NO_QUOTES, BEYOND, OVER],
        WITHIN,
    )
    table.attrs["forward_error"] = d
    table.attrs["forward_error_source"] = why
    return table


# --- the one-sided offset and the index's move before the snapshot ------------------------


def index_move(bars: pd.DataFrame, t: pd.Timestamp, minutes: float) -> float:
    """Index change over the ``minutes`` before ``t`` (bar covering ``t`` minus the bar covering
    ``t - minutes``); NaN when the saved bars don't reach back that far."""
    try:
        _, now = options.index_at(bars, t)
        _, then = options.index_at(bars, t - pd.Timedelta(minutes=minutes))
    except ValueError:
        return float("nan")
    return now - then


@dataclass(frozen=True)
class Offset:
    """Whether the options and Kalshi disagree to one side on one snapshot, and the index's
    move before it. Descriptive only: nothing is concluded from a single snapshot."""

    n: int  # strikes assessed (status within / beyond limit)
    above_ask: int
    below_bid: int
    mean_diff: float  # options minus Kalshi mid, probability
    shift: float  # index points the options' forward would move to best match Kalshi's mids
    parity_minus_index: float  # the options' own forward vs the index we fitted with
    move_15m: float  # index change over the 15 minutes before the quote clock
    move_5m: float
    kalshi_lag_s: float  # Kalshi candle close minus the quote clock, seconds

    @property
    def side(self) -> str:
        if self.above_ask and not self.below_bid:
            return "options above"
        if self.below_bid and not self.above_ask:
            return "options below"
        return "mixed" if self.above_ask else "none outside"


def offset_summary(
    day: SameDay, table: pd.DataFrame, bars: pd.DataFrame, kalshi_quotes: pd.DataFrame
) -> Offset:
    """Summarise the assessed strikes of one snapshot (not in a no-quote gap or beyond the fit).

    ``shift`` is found by moving the options' forward from -30 to +30 points in 0.1 steps and
    keeping the one with the smallest squared distance to Kalshi's mids. Negative means Kalshi
    prices the index lower than the options do. Kalshi is used here only to *describe* the
    disagreement, never to change the fit.
    """
    a = table[table["status"].isin([WITHIN, OVER])]
    K, mid = a["strike"].to_numpy(), a["kalshi_mid"].to_numpy()
    if len(a):
        shifts = np.round(np.arange(-300, 301) * 0.1, 1)
        sse = [((prob_above(_shifted(day.fit, s), K, day.r) - mid) ** 2).sum() for s in shifts]
        shift = float(shifts[int(np.argmin(sse))])
    else:
        shift = float("nan")
    fp, n = options.parity_check(day)
    times = kalshi_quotes["time"].dropna() if "time" in kalshi_quotes else pd.Series([])
    lag = (pd.Timestamp(times.iloc[0]) - day.quote_time).total_seconds() if len(times) else np.nan
    return Offset(
        n=len(a),
        above_ask=int((a["p_options"] > a["yes_ask"]).sum()),
        below_bid=int((a["p_options"] < a["yes_bid"]).sum()),
        mean_diff=float(a["diff"].mean()) if len(a) else float("nan"),
        shift=shift,
        parity_minus_index=fp - day.forward if n else float("nan"),
        move_15m=index_move(bars, day.quote_time, 15),
        move_5m=index_move(bars, day.quote_time, 5),
        kalshi_lag_s=float(lag),
    )
