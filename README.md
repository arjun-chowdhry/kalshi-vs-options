# Kalshi vs options

Does Kalshi's price for "S&P 500 above X at 4pm today" agree with the probability implied by
same-day SPX option prices, and does any gap survive Kalshi's fees and the bid-ask spread?

Work in progress. Milestone 1 (data feasibility) is in [docs/FEASIBILITY.md](docs/FEASIBILITY.md).
Read-only: public market data only, no orders, no keys.

## Plan

- **M1, data feasibility (done):** [docs/FEASIBILITY.md](docs/FEASIBILITY.md). Same-day
  cleaning in `kvo/options.py`. The off-the-tape rule is frozen as of 2026-11-05.
- **M2, compare the two markets:** options-implied P(close >= K) against Kalshi's bid/ask at
  the options' quote clock, one snapshot at a time. Ground rules:
  - Kalshi prices are never an input to the options fit. They are compared only after it.
  - Every chart shades the strike gap near the money where no option quote survived cleaning,
    labelled **"no usable option quotes"**. Probabilities there come from the fit's shape, not
    from prices.
  - An edge at a strike inside that gap is never reported as a finding. At most it is noted as
    "inside the no-quote gap, not assessed".
- **Resolution limit:** the free data can't credibly detect a gap between the options and
  Kalshi smaller than about **5-6 percentage points** at typical strikes outside the no-quote
  gap. That is about 3 points of Kalshi cost (half the spread plus the fee) plus twice the
  options' own uncertainty of about 1-1.5 points. Near the gap's edges the limit is **up to
  about 18 points**, where the uncertainty reaches 4-7 points. **Inside the gap there is no
  limit, because there is no measurement.** On both 2026-11-05 snapshots that gap was 1.0-1.5
  expected moves wide and covered the at-the-money strikes. The options' uncertainty combines
  the fit error (leave-one-out refits) with a forward error (index vs parity, 4-5 points). It
  is measured per strike on two snapshots from one day so far, and M2 re-measures it on every
  snapshot and applies the limit strike by strike.

## Setup and daily use

```powershell
py -3.13 -m venv .venv
.venv\Scripts\python.exe -m pip install -e ".[dev]"
.venv\Scripts\python.exe -m pytest
.venv\Scripts\python.exe scripts\snapshot.py       # during market hours: save + report
.venv\Scripts\python.exe scripts\fit_snapshot.py   # re-fit the latest saved snapshot
```
