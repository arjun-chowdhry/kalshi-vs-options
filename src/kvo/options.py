"""Same-day SPX options: download, clean and fit an SVI smile to today's expiry.

Why SPX, not SPY
----------------
Kalshi settles on the S&P 500 index itself. SPX options are written on that same index,
are European (no early exercise to strip out), and the daily SPXW expiries settle on the 4pm
closing value, the same number Kalshi uses. SPY is an ETF worth about a tenth of the index,
with dividends and American exercise, so it would need a mapping step that adds error. Yahoo
serves SPX chains with daily expiries for free (checked 2026-11-04, see docs/FEASIBILITY.md),
so we don't need SPY.

Reused from options-desk
------------------------
``fetch_chain`` / ``fetch_rate_curve`` (downloads), ``quote_flags`` (zero-bid, crossed and
wide quotes), ``year_fraction``, the Black-Scholes implied-vol solver and ``fit_chain`` (SVI).
We do *not* use options-desk's ``clean_chain`` for the same-day expiry, for the reasons below.

Why same-day cleaning is different (snapshot 2026-11-05T142350)
---------------------------------------------------------------
That snapshot fitted with an RMSE of 20.6 vol points and a forward of 7438.75 against an index
of 7367.90. The cause was bad put quotes from Yahoo: 114 of the 116 in-the-money puts had a
tight, two-sided, recently traded bid/ask *below intrinsic value* (the 7500 put was quoted
9.40/9.60, intrinsic 132, last trade 128.35), and so were most out-of-the-money puts from 7330
to 7365. ``clean_chain``'s parity forward takes the strikes with the smallest ``|C - P|``, and
a put wrongly quoted near the call's price makes ``|C - P|`` look small, so the median landed
on exactly those pairs. With F = 7438.75 the bad puts then counted as OTM and supplied 93% of
the fit error. Its staleness filter (5 days) also can't see a call last traded 90 minutes ago.

So for the same-day expiry:

1. **The quote clock is the latest trade in the chain** (``quote_time``). Yahoo is about 15
   minutes delayed, so the quotes describe that moment, not the download time.
2. **The forward is the index at the quote clock** (``index_at``: the 1-minute SPX bar covering
   that moment, also delayed by Yahoo by about the same amount). Over a few hours the carry
   ``F = S e^{(r-q)T}`` adds well under a tenth of a point, so we use the index as is. Parity is
   kept only as a check (``parity_check``), from pairs whose in-the-money leg is worth at least
   its intrinsic value, and the report flags a disagreement.
3. **Time to expiry from the quote clock** (the download time would shorten T by the delay
   and inflate every vol by about 8% on that snapshot).
4. **Staleness in minutes**: a quote whose last trade is more than ``STALE_MINUTES`` older than
   the quote clock is dropped. And a quote far from a trade *in the same contract* seconds
   before the clock is dropped as ``off_tape``: on that snapshot the bad puts started at 7305,
   below where the no-arbitrage checks can see them, and every one of them was 1-14 points
   under its own trade from less than a minute earlier.
5. **No-arbitrage on the OTM curve** (``otm_arbitrage``). Puts must not get cheaper as the
   strike rises, calls must not get dearer, and across the forward put-call parity plus
   monotonicity bound each side by the other. See that function for which quote is dropped.
6. **Near the money only**: within ``N_SD`` expected moves (ATM vol x sqrt(T) x F, the ATM vol
   estimated from the checked quotes closest to the forward), where SVI is meant to fit.

Every quote of the expiry comes back with a ``reason`` ("" when it is fitted) so the report can
say what was dropped and why. Nothing here looks at Kalshi: the comparison with Kalshi lives in
``kvo.compare`` and runs only after the fit.

In-the-money calls for the lower wing
-------------------------------------
By parity, an ITM call gives a synthetic OTM put: ``P = C - DF (F - K)``. That could replace
bad puts, but it inherits any forward error one for one: on the 2026-11-05 snapshot moving F by
6 points (index vs parity) moved the 7320 synthetic-put vol from 65% to 49%. So we use it only
when ``itm_call_check`` finds the ITM calls sane *and* agreeing with the real puts where both
exist, and then only at strikes where the real put was dropped.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

import numpy as np
import pandas as pd
import yfinance as yf
from optdesk.data.clean import quote_flags, year_fraction
from optdesk.data.fetch import fetch_chain, fetch_rate_curve
from optdesk.data.rates import RateCurve
from optdesk.pricing.black_scholes import bs_price
from optdesk.pricing.implied_vol import implied_vol
from optdesk.surface.svi import SVIParams, fit_chain

__all__ = [
    "N_SD",
    "STALE_MINUTES",
    "TICKER",
    "SameDay",
    "atm_vol",
    "expected_move",
    "fetch_spx",
    "index_at",
    "itm_call_check",
    "largest_gap",
    "off_tape",
    "otm_arbitrage",
    "parity_check",
    "prob_above",
    "quote_age_minutes",
    "quote_time",
    "same_day_fit",
    "same_day_quotes",
    "spx_minutes",
    "svi_kink",
]

TICKER = "^SPX"
NEW_YORK = "America/New_York"
STALE_MINUTES = 15.0  # a same-day quote whose last trade is older than this is dropped
N_SD = 2.0  # fit strikes within this many expected moves of the forward
TICK = 0.05  # SPX option tick under $3
TAPE_SECONDS = 60  # a trade this close to the quote clock is a check on the quote (off_tape)
TAPE_POINTS, TAPE_SHARE = 0.5, 0.2  # ...which may differ from it by max(0.5, 20% of the trade)
MAX_BAR_GAP = pd.Timedelta(minutes=2)  # how far the nearest index bar may be from the clock
ITM_AGREE_VOL = 0.02  # ITM-call synthetic puts must match real puts within 2 vol points
ITM_MIN_COMMON = 3  # ...at at least this many strikes, or they can't be checked


# --- downloads ------------------------------------------------------------------------------


def fetch_spx(n_expiries: int = 2) -> tuple[pd.DataFrame, RateCurve]:
    """Raw SPX chain for the nearest ``n_expiries`` (today's first) and the Treasury curve."""
    return fetch_chain(TICKER, n_expiries), fetch_rate_curve()


def spx_minutes() -> pd.DataFrame:
    """Today's 1-minute SPX bars from Yahoo: ``time`` (bar start, UTC) and ``close``."""
    bars = yf.Ticker(TICKER).history(period="1d", interval="1m")
    if bars.empty:
        return pd.DataFrame({"time": pd.Series(dtype="datetime64[ns, UTC]"), "close": []})
    return pd.DataFrame({"time": bars.index.tz_convert("UTC"), "close": bars["Close"].to_numpy()})


# --- the quote clock and the index at that moment -------------------------------------------


def _expiry_chain(raw: pd.DataFrame, expiry: str | pd.Timestamp) -> pd.DataFrame:
    day = pd.Timestamp(expiry).normalize()
    return raw[pd.to_datetime(raw["expiry"]).dt.normalize() == day]


def quote_time(raw: pd.DataFrame, expiry: str | pd.Timestamp) -> pd.Timestamp:
    """The moment the (delayed) quotes describe: the latest trade in that expiry (UTC)."""
    chain = _expiry_chain(raw, expiry)
    return pd.Timestamp(chain["last_trade"].max()) if not chain.empty else pd.NaT


def quote_age_minutes(raw: pd.DataFrame, expiry: str | pd.Timestamp) -> float:
    """Minutes between the download and the quote clock: an estimate of the feed delay.

    If the most active contracts traded seconds ago in reality but the latest trade we see is
    15 minutes old, the feed is about 15 minutes delayed (so this is also an upper bound).
    """
    chain = _expiry_chain(raw, expiry)
    t = quote_time(raw, expiry)
    if pd.isna(t):
        return float("nan")
    return (chain["asof"].iloc[0] - t) / pd.Timedelta(minutes=1)


def index_at(bars: pd.DataFrame, t: pd.Timestamp) -> tuple[pd.Timestamp, float]:
    """``(bar start, close)`` of the 1-minute bar covering ``t``: the last bar starting at or
    before it. Raises if that bar is more than ``MAX_BAR_GAP`` before ``t`` (no bar near the
    quote clock, so the index at that moment is unknown)."""
    before = bars[bars["time"] <= t]
    if before.empty or t - before["time"].iloc[-1] > MAX_BAR_GAP:
        raise ValueError(f"no 1-minute SPX bar within {MAX_BAR_GAP} before {t}")
    row = before.iloc[-1]
    return pd.Timestamp(row["time"]), float(row["close"])


# --- cleaning ---------------------------------------------------------------------------------


@dataclass(frozen=True)
class SameDay:
    """One same-day expiry after cleaning (and fitting, once ``same_day_fit`` has run)."""

    quotes: pd.DataFrame  # every quote of the expiry, ``reason`` "" for the fitted ones
    T: float  # years from the quote clock to 4pm
    r: float
    forward: float  # the index at the quote clock
    quote_time: pd.Timestamp
    atm_vol: float  # estimate from the quotes nearest the forward (sets the window)
    expected_move: float  # atm_vol * sqrt(T) * forward, index points
    n_sd: float
    itm_calls: dict  # itm_call_check's verdict
    fit: pd.Series | None = None

    @property
    def used(self) -> pd.DataFrame:
        return self.quotes[self.quotes["reason"] == ""]

    @property
    def discount(self) -> float:
        return float(np.exp(-self.r * self.T))


def off_tape(chain: pd.DataFrame, t_quote: pd.Timestamp) -> pd.Series:
    """True where a quote disagrees with a trade in the same contract moments earlier.

    If the contract traded within ``TAPE_SECONDS`` of the quote clock, its mid should be close
    to that trade: in under a minute the index moves a few points at most, and a same-day
    option's price moves by its delta times that. A mid more than ``max(TAPE_POINTS,
    TAPE_SHARE x last)`` from such a trade means the quote, not the market, is off. On
    2026-11-05 the bad puts (7305-7365) were 1-14 points below trades 0-50 seconds old, while
    every other fresh quote within 7150-7600 was within 0.25 of its trade.
    """
    fresh = (t_quote - chain["last_trade"]) <= pd.Timedelta(seconds=TAPE_SECONDS)
    mid = (chain["bid"] + chain["ask"]) / 2
    allowed = np.maximum(TAPE_POINTS, TAPE_SHARE * chain["last"])
    return fresh & ((mid - chain["last"]).abs() > allowed)


def otm_arbitrage(
    strike: np.ndarray,
    bid: np.ndarray,
    ask: np.ndarray,
    is_call: np.ndarray,
    forward: float,
    discount: float,
) -> np.ndarray:
    """True for OTM quotes that break static no-arbitrage; inputs are the OTM quotes only.

    A violation counts only if it could be traded: one quote's ask below what another quote's
    bid (or a parity bound built from it) says it must be worth. Gaps inside the spread don't.

    1. *Monotonic in strike.* An OTM put can't be worth less than a put at a lower strike, and
       an OTM call can't be worth more than a call at a higher strike. Walking each side in from
       its far wing, a quote whose ask is below the highest bid already kept is dropped.
       Why from the wing: the far-wing quotes are cheap, so a bad one there would have to be
       *too dear* to hide good ones nearer the money; the corruption we have seen (2026-11-05)
       was the opposite, near-the-money quotes far too cheap.
    2. *Across the forward.* By parity a put is ``C(K) - DF (F - K)``, and a call is worth at
       least any call at a higher strike, so ``P(K) >= C(Kc) - DF (F - K)`` with ``Kc`` the
       nearest kept OTM call; likewise ``C(K) >= P(Kp) - DF (K - F)`` with ``Kp`` the nearest
       kept OTM put. This catches a run of bad puts that happens to be monotonic among itself.
    """
    strike, bid, ask, is_call = (np.asarray(x) for x in (strike, bid, ask, is_call))
    bad = np.zeros(strike.size, dtype=bool)
    for side, ascending in ((~is_call, True), (is_call, False)):
        idx = np.flatnonzero(side)
        idx = idx[np.argsort(strike[idx])]
        if not ascending:
            idx = idx[::-1]
        best_bid = -np.inf
        for i in idx:
            if ask[i] < best_bid:
                bad[i] = True
            else:
                best_bid = max(best_bid, bid[i])
    puts = np.flatnonzero(~is_call & ~bad)
    calls = np.flatnonzero(is_call & ~bad)
    if puts.size and calls.size:
        kc = calls[np.argmin(strike[calls])]  # nearest-the-money kept call
        kp = puts[np.argmax(strike[puts])]  # nearest-the-money kept put
        put_floor = bid[kc] - discount * (forward - strike[puts])
        call_floor = bid[kp] - discount * (strike[calls] - forward)
        bad[puts[ask[puts] < put_floor]] = True
        bad[calls[ask[calls] < call_floor]] = True
    return bad


def _iv(price, F, K, T, r, call) -> np.ndarray:
    """Black-Scholes vol on the forward (S = F, q = r), the options-desk convention."""
    n = len(price)
    return implied_vol(
        np.asarray(price, dtype=float),
        S=np.full(n, F),
        K=np.asarray(K, dtype=float),
        T=np.full(n, T),
        r=np.full(n, r),
        q=np.full(n, r),
        call=np.asarray(call, dtype=bool),
    )


def atm_vol(quotes: pd.DataFrame, forward: float, n_each: int = 2) -> float:
    """Median implied vol of the ``n_each`` usable quotes nearest the forward on each side."""
    ok = quotes[quotes["iv"].notna()]
    below = ok[ok["strike"] < forward].nlargest(n_each, "strike")
    above = ok[ok["strike"] >= forward].nsmallest(n_each, "strike")
    near = pd.concat([below, above])
    return float(near["iv"].median()) if not near.empty else float("nan")


def expected_move(vol: float, T: float, forward: float) -> float:
    """One standard deviation of the index to expiry, in index points: ``vol sqrt(T) F``."""
    return vol * np.sqrt(T) * forward


def same_day_quotes(
    raw: pd.DataFrame,
    curve: RateCurve,
    expiry: str | pd.Timestamp,
    index: float,
    t_quote: pd.Timestamp,
    *,
    max_rel_spread: float = 0.5,
    stale_minutes: float = STALE_MINUTES,
    n_sd: float = N_SD,
    use_itm_calls: bool = True,
) -> SameDay:
    """Every quote of the expiry with its mid, implied vol and why it was dropped.

    ``reason`` is "" for the quotes to fit, else the first check it failed: ``zero_bid``,
    ``crossed``, ``wide``, ``stale``, ``off_tape`` (see ``off_tape``), ``itm`` (in the money:
    we fit OTM options only),
    ``arbitrage``, ``no_iv`` or ``far`` (outside ``n_sd`` expected moves). ``source`` is
    ``"quote"``, or ``"itm_call"`` for a synthetic put made from an ITM call (see the module
    notes; only when ``itm_call_check`` passes and ``use_itm_calls``). Returned inside a
    ``SameDay`` with the clock, forward, ATM vol and the ITM-call verdict (``fit`` is None).
    """
    chain = _expiry_chain(raw, expiry)
    chain = chain.drop_duplicates(subset=["option_type", "strike"]).copy()
    T = float(year_fraction(t_quote, pd.Timestamp(expiry)))
    r = float(curve(np.array([T]))[0])
    DF = float(np.exp(-r * T))
    F = float(index)

    flags = quote_flags(chain, max_rel_spread=max_rel_spread, max_stale_days=None)
    age = t_quote - chain["last_trade"]
    flags["stale"] = ~(age <= pd.Timedelta(minutes=stale_minutes))  # never traded -> stale
    flags["off_tape"] = off_tape(chain, t_quote)
    is_call = (chain["option_type"] == "call").to_numpy()
    flags["itm"] = np.where(is_call, chain["strike"] < F, chain["strike"] >= F)

    q = chain.assign(
        mid=(chain["bid"] + chain["ask"]) / 2,
        rel_spread=(chain["ask"] - chain["bid"]) / ((chain["bid"] + chain["ask"]) / 2),
        T=T,
        r=r,
        forward=F,
        source="quote",
        price=np.nan,  # the price we invert: mid, or the synthetic put for "itm_call"
    )
    q["reason"] = ""
    for name in ("zero_bid", "crossed", "wide", "stale", "off_tape", "itm"):
        q.loc[(q["reason"] == "") & flags[name].to_numpy(), "reason"] = name

    otm = q["reason"] == ""
    bad = otm_arbitrage(
        q.loc[otm, "strike"].to_numpy(),
        q.loc[otm, "bid"].to_numpy(),
        q.loc[otm, "ask"].to_numpy(),
        (q.loc[otm, "option_type"] == "call").to_numpy(),
        F,
        DF,
    )
    q.loc[q.index[otm][bad], "reason"] = "arbitrage"
    q["price"] = q["mid"]
    q["iv"] = np.nan
    keep = q["reason"] == ""
    q.loc[keep, "iv"] = _iv(
        q.loc[keep, "mid"], F, q.loc[keep, "strike"], T, r, q.loc[keep, "option_type"] == "call"
    )
    q.loc[keep & q["iv"].isna(), "reason"] = "no_iv"

    # The window comes from the checked OTM quotes alone (synthetic puts can't move it).
    vol = atm_vol(q[q["reason"] == ""], F)
    move = expected_move(vol, T, F)
    window = n_sd * move if np.isfinite(move) else np.inf
    itm = itm_call_check(q[(q["strike"] - F).abs() <= window], F, T, r)
    if use_itm_calls and itm["sane"]:
        q = _add_synthetic_puts(q, itm["table"], F, T, r)
    far = (q["reason"] == "") & ((q["strike"] - F).abs() > window)
    q.loc[far, "reason"] = "far"
    q["k"] = np.log(q["strike"] / F)
    q = q.sort_values(["strike", "option_type"]).reset_index(drop=True)
    return SameDay(q, T, r, F, pd.Timestamp(t_quote), vol, move, n_sd, itm)


def _add_synthetic_puts(q: pd.DataFrame, table: pd.DataFrame, F, T, r) -> pd.DataFrame:
    """Replace dropped OTM puts by synthetic puts from checked ITM calls at the same strike."""
    puts = q[(q["option_type"] == "put") & (q["strike"] < F)].set_index("strike")
    used = set(puts.index[puts["reason"] == ""])
    rows = []
    for _, c in table[table["ok"]].iterrows():
        if c["strike"] in used:
            continue
        row = q.loc[q["contract"] == c["contract"]].iloc[0].copy()
        row["source"], row["reason"], row["option_type"] = "itm_call", "", "put"
        row["price"], row["iv"] = c["synthetic_put"], c["iv_synthetic"]
        rows.append(row)
    if not rows:
        return q
    # The synthetic put stands in for the call quote it came from; drop the real put row.
    drop = q["option_type"].eq("put") & q["strike"].isin([row["strike"] for row in rows])
    return pd.concat([q[~drop], pd.DataFrame(rows)], ignore_index=True)


def itm_call_check(q: pd.DataFrame, forward: float, T: float, r: float) -> dict:
    """Are the in-the-money calls good enough to stand in for bad puts? See the module notes.

    Uses the ITM calls in ``q`` that pass the basic filters (not zero-bid, crossed, wide or
    stale); the caller passes only the strikes inside the fit window.
    ``table``: one row per such call with its synthetic put ``C - DF (F - K)``, that put's
    relative spread and implied vol, the real put's vol at the strike if it was fitted, and
    ``ok`` (synthetic put positive with a spread under 50%, and no butterfly or monotonicity
    violation among the calls). ``sane`` needs every call ``ok`` and the synthetic puts to agree
    with the real ones within ``ITM_AGREE_VOL`` (median) at ``ITM_MIN_COMMON`` strikes or more.
    ``why`` lists every condition that failed ("" when sane).
    """
    DF = float(np.exp(-r * T))
    calls = q[(q["option_type"] == "call") & (q["reason"] == "itm")].sort_values("strike")
    t = pd.DataFrame(
        {
            "contract": calls["contract"].to_numpy(),
            "strike": calls["strike"].to_numpy(),
            "mid": calls["mid"].to_numpy(),
        }
    )
    t["synthetic_put"] = t["mid"] - DF * (forward - t["strike"])
    spread = (calls["ask"] - calls["bid"]).to_numpy()
    with np.errstate(divide="ignore", invalid="ignore"):
        t["synthetic_rel_spread"] = spread / t["synthetic_put"].to_numpy()
    positive = t["synthetic_put"] > 0
    t["iv_synthetic"] = np.nan
    if positive.any():
        t.loc[positive, "iv_synthetic"] = _iv(
            t.loc[positive, "synthetic_put"], forward, t.loc[positive, "strike"], T, r,
            np.zeros(int(positive.sum()), bool),
        )  # fmt: skip
    # Calls must fall with strike (slope in [-DF, 0]) and be convex (slopes rising).
    shape_ok = np.ones(len(t), dtype=bool)
    if len(t) >= 2:
        K, C = t["strike"].to_numpy(), t["mid"].to_numpy()
        slope = np.diff(C) / np.diff(K)
        for i in np.flatnonzero((slope > TICK / 5) | (slope < -DF - TICK / 5)):
            shape_ok[[i, i + 1]] = False
        convex = np.diff(slope) * np.diff(K)[1:] >= -TICK  # butterfly value >= -1 tick
        for i in np.flatnonzero(~convex):
            shape_ok[[i, i + 1, i + 2]] = False
    t["ok"] = positive & (t["synthetic_rel_spread"] <= 0.5) & t["iv_synthetic"].notna() & shape_ok
    real = q[(q["option_type"] == "put") & (q["reason"] == "")].set_index("strike")["iv"]
    t["iv_put"] = t["strike"].map(real)
    common = t.dropna(subset=["iv_synthetic", "iv_put"])
    gap = (
        float((common["iv_synthetic"] - common["iv_put"]).abs().median()) if len(common) else np.nan
    )

    problems = []
    if t.empty:
        problems.append("no ITM calls pass the basic filters")
    elif not t["ok"].all():
        bad = t.loc[~t["ok"], "strike"].astype(int).astype(str)
        problems.append(f"bounds/butterfly violations at {', '.join(bad)}")
    if len(common) < ITM_MIN_COMMON:
        problems.append(f"only {len(common)} strikes to check them against real puts")
    elif not gap <= ITM_AGREE_VOL:
        problems.append(f"synthetic puts differ from real puts by {gap * 100:.1f} vol points")
    why = "; ".join(problems)
    return {"sane": why == "", "why": why, "n": len(t), "vol_gap": gap, "table": t}


def parity_check(day: SameDay) -> tuple[float, int]:
    """Forward from put-call parity, as a check on the index: ``(median F, number of pairs)``.

    A strike counts only if both its call and its put passed the basic filters, the OTM leg
    passed the no-arbitrage checks (reason "", ``far`` or ``no_iv``), and the ITM leg is worth
    at least its intrinsic value against the index (a quote below intrinsic is wrong). Unlike
    picking the smallest ``|C - P|``, this can't be steered toward broken quotes.
    """
    q, index, DF = day.quotes, day.forward, day.discount
    usable = q["reason"].isin(["", "far", "no_iv", "itm"]) & (q["source"] == "quote")
    m = q[usable].pivot(index="strike", columns="option_type", values="mid")
    m = m.reindex(columns=["call", "put"]).dropna()
    if m.empty:
        return float("nan"), 0
    K = m.index.to_numpy()
    ok = (m["call"] >= DF * np.maximum(index - K, 0) - TICK) & (
        m["put"] >= DF * np.maximum(K - index, 0) - TICK
    )
    m = m[ok]
    if m.empty:
        return float("nan"), 0
    F = m.index.to_numpy() + (m["call"] - m["put"]).to_numpy() / DF
    return float(np.median(F)), int(len(F))


# --- fitting and what the fit implies ----------------------------------------------------


def same_day_fit(
    raw: pd.DataFrame,
    curve: RateCurve,
    expiry: str | pd.Timestamp,
    index: float,
    t_quote: pd.Timestamp,
    **kwargs,
) -> SameDay:
    """Cleaned quotes and SVI fit (``SameDay.fit``) for one same-day expiry.

    ``index`` is the SPX level at the quote clock ``t_quote`` (``index_at``, ``quote_time``).
    The fit row has ``T``, ``forward``, the SVI parameters, ``rmse``, ``max_error``, ``n`` and
    ``success``, plus ``atm_vol`` (the fitted vol at the forward). It is None when fewer than 5
    quotes are left (after hours, when every bid is zero). ``kwargs`` go to
    ``same_day_quotes``.
    """
    day = same_day_quotes(raw, curve, expiry, index, t_quote, **kwargs)
    if len(day.used) < 5:
        return day
    fit = fit_chain(day.used).iloc[0].copy()
    fit["atm_vol"] = float(_params(fit).implied_vol(np.array([0.0]), fit["T"])[0])
    return replace(day, fit=fit)


def _params(fit: pd.Series) -> SVIParams:
    return SVIParams(*(float(fit[x]) for x in ("a", "b", "rho", "m", "sigma")))


def prob_above(fit: pd.Series, strikes, r: float = 0.0, h: float = 0.5) -> np.ndarray:
    """Options-implied probability that the index settles at or above each strike.

    ``P(S_T > K) = -dC/dK / DF``, the slope of the call price along the fitted smile (so the
    skew is included, not just ``N(d2)``), by central differences ``h`` points apart.
    """
    K = np.asarray(strikes, dtype=float)
    F, T = float(fit["forward"]), float(fit["T"])
    p = _params(fit)

    def call(k_abs):
        vol = p.implied_vol(np.log(k_abs / F), T)
        return bs_price(F, k_abs, T, r, vol, r, True)

    DF = np.exp(-r * T)
    return np.clip(-(call(K + h) - call(K - h)) / (2 * h) / DF, 0.0, 1.0)


def svi_kink(fit: pd.Series) -> tuple[float, float]:
    """``(strike, width in index points)`` of the SVI smile's vertex.

    The vertex is at ``k = m`` and ``sigma`` sets how rounded it is: about ``sigma F`` points.
    With ``sigma`` at options-desk's lower bound (1e-4) the smile is a sharp V, and since the
    probability of finishing above K comes from the smile's slope, it jumps at the vertex. If
    the vertex sits in a strike gap, that jump is the fit's shape, not anything quoted.
    """
    F = float(fit["forward"])
    return F * float(np.exp(fit["m"])), float(fit["sigma"]) * F


def largest_gap(used: pd.DataFrame, forward: float, move: float) -> tuple[float, float]:
    """Widest space between neighbouring fitted strikes that overlaps one expected move of the
    forward: ``(lower strike, upper strike)``. A wide gap here means the ATM vol is
    interpolated, not observed."""
    K = np.unique(used["strike"].to_numpy())
    if K.size < 2:
        return float("nan"), float("nan")
    lo, hi = K[:-1], K[1:]
    near = (hi >= forward - move) & (lo <= forward + move)
    if not near.any():
        near = np.ones_like(lo, dtype=bool)
    i = np.flatnonzero(near)[np.argmax((hi - lo)[near])]
    return float(lo[i]), float(hi[i])
