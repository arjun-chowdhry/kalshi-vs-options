# Milestone 2: options against Kalshi, strike by strike

Started Friday 2026-11-06 on branch `m2-compare`. Six snapshots so far, from three trading days.
Every number below comes from `scripts\compare_snapshots.py` (per-strike tables in
`data\m2\<snapshot>.csv`, the offset summary in `data\m2\offsets.csv`) or
`scripts\check_settlement.py` (`data\settlements.csv`). The fit and the cleaning are the frozen
M1 code. Nothing was retuned after looking at Kalshi.

## What is computed, per strike

For every Kalshi "above" strike priced 3-97 cents at the options' quote clock
(`kvo.compare.comparison_table`):

| Column | Meaning |
|---|---|
| `diff` | Options probability minus Kalshi's mid. |
| `fit_se` | Jackknife standard error from leave-one-out refits: drop each fitted quote in turn, refit SVI, recompute the probability. |
| `forward_se` | How much the probability moves if the forward is off by the **forward error**, either way. |
| `sigma` | `fit_se` and `forward_se` added in quadrature: the options' own uncertainty. |
| `cost` | Half Kalshi's spread plus the exact taker fee (0.07 x P x (1-P)) at the price you would pay. |
| `limit` | `cost + 2 x sigma`. This is the smallest gap the free data can credibly detect at that strike. |
| `status` | `no usable option quotes`: strictly between two fitted strikes more than 5 points apart. `beyond the fitted quotes`: outside the fitted range. **Neither is ever assessed.** Everywhere else: `beyond limit` if \|diff\| > limit, else `within limit`. |

**The forward error** is the larger of two numbers: the parity forward's distance from the index, and the median
1-minute index move over the 30 minutes before the quote clock. We fit to a 1-minute bar
close, and the quote clock falls somewhere inside that minute. With no parity forward it is 5
points (the 2026-11-05 parity gaps were 3.9 and 5.3). This is a choice, and it is the main
driver of the limit near the money. On 2026-11-06 parity agreed with the index to 0.1-1.8
points, but the index moved a median 4 points a minute, so the minute move set the error.

**The gap rule is wider than M1's.** M1's report marks only the largest gap near the money.
Here every Kalshi strike without a fitted option quote at its own strike is labelled. On
2026-11-05T150047 that adds the stale-call gaps 7425-7510 to the 7365-7420 one.

## Results

| Snapshot | Quote clock (ET) | Forward error (pts) | Assessed / no quotes / beyond fit | Limit, all assessed | Limit, strikes priced 20-80c | Beyond limit | Largest \|diff\| / limit |
|---|---|---|---|---|---|---|---|
| 11-05 T142350 | 14:08:45 | 3.9 (parity, 1 pair) | 16 / 28 / 3 | 3.1-10.2 | 8.0-8.8 | **0** | 0.35 |
| 11-05 T150047 | 14:45:45 | 5.3 (parity, 11 pairs) | 19 / 22 / 1 | 3.6-13.1 | 8.0-13.1 | **0** | 0.41 |
| 11-06 T112037 | 11:05:36 | 4.1 (1-min move) | 49 / 1 / 3 | 2.9-9.0 | 6.3-9.0 | **0** | 0.32 |
| 11-06 T112524 | 11:10:22 | 3.9 (1-min move) | 48 / 1 / 0 | 2.3-8.7 | 6.6-8.7 | **0** | 0.27 |
| 11-09 T131948 | 13:04:50 | 0.8 (1-min move) | 11 / 0 / 5 | 2.4-7.6 | 6.4-7.6 | **0** | 0.41 |
| 11-09 T132459 | 13:10:01 | 0.8 (1-min move) | 11 / 0 / 5 | 2.7-9.1 | 5.6-8.7 | **0** | 0.55 |

Limits and differences are in probability points.

- **No strike on any snapshot is beyond the resolution limit.** The largest disagreement used
  at most 55% of the limit at its strike. So far, wherever the options can be measured, they
  and Kalshi agree to within what this data can resolve.
- **The limit near the money is larger than the README's earlier estimate.** At strikes
  priced 20-80 cents it is 6-13 points. The README said 5-6. The difference is the forward error: 4-5 points of
  forward error moves the probability at those strikes by 1.5-4.5 points, and `2 x sigma` there is 3-10.
  Away from the money the limit falls to 2-4 points, mostly Kalshi's cost.
- **The jackknife fit error is small when quotes are dense.** On 2026-11-06 it was 0.6 points at most.
  At strikes assessed next to the 2026-11-05 gaps it reached 2.6-3.5 points.
- **Only the 2026-11-05 snapshots have many strikes with no option quotes.** On both 2026-11-06 snapshots one strike (7420)
  is unassessed. On 2026-11-05 more than half are. On 2026-11-09 none is in a gap, but 5 of the 16 strikes
  are beyond the fitted quotes, so they are not assessed either.

