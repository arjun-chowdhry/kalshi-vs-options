# Milestone 3: paper trading

Started Friday 2026-11-06 on branch `m3-paper`. No orders are placed, ever. A "trade" here is
a row in a table: one $1 contract, bought at Kalshi's price at the moment the option quotes
are from, held until Kalshi settles it.

## Read this first: what these numbers can't tell you

- **The sample is one settled day.** There are four snapshots, two from Thursday 2026-11-05
  and two from Friday 2026-11-06. Friday's close isn't settled yet, so its trades can't be
  scored. Everything settled so far rides on **one closing price**: 7353.73 on 2026-11-05.
- **Trades on the same day are not separate experiments.** They all win or lose on the same
  close. Twenty trades on one day are closer to one bet than to twenty. That is why the report
  shows two standard errors. The one that treats trades as independent is too small. The one
  computed across days is the honest one, and it can't be computed until there are at least
  two settled days.
- **A null result is the expected outcome.** With a handful of days, no profit or loss either
  way can be told apart from luck. M2 also found no strike where the options and Kalshi
  disagree by more than the data can resolve. So the strict rule is expected to make no trades,
  and it made none.
- **The fee rate (0.07) is not verified first-hand.** Kalshi's fee schedule wouldn't open.
  0.07 is the higher of the two rates quoted elsewhere, so it is the conservative choice.
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

## Results (run 2026-11-06, before Friday's close)

| Snapshot | Close | Strict trades | Naive trades |
|---|---|---|---|
| 2026-11-05T142350 (14:08 ET) | 7353.73 | 0 | 14, **all inside the no-quote gap** |
| 2026-11-05T150047 (14:45 ET) | 7353.73 | 0 | 6, 3 of them inside the gap |
| 2026-11-06T112037 (11:05 ET) | not settled yet | 0 | 0 |
| 2026-11-06T112524 (11:10 ET) | not settled yet | 0 | 0 |

P&L is in dollars per $1 contract, after fees:

| Rule | Trades (YES / NO) | Settled | Settled days | Won | Total P&L | Mean P&L | SE, trades independent | SE, by day | Mean expected P&L |
|---|---|---|---|---|---|---|---|---|---|
| Strict | 0 | 0 | 0 | - | $0.00 | - | - | - | - |
| Naive, all strikes | 20 (4 / 16) | 20 | 1 | 14 | +$2.95 | +$0.148 | $0.075 | **n/a (1 day)** | +$0.014 |
| Naive, assessed strikes only | 3 (1 / 2) | 3 | 1 | 3 | +$0.87 | +$0.290 | $0.101 | **n/a (1 day)** | +$0.004 |

**What this says, plainly:**

- **The strict rule found nothing to trade.** That is the expected result. It matches M2:
  nowhere is the disagreement bigger than the data can resolve.
- **The naive rule made money, but this says nothing about skill.** Its $2.95 is one day's
  close. The index was at 7368-7413 when the snapshots were taken and fell to 7353.73 by 4pm.
  16 of the 20 naive trades were NO bets, which pay when the index ends lower. The options'
  own probabilities expected about 1.4 cents a trade, or $0.28 in total. The NO bets made
  $2.50 of the $2.95. The other $2.67 is the gap between what happened and what was
  expected, and it comes from the index falling. On a day the index rose, most of those NO bets
  would have lost.
- **The independent-trades SE ($0.075) makes +$0.148 look about 2 standard errors from zero.
  It isn't.** All 20 trades share one close, so that SE is far too small. The by-day SE needs a
  second settled day.
- **17 of the 20 naive trades were at strikes with no option quote of their own.** That
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

- Re-run after each new settled day. The by-day standard error appears from the second
  settled day on, and it only means much after a few weeks.
- Milestone 4 is on hold until you say to start it.
