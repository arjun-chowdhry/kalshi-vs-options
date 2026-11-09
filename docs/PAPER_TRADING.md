# Milestone 3: paper trading

Started Friday 2026-11-06 on branch `m3-paper`. No orders are placed, ever. A "trade" here is
a row in a table: one $1 contract, bought at Kalshi's price at the moment the option quotes
are from, held until Kalshi settles it.

## Read this first: what these numbers can't tell you

- **All the P&L comes from one day.** There are six snapshots, two each from 2026-11-05,
  2026-11-06 and 2026-11-09. Two of those days have settled, but neither rule traded on Friday
  2026-11-06. So every settled trade still rides on **one closing price**: 7353.73 on
  2026-11-05. Monday 2026-11-09 hasn't settled.
- **Trades on the same day are not separate experiments.** They all win or lose on the same
  close. Twenty trades on one day are closer to one bet than to twenty. That is why the report
  shows two standard errors. The one that treats trades as independent is too small. The one
  computed across days is the honest one, and it can't be computed until at least two settled
  days have trades. Friday doesn't count: a day with no trades has no P&L per trade.
- **A null result is the expected outcome.** With a handful of days, no profit or loss either
  way can be told apart from luck. M2 also found no strike where the options and Kalshi
  disagree by more than the data can resolve. So the strict rule is expected to make no trades,
  and it made none.
- **The fee rate (0.07) is not verified first-hand.** Kalshi's fee schedule wouldn't open.
  0.07 is the higher of the two rates quoted elsewhere, so it is the conservative choice. It
  also decides close calls: at 0.035, the naive rule would have made one trade on Friday.
- **Fills are assumed.** Every trade fills one contract at the quoted ask (or at 1 - bid for
  NO), from Kalshi's 1-minute candle at the options' quote clock. Real fills could be worse,
  and the book can change within the minute.

## The two rules

Both rules use M2's per-strike table (`kvo.compare.comparison_table`). Both can buy either side:
YES when the options say the index is more likely to close above the strike than Kalshi's
price implies, NO when less likely.

| Rule | Buys YES when | Buys NO when | Strikes with no option quote of their own |
|---|---|---|---|
| **Strict** | the options probability is above Kalshi's mid by more than the **resolution limit** (half the spread + fee + 2 x the options' uncertainty) | the same, below the mid | never traded |
| **Naive** | options probability > ask + fee | options probability < bid - fee | traded; shown separately |

The fee is Kalshi's taker fee for one contract, rounded up to the cent: 1-2 cents.

## Results (run 2026-11-09, after Friday settled and before Monday's close)

| Snapshot | Close | Strict trades | Naive trades |
|---|---|---|---|
| 2026-11-05T142350 (14:08 ET) | 7353.73 | 0 | 14, **all at strikes with no assessment** |
| 2026-11-05T150047 (14:45 ET) | 7353.73 | 0 | 6, 3 of them at strikes with no assessment |
| 2026-11-06T112037 (11:05 ET) | 7376.86 | 0 | 0 |
| 2026-11-06T112524 (11:10 ET) | 7376.86 | 0 | 0 |
| 2026-11-09T131948 (13:04 ET) | not settled yet | 0 | 0 |
| 2026-11-09T132459 (13:10 ET) | not settled yet | 0 | 7, 3 of them at strikes with no assessment |

"No assessment" means the strike has no option quote of its own, or is outside the fitted
quotes (`in_gap` in `trades.csv`).

P&L is in dollars per $1 contract, after fees. The trade counts include Monday's 7 unsettled
naive trades. Every P&L column covers settled trades only, all from 2026-11-05:

| Rule | Trades (YES / NO) | Settled | Settled days | Won | Total P&L | Mean P&L | SE, trades independent | SE, by day | Mean expected P&L |
|---|---|---|---|---|---|---|---|---|---|
| Strict | 0 | 0 | 0 | - | $0.00 | - | - | - | - |
| Naive, all strikes | 27 (4 / 23) | 20 | 1 | 14 | +$2.95 | +$0.148 | $0.075 | **n/a (1 day)** | +$0.014 |
| Naive, assessed strikes only | 7 (1 / 6) | 3 | 1 | 3 | +$0.87 | +$0.290 | $0.101 | **n/a (1 day)** | +$0.004 |

**What this says, plainly:**

- **Friday adds nothing to the P&L, because there were no trades to score.** Neither rule traded
  on either Friday snapshot. Friday's close of 7376.86 settled no contracts here, and the
  totals are the same as before it.
- **Friday's naive zero was a near miss.** The closest candidate was YES at 7410 on T112037,
  0.7 cents short of covering the ask and the fee. On T112524 the closest was 2.2 cents short.
  At the lower quoted fee rate (0.035), the T112037 trade would have happened, paying 54 cents
  plus a 1-cent fee. The index closed below 7410, so it would have lost $0.55. One trade proves
  nothing, but it shows the zero depends on an unverified input.
- **The strict rule found nothing to trade, on any of the six snapshots.** That is the
  expected result. It matches M2: nowhere is the disagreement bigger than the data can resolve.
- **Monday's 7 naive trades are unscored.** All 7 are NO bets, and the largest expected profit
  is 1.1 cents. The same rule made no trades on the snapshot five minutes earlier, so these
  signals are not stable from one snapshot to the next.
- **The naive rule made money on Thursday, but this says nothing about skill.** Its $2.95 is one day's
  close. The index was at 7368-7413 when the snapshots were taken and fell to 7353.73 by 4pm.
  16 of the 20 naive trades were NO bets, which pay when the index ends lower. The options'
  own probabilities expected about 1.4 cents a trade, or $0.28 in total. The NO bets made
  $2.50 of the $2.95. The other $2.67 is the gap between what happened and what was
  expected, and it comes from the index falling. On a day the index rose, most of those NO bets
  would have lost.
- **The independent-trades SE ($0.075) makes +$0.148 look about 2 standard errors from zero.
  It isn't.** All 20 trades share one close, so that SE is far too small. The by-day SE needs a
  second settled day.
- **17 of the 20 settled naive trades were at strikes with no assessment.** That
  includes all 14 on 2026-11-05T142350, in the gap where the fitted curve had a sharp kink
  (FEASIBILITY.md). Those probabilities come from the curve's shape, not from prices, and under
  the project's rules they are never a finding. The strict rule refused every one.

## How to re-run

```powershell
.venv\Scripts\python.exe scripts\check_settlement.py   # after about 7pm New York: record closes
.venv\Scripts\python.exe scripts\paper_trade.py        # trades, settlement, summary
```

Every trade goes to `data\m3\trades.csv`, and the summary to `data\m3\summary.csv`. Both files
are regenerated on each run and are not kept in git. Days only count as settled once
`data\settlements.csv` has Kalshi's settlement value for them. The P&L uses the value Kalshi
actually paid on. So far it has matched `^GSPC` on every day checked.

## Not done yet (Milestone 4 is on hold)

- Re-run after each new settled day. The by-day standard error appears once two settled days
  have trades. 2026-11-09 would be the second for the naive rule. The strict rule has no trades
  at all, so it has no standard error. Either way it only means much after a few weeks.
- Milestone 4 is on hold until you say to start it.