## The one-sided offset: an observation, not a finding

M1 noted that on 2026-11-06T112037 all 16 strikes outside Kalshi's bid-ask had the options
above the ask. Here is the same check on every snapshot, assessed strikes only.
`shift` is how many index points the options' forward would have to move to best match
Kalshi's mids (negative: Kalshi prices the index lower). It is fitted only to describe the
disagreement and is not fed back into anything.

| Snapshot | Assessed | Options > ask | Options < bid | Mean diff | Shift (pts) | Parity - index | Index move, 15 min / 5 min before | Kalshi candle after quote clock | Side |
|---|---|---|---|---|---|---|---|---|---|
| 11-05 T142350 | 16 | 2 | 2 | +0.7 | +0.0 | +3.93 | n/a (no bars saved) | 15 s | mixed |
| 11-05 T150047 | 19 | 1 | 4 | -0.3 | +2.5 | -5.28 | +36.8 / +16.8 | 15 s | mixed |
| 11-06 T112037 | 49 | 15 | 0 | +1.0 | -3.0 | -0.13 | -16.9 / -3.9 | 24 s | options above |
| 11-06 T112524 | 48 | 0 | 0 | +0.2 | -0.1 | +1.78 | -6.8 / +5.0 | 38 s | none outside |
| 11-09 T131948 | 11 | 6 | 0 | +1.6 | -1.1 | +0.23 | -1.1 / +0.2 | 10 s | options above |
| 11-09 T132459 | 11 | 0 | 7 | -2.2 | +1.5 | -0.29 | +1.0 / -2.0 | 59 s | options below |

**What this shows so far:**

- **The offset did not repeat.** In the snapshot taken five minutes after T112037 on the same
  morning, no strike was outside Kalshi's bid-ask, and the shift was -0.1 points. On 2026-11-05
  the misses went both ways. On 2026-11-09 it reversed in five minutes, from options above the
  ask on 6 strikes to options below the bid on 7.
- **The size is within the forward error on 2026-11-06, but not on 2026-11-09.** The 3.0-point
  shift on T112037 is smaller than the 4.1-point forward error already in that snapshot's limit.
  The 1.1 and 1.5-point shifts on 2026-11-09 are larger than that day's 0.8-point forward error.
  Those differences still used at most 55% of the limit, because the limit also includes the
  fit error and Kalshi's cost.
- **Timing.** Four snapshots have a shift of at least 1 point and the 15-minute bars to compare with. On all four, Kalshi had moved further in
  the direction of the index's last 15 minutes: lower in a falling market, higher in a rising
  one. That is what a timing difference would produce. On 2026-11-09, though, the index moved only about 1 point in those 15 minutes, too little to tell apart from noise. And the Kalshi candle closes only 10-59
  seconds after the quote clock. At the 15-minute rate before T112037 (about 1.1 points a
  minute), 24 seconds is only about half a point, not 3. A 3-point move inside one minute is
  ordinary that morning, though: the median 1-minute move was 4 points. The data
  can't place prices more finely than one minute. And on T112037 the options' own parity
  forward matched the index (-0.13), so if timing explains the shift, the difference is between Yahoo's clock and Kalshi's,
  not inside the option chain.
- **Verdict: none.** Four snapshots out of four lining up with the move is not evidence. Under
  the rule set for this, the offset stays out of the findings until it has been checked on at
  least **5 trading days** (`OFFSET_MIN_DAYS`). It has 3 so far. The scheduled 11:15am snapshot adds one day per
  trading day. Some days should also get a second snapshot a few minutes later, as on
  2026-11-06, because the T112037/T112524 pair is the most informative comparison so far.

## Settlement check

Kalshi's `expiration_value` against Yahoo's `^GSPC` close (`scripts\check_settlement.py`, run
2026-11-06 and 2026-11-09):

| Day | Event | Kalshi | ^GSPC | Result |
|---|---|---|---|---|
| 2026-11-03 | KXINXU-26NOV03H1600 | 7568.92 | 7568.92 | match |
| 2026-11-04 | KXINXU-26NOV04H1600 | 7688.62 | 7688.62 | match |
| 2026-11-05 | KXINXU-26NOV05H1600 | 7353.73 | 7353.73 | match |
| 2026-11-06 | KXINXU-26NOV06H1600 | 7376.86 | 7376.86 | match (first day under the S&P Global source) |

Kalshi settles about 3 hours after the close (the 11-04 event settled at 7:01pm New York).
Before 4:15pm New York, `^GSPC`'s daily bar for the same day is the live price, so the
script won't use it. The snapshot task runs this check after each snapshot and records any
earlier day that has settled. One matching day says little yet about the new source.

## Still open

- Kalshi's range contracts (`KXINX`): the sum-to-100% check and the comparison with the
  "above" contracts.
- Whether the forward error should use the full median 1-minute move. It is the main reason
  the limit is 6-13 points near the money.
- The offset, on at least 5 trading days.
