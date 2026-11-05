"""The text report printed after a snapshot: clock and staleness, cleaning, fit, Kalshi check.

Shared by ``scripts/snapshot.py`` (right after downloading) and ``scripts/fit_snapshot.py``
(re-fitting a saved snapshot), so both print the same thing. The Kalshi comparison comes last
and is computed from the finished fit; nothing in it changes the fit (see ``kvo.compare``).
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from optdesk.data.rates import RateCurve

from kvo import options
from kvo.compare import kalshi_check
from kvo.options import SameDay

__all__ = ["KALSHI_WINDOW", "kalshi_strikes_near", "same_day_report"]

NEW_YORK = "America/New_York"
KALSHI_WINDOW = 150.0  # index points either side of the index: the Kalshi strikes we look up
PARITY_WARN = 0.2  # flag a parity forward more than this many expected moves from the index
GAP_WARN = 1.0  # flag a near-the-money strike gap wider than this many expected moves
KINK_WARN = 0.25  # flag an SVI vertex in that gap rounded over less than this share of it

_REASONS = {
    "stale": f"stale (last trade > {options.STALE_MINUTES:.0f} min before the clock)",
    "off_tape": "off the tape (mid far from a trade < 1 min before the clock)",
    "arbitrage": "no-arbitrage violations",
    "wide": "wide spreads",
    "zero_bid": "zero bids",
    "crossed": "crossed",
    "no_iv": "no implied vol",
}


def _ny(t: pd.Timestamp) -> str:
    return pd.Timestamp(t).tz_convert(NEW_YORK).strftime("%H:%M:%S ET")


def _strikes(values) -> str:
    return ", ".join(str(int(k)) for k in sorted(values))


def kalshi_strikes_near(markets: pd.DataFrame, index: float) -> pd.DataFrame:
    """The Kalshi "above" markets within ``KALSHI_WINDOW`` points of the index."""
    return markets[(markets["strike"] - index).abs() <= KALSHI_WINDOW]


def same_day_report(
    raw: pd.DataFrame,
    curve: RateCurve,
    expiry: str | pd.Timestamp,
    bars: pd.DataFrame,
    kalshi_at_quote: pd.DataFrame | None = None,
) -> tuple[SameDay | None, list[str]]:
    """Clean and fit the same-day expiry and describe it: ``(result, report lines)``.

    ``result`` is None when there is nothing to fit (no quotes, or no index bar near the
    quote clock); the lines then say why.
    """
    lines = []
    chain = raw[pd.to_datetime(raw["expiry"]).dt.normalize() == pd.Timestamp(expiry).normalize()]
    if chain.empty:
        return None, [f"SPX {expiry}: no quotes for this expiry"]
    asof = pd.Timestamp(chain["asof"].iloc[0])
    t_quote = options.quote_time(raw, expiry)
    lines.append(
        f"SPX {expiry}: {len(chain)} quotes, {(chain['bid'] > 0).sum()} with a bid; quote clock "
        f"{_ny(t_quote)} (latest trade), {options.quote_age_minutes(raw, expiry):.1f} min "
        f"before download"
    )
    try:
        bar_time, index = options.index_at(bars, t_quote)
    except ValueError as err:
        return None, [*lines, f"SPX index: {err}; not fitting"]
    last_lag = (asof - bars["time"].iloc[-1]) / pd.Timedelta(minutes=1)
    lines.append(
        f"SPX index at the quote clock: {index:.2f} (1-min bar {_ny(bar_time)}); latest bar "
        f"{last_lag:.1f} min before download"
    )

    day = options.same_day_fit(raw, curve, expiry, index, t_quote)
    q = day.quotes
    hours_lost = (asof - t_quote) / pd.Timedelta(hours=1)
    lines.append(
        f"Time to expiry from the quote clock: {day.T * 365 * 24:.2f} h (from the download it "
        f"would be {day.T * 365 * 24 - hours_lost:.2f} h)"
    )
    counts = q["reason"].value_counts()
    dropped = [f"{counts[r]} {label}" for r, label in _REASONS.items() if counts.get(r, 0)]
    lines.append("Dropped: " + "; ".join(dropped))
    near = (q["strike"] - index).abs() <= 2 * day.expected_move
    for reason, label in (("off_tape", "off the tape"), ("arbitrage", "no-arbitrage")):
        otm = np.where(q["option_type"] == "call", q["strike"] >= index, q["strike"] < index)
        hit = q.loc[(q["reason"] == reason) & near & otm]
        for side in ("put", "call"):
            ks = hit.loc[hit["option_type"] == side, "strike"]
            if len(ks):
                lines.append(f"  {label} near the money, {side}s: {_strikes(ks)}")
    stale_near = q[
        (q["reason"] == "stale") & ((q["strike"] - index).abs() <= 2 * day.expected_move)
    ]
    if len(stale_near):
        lines.append(f"  stale near the money: {_strikes(stale_near['strike'])}")
    lines.append(
        f"  not fitted by design: {counts.get('itm', 0)} in the money, "
        f"{counts.get('far', 0)} beyond {day.n_sd:g} expected moves "
        f"({day.n_sd * day.expected_move:.0f} points)"
    )

    fp, n_pairs = options.parity_check(day)
    if n_pairs:
        z = (fp - index) / day.expected_move
        flag = "  <-- CHECK: index and parity disagree" if abs(z) > PARITY_WARN else ""
        lines.append(
            f"Parity check: forward {fp:.2f} from {n_pairs} clean pairs, {fp - index:+.2f} vs "
            f"index ({z:+.2f} expected moves){flag}"
        )
    else:
        lines.append("Parity check: no clean call/put pairs")

    itm = day.itm_calls
    synth = q[q["source"] == "itm_call"]
    if itm["sane"]:
        where = _strikes(synth["strike"]) if len(synth) else "none needed"
        lines.append(f"ITM calls: sane; synthetic puts used at {where}")
    else:
        lines.append(f"ITM calls: not used for the lower wing ({itm['why']})")

    if day.fit is None:
        lines.append(f"SVI: not fitted, only {len(day.used)} clean quotes (market closed?)")
        return day, lines
    f, used = day.fit, day.used
    lines.append(
        f"SVI: {int(f['n'])} quotes {used['strike'].min():.0f}-{used['strike'].max():.0f}, "
        f"RMSE {f['rmse'] * 100:.2f} vol points (max {f['max_error'] * 100:.2f}), ATM vol "
        f"{f['atm_vol'] * 100:.1f}%, expected move to 4pm {day.expected_move:.0f} points, "
        f"converged {bool(f['success'])}"
    )
    lo, hi = options.largest_gap(used, index, day.expected_move)
    if np.isfinite(lo):
        width = (hi - lo) / day.expected_move
        flag = "  <-- ATM vol is interpolated across it" if width > GAP_WARN else ""
        lines.append(
            f"Largest strike gap near the money: {lo:.0f} to {hi:.0f} ({hi - lo:.0f} points, "
            f"{width:.2f} expected moves){flag}"
        )
        vertex, kink = options.svi_kink(f)
        if lo < vertex < hi and kink < KINK_WARN * (hi - lo):
            lines.append(
                f"  SVI vertex at {vertex:.0f}, inside that gap, rounded over only {kink:.1f} "
                f"points: option probabilities between {lo:.0f} and {hi:.0f} come from the fit's "
                f"shape, not from quotes"
            )
    else:
        lo = hi = np.nan

    lines.append("")
    lines.extend(_kalshi_lines(day, kalshi_at_quote, (lo, hi)))
    return day, lines


def _kalshi_lines(
    day: SameDay, kalshi_at_quote: pd.DataFrame | None, gap: tuple[float, float]
) -> list[str]:
    head = "Kalshi sanity check (after the fit, not used in it)"
    if kalshi_at_quote is None or kalshi_at_quote.empty:
        return [f"{head}: no Kalshi prices at the quote clock saved"]
    table = kalshi_check(day, kalshi_at_quote)
    if table.empty:
        return [f"{head}: no two-sided Kalshi strikes priced 3-97 cents at the quote clock"]
    minute = kalshi_at_quote["time"].dropna()
    when = _ny(minute.iloc[0]) if len(minute) else "?"
    in_gap = (table["strike"] > gap[0]) & (table["strike"] < gap[1])
    mean, worst = table["diff"].mean() * 100, table["diff"].abs().max() * 100
    lines = [
        f"{head}, Kalshi candles closing {when}: {len(table)} strikes; options minus Kalshi mid "
        f"averages {mean:+.1f} points (largest {worst:.1f}); "
        f"{int(table['outside'].sum())} strikes outside Kalshi's bid-ask",
        f"  in the strike gap: {int(in_gap.sum())} strikes, {int(table['outside'][in_gap].sum())} "
        f"outside; elsewhere: {int((~in_gap).sum())} strikes, "
        f"{int(table['outside'][~in_gap].sum())} outside",
        "  strike  kalshi bid/ask  options   (* outside Kalshi's bid-ask, g inside the strike gap)",
    ]
    for _, row in table.iterrows():
        mark = ("  *" if row["outside"] else "   ") + (
            " g" if gap[0] < row["strike"] < gap[1] else ""
        )
        lines.append(
            f"  {row['strike']:>6.0f}   {row['yes_bid']:.2f} / {row['yes_ask']:.2f}    "
            f"{row['p_options']:.3f}{mark}".rstrip()
        )
    return lines
