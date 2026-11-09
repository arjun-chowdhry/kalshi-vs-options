# Kalshi vs options

Kalshi sells contracts that pay $1 if the S&P 500 closes above a given level today. Options
on the same index, expiring today, also imply a probability for that. This project asks: do
the two agree, and when they don't, is the gap big enough to make money after Kalshi's fees
and the bid-ask spread?

It only reads public market data. It has no account, no keys, and no code that could place an
order. A test checks the source code for that.

## Limits: read these before any result

1. **There is very little data.** Free option data has no history, so the only evidence is
   the snapshots saved since 2026-11-05: six so far, from three trading days. Two of those days
   have settled, but only one had any paper trades, so **all the P&L rests on one close**. A
   new snapshot is scheduled for every weekday at 11:15am New York. With this few days, **a
   null result is the expected outcome**. Nothing here is evidence of an edge.
2. **Small gaps can't be detected.** The options' implied probability is itself uncertain.
   The curve fitted to the option prices has its own error, and so does the index level it is
   anchored to. Adding Kalshi's cost to act, the smallest gap the data can credibly detect is
   **about 6-13 percentage points near the money**, and 2-4 points in the wings. This is
   measured per strike on every snapshot.
3. **Some strikes have no measurement at all.** Yahoo's option quotes are sometimes corrupted
   or stale, and the cleaning removes them. That can leave strikes with no usable option quote
   of their own. On Thursday 2026-11-05 more than half of the Kalshi strikes near the money
   had none. Probabilities there come from the shape of the fitted curve, not from prices. They
   are labelled **"no usable option quotes"** and are never reported as findings.
4. **The two markets are matched only to the minute.** Yahoo's option quotes are about 15
   minutes delayed. Kalshi's price is taken from the same minute, but the data can't line them
   up more finely than that. On a fast-moving morning the index moves about 4 points a minute.
5. **Trades on one day are not independent.** They all settle on the same close, so twenty
   trades on one day are closer to one bet than to twenty. The day is the unit of evidence.
6. **Some inputs are unverified.** Kalshi's fee rate, 0.07, comes from secondary sources,
   because the fee schedule PDF wouldn't open. We use the higher of the rates quoted, to be
   safe. It can decide close calls: at the lower rate, the naive rule would have traded once
   on 2026-11-06. Paper trades assume a one-contract fill at the quoted price.

## Where things stand

| Milestone | Status | What it found |
|---|---|---|
| **M1: is the data good enough?** [docs/FEASIBILITY.md](docs/FEASIBILITY.md) | Done (2026-11-06): **go** | Both markets are free and usable. Yahoo's same-day option quotes need daily cleaning. Mid-morning chains were much cleaner than afternoon ones (one day of each so far). |
| **M2: do the two markets agree?** [docs/COMPARISON.md](docs/COMPARISON.md) | In progress | On every snapshot, every strike where the options can be measured agrees with Kalshi to within the limit in point 2. Kalshi's settlement value matched the `^GSPC` close on every day checked (Nov 3-6). A one-sided disagreement has not held up: on Nov 6 it was gone 5 minutes later, and on Nov 9 it reversed 5 minutes later. It stays an observation until it has been checked on at least 5 trading days (3 so far). |
| **M3: paper trading** [docs/PAPER_TRADING.md](docs/PAPER_TRADING.md) | Done (2026-11-09): **no evidence of an edge** | The strict rule, which trades only past the limit, made **no trades** on any of the six snapshots. The naive rule, which trades whenever the options beat Kalshi's price by more than the fee, made 20 trades on Nov 5 and was up $2.95. That is luck from one falling close: the options themselves expected $0.28, and 17 of the 20 were at strikes with no assessment. Neither rule traded on Nov 6, so that settlement added nothing. Nov 9's 7 naive trades aren't settled. Re-run as days settle. |
| M4 | On hold | |

## Ground rules

- Kalshi prices are never used to clean or fit the options. They are compared only afterwards.
- A gap at a strike with no usable option quote is never a finding.
- The rule that removes corrupted option quotes ("off the tape") has been frozen since
  2026-11-05 and is not retuned after looking at Kalshi.
- The one-sided offset between options and Kalshi is not a finding until it has been checked on at least 5 trading days.

## Setup and daily use

```powershell
py -3.13 -m venv .venv
.venv\Scripts\python.exe -m pip install -e ".[dev]"
.venv\Scripts\python.exe -m pytest
```

| When | Command | What it does |
|---|---|---|
| Weekdays 11:15am New York (scheduled) | `scripts\snapshot_task.cmd` | Saves a snapshot, then checks earlier days' settlements. The log goes to `data\logs\`. |
| Any time, market open | `.venv\Scripts\python.exe scripts\snapshot.py` | Saves a snapshot by hand and prints a quality report. |
| Any time | `.venv\Scripts\python.exe scripts\fit_snapshot.py` | Re-fits the latest saved snapshot. |
| Any time | `.venv\Scripts\python.exe scripts\compare_snapshots.py` | M2: the per-strike comparison and the offset summary. |
| After about 7pm New York | `.venv\Scripts\python.exe scripts\check_settlement.py` | Records Kalshi's settlement value against the `^GSPC` close. |
| After a new settled day | `.venv\Scripts\python.exe scripts\paper_trade.py` | M3: both rules' trades, settled P&L and standard errors. |

The scheduled task lives in Windows Task Scheduler. To set it up, choose Create Task, then:

- **Trigger:** Weekly, Mon-Fri, 10:15am. That is Central time; 11:15am New York.
- **Action:** start `scripts\snapshot_task.cmd`. Leave "Start in" blank.
- **Settings:** tick "Run task as soon as possible after a scheduled start is missed", and stop
  the task after 30 minutes.
