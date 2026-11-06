# Milestone 1: is the data good enough?

Checked on Wednesday 2026-11-04, mostly after the 4pm close (about 7pm New York). Every
number below was observed directly, from Kalshi's public API, Kalshi's docs, or Yahoo via
yfinance, unless it is marked **(general knowledge)** or **(unverified)**.

## Verdict: feasible (closed 2026-11-06)

- **The Kalshi side works.** It is free, needs no account or key, has the right contracts,
  real two-sided quotes during the day, and free minute-by-minute price history.
- **The SPX option side works, with daily cleaning.** Yahoo serves same-day SPX expiries
  whose strikes and settlement line up with Kalshi's. Three market-hours snapshots (two late on
  2026-11-05, one mid-morning on 2026-11-06) all gave a converged SVI fit with RMSE under 1.6
  vol points after cleaning. The morning one was the best by far: 51 quotes, RMSE 0.52, a
  10-point strike gap (see [Morning run](#morning-run-snapshot-2026-11-06t112037)). The
  go/no-go for Milestone 4 is **go**.
- **Snapshots should be taken mid-morning.** On the evidence so far (one morning, one
  afternoon day; not yet separated from day-to-day variation) the morning chain is much
  cleaner. Daily snapshots are scheduled for 11:15am New York.
- **The big limit is history on the options side.** Yahoo has no past option chains. The
  backtest and scoreboard can only use snapshots we save from now on, so the sample builds up
  at one day per trading day.

## Kalshi

| Question | Answer | Source |
|---|---|---|
| Which series? | `KXINXU` "S&P 500 above/below": one event per hour, 10am to 4pm New York, every trading day. We use the 4pm event, e.g. `KXINXU-26NOV05H1600`. `KXINX` "S&P 500 range" (daily 4pm) also exists; not needed. | `GET /series/KXINXU`, `GET /events?series_ticker=KXINXU` |
| What does a contract pay? | $1 if "the end-of-day S&P 500 index value ... is above 7744.9999", i.e. at or above 7745.00. | `rules_primary` field of each market |
| Range contracts (`KXINX`) | 30 per 4pm close: 28 buckets 25 points wide ("7,675 to 7,699.9999"), a tail below and a tail at or above. Exactly one pays, so their prices should sum to about 100%, the independent check planned for M2. Saved in every snapshot as `ranges.parquet`. The next day's contracts were still `initialized` (not trading, no quotes) at 7:30pm. | `GET /markets?event_ticker=KXINX-...` |
| Strikes | 60-80 per 4pm event, **5 index points apart** (Nov 3: 7425-7720; Nov 4: 7375-7770). | `GET /markets?event_ticker=...` |
| Settlement value | Published per market as `expiration_value`: 7568.92 (Nov 3), 7688.62 (Nov 4). Both equal the S&P 500 close on Yahoo (`^GSPC`). So actual outcomes come free from Kalshi. | API + yfinance |
| Settlement source change | Kalshi: "Effective Friday, November 6, 2026, this event's source agency will change to S&P Global Inc." Same index, different feed. Worth watching for any mismatch. | `product_metadata` of the series |
| Trading hours | The next day's 4pm event opened at 4:16pm the previous afternoon (`open_time`), and closes at 4pm on the day. | market JSON |
| Liquidity | 264k contracts traded on the Nov 3 4pm event, 469k on Nov 4. | `volume_fp` summed over strikes |
| Spreads during the day | From hourly candles: at 11am, 13:00 and 3pm New York, 9-30 strikes were priced 5-95 cents with both a bid and an ask. **Median spread 1-3 cents, widest 5 cents.** Overnight (7pm): median 4 cents. | `GET /series/KXINXU/markets/{ticker}/candlesticks` |
| Historical prices? | **Yes.** 1-minute, hourly and daily candles of the YES bid and ask (open/high/low/close) and volume, plus individual trades, all public for recent markets. Markets settled before 2026-09-05 move to a `/historical` archive. Archived market details and settlement values load fine there, but my one archived candle request failed (**unverified** whether archived candles are available). | `/candlesticks`, `/markets/trades`, `/historical/cutoff`, `/historical/markets` |
| Do we need a key? | No. Every request above was an unauthenticated GET. | observed |
| Rate limits | Kalshi documents token budgets for logged-in accounts: Basic tier 200 read tokens per second, about 20 requests per second. Limits for requests without a key are not documented (**unverified**). A snapshot makes 3 requests, and the client spaces every request at least 0.2 s apart (5 per second at most). | docs.kalshi.com/getting_started/rate_limits |
| Fees | `KXINXU` reports `fee_type: quadratic, fee_multiplier: 1`, effective 2026-07-03. Kalshi's docs say fees are computed to $0.000001 and charged in whole cents per order, with leftovers rebated. The formula's rate, **0.07**, comes from secondary sources quoting Kalshi's fee schedule PDF, which returned HTTP 429 to every attempt, so **unverified first-hand**. Some sources quote 0.035 for S&P markets; we use the higher 0.07 to be conservative. At 50 cents that is 1.75 cents per contract. | `GET /series/fee_changes?series_ticker=KXINXU`, docs.kalshi.com/getting_started/fee_rounding |

**What it costs to act on a gap:** buying at the ask instead of the mid costs half the spread
(about 1 cent), plus the fee (about 2 cents near 50 cents, less toward the wings). So a gap
between the option-implied probability and the Kalshi mid must be bigger than about **3
percentage points** before it shows up as a paper profit.

## SPX options (Yahoo via yfinance)

| Question | Answer | Source |
|---|---|---|
| Same-day SPX expiries? | **Yes.** `^SPX` lists daily expiries (2026-11-05, 11-06, 11-09, ...). Contracts are SPXW (e.g. `SPXW261105C07730000`). | yfinance 1.7.0 |
| Strikes | 141 calls and 197 puts for 2026-11-05, **5 points apart** near the money, the same grid as Kalshi. | yfinance |
| Settlement | SPXW daily options are European, cash-settled on the 4pm closing index value, the same number Kalshi uses **(general knowledge)**. | |
| Quote quality | **Mixed, measured 2026-11-05 at 14:23 ET** (see below). Calls and deep OTM puts are clean; Yahoo's put bid/asks from 7305 up were corrupted (tight, two-sided, freshly traded, and below intrinsic or far below their own last trade). The same-day cleaning in `kvo/options.py` now catches this. | `scripts/fit_snapshot.py` |
| Delay | Yahoo option quotes are about 15 minutes delayed **(general knowledge; options-desk notes the same)**. `scripts/snapshot.py` measures it on every run (minutes since the latest trade, and since the latest 1-minute index bar). | |
| SPY needed? | No. SPX is the same index Kalshi settles on, with no ETF-to-index mapping. SPY stays as a fallback only if SPX same-day quotes turn out unusable. | |
| History | **None for free.** Yahoo serves only the live chain. | |

**Matching the times:** options are about 15 minutes stale and Kalshi is live. Because Kalshi
minute candles are public, Milestone 2 can look up the Kalshi bid and ask at the minute the
option quotes are from, instead of comparing a live price with a stale one.

## What the pipeline does now

`scripts/snapshot.py` finds the open 4pm event, saves every Kalshi strike, the raw SPX chain
(today's and the next expiry), the Treasury curve and the latest index bar into
`data/snapshots/<New York time>/`, then prints a quality report. Tonight's test run:

```
Kalshi KXINXU-26NOV05H1600: 70 strikes, 50 with a bid and an ask; median spread 0.04 on the 33 strikes priced 5-95 cents
SPX 2026-11-05: 338 quotes, 1 with a bid; latest trade 179.1 min before download
SPX index: 7688.73, latest 1-min bar 195.1 min before download
SVI: not fitted, only 0 clean quotes (market closed?)
```

## First market-hours run (snapshot 2026-11-05T142350)

The first fit gave an SVI RMSE of 20.6 vol points and a parity forward of 7438.75 against an
index of 7367.90. Diagnosis and fix:

- **Cause: corrupted put quotes.** 114 of 116 in-the-money puts were quoted below intrinsic
  (the 7500 put at 9.40/9.60, intrinsic 132, last trade 128.35), and the OTM puts from 7305 to
  7365 were 1-14 points below trades in the same contract from under a minute earlier. The
  parity rule (median over the 5 strikes with the smallest `|C - P|`) picked exactly those
  pairs. With F = 7438.75 the bad puts then counted as OTM and made 93% of the fit error.
- **Delay, measured:** the latest option trade (the quote clock) was 15.1 minutes before the
  download; the latest index bar 15.8 minutes. Kalshi is live. At the quote clock Kalshi's
  50% point was ~7367 (the index: 7367.90); at download it was ~7381.
- **Fix** (`kvo/options.py`): the index at the quote clock as the forward, T from the quote
  clock, a 15-minute staleness cut, an "off the tape" check (mid vs a trade seconds earlier),
  tradeable no-arbitrage checks across strikes and across the forward, and strikes within two
  expected moves. Parity is kept as a check only (7371.8, +3.9 vs the index).
- **ITM calls** were checked as a substitute for the bad puts and rejected: the 7320/7325/7340
  calls are not convex, and a synthetic put inherits the forward's error one for one.
- **Result:** 18 quotes (7250-7475), RMSE 1.57 vol points, ATM vol 55.3%. But no clean quote
  between 7300 and 7390 (1.5 expected moves), and the SVI vertex sits in that gap with a sharp
  kink, so option probabilities there are the fit's shape. Kalshi agrees within its bid-ask at
  25 of the 30 strikes outside the gap and at 1 of 17 inside it (sanity check only; Kalshi is
  never used in the fit).

**It recurs.** A second snapshot the same day (2026-11-05T150047, quote clock 14:45:45 ET,
index 7413.45) had the same pattern in puts 7370-7410, just below the index; with them
dropped: 20 quotes, RMSE 0.84 vol points, ATM vol 59.5%, a 7365-7420 gap (1.0 expected moves).
So the cleaning is needed every day, and there will usually be a gap just below the money.

Still open for Milestone 2: how to get probabilities across that gap without an artificial
kink, and whether the corruption follows the index (it sat just below it both times).

### The off-the-tape rule (frozen 2026-11-05)

**The rule** (`kvo.options.off_tape`): drop a quote if its contract traded within 60 seconds
before the quote clock and its mid is more than max(0.5 index points, 20% of that trade) away
from the trade price.

**Why it was added.** The no-arbitrage checks drop a put only when its ask is below a price
it must be worth, and the corrupted puts at 7305-7325 on 2026-11-05T142350 stayed above every
such bound. They were 0.95-2.40 points below trades in the same contracts 0-50 seconds before
the clock. Every other quote between 7150 and 7600 that had traded in that window was within
0.25 of its trade. A move that big in under a minute would need an index move several times
larger than one minute of a 55% vol allows. The threshold was set from those option quotes
alone, with room on both sides: the smallest corrupted gap was 0.95, the largest clean one
0.225.

**How it was found, stated plainly.** I added the rule **after looking at the Kalshi
comparison table** for 2026-11-05T142350. That table showed the options' probability falling
12 points between 7315 and 7320, and that jump led me back to the 7305-7325 puts. Kalshi
prices are not an input to the rule and were not used to choose its threshold. But Kalshi is
what prompted the rule, so the comparison on these two snapshots is not fully independent of
it.

**Frozen.** The rule and its three numbers (60 s, 0.5, 20%) will not change after this point,
whatever later Kalshi comparisons show. If a future snapshot shows the rule wrongly dropping
good quotes, that goes in this document as a known limitation, not into a retuned rule.

**What it changed**, on both snapshots of 2026-11-05. The fit itself is the same frozen code,
with only `off_tape` switched off for the "off" rows. "Within" means the options probability
falls inside Kalshi's bid-ask at the quote-clock minute. Each row uses its own strike gap,
because the rule changes which quotes survive:

| Snapshot | Rule | Quotes | RMSE (vol pts) | ATM vol | Gap | Kalshi within bid-ask: all | outside gap | inside gap | Mean / max \|options - Kalshi\| |
|---|---|---|---|---|---|---|---|---|---|
| T142350 | on | 18 | 1.57 | 55.3% | 7300-7390 | 26 / 47 | 25 / 30 | 1 / 17 | 2.3 / 6.3 pts |
| T142350 | off | 21 | 1.70 | 53.0% | 7325-7390 | 19 / 47 | 19 / 35 | 0 / 12 | 3.5 / 10.1 pts |
| T150047 | on | 20 | 0.84 | 59.5% | 7365-7420 | 25 / 42 | 23 / 32 | 2 / 10 | 1.3 / 3.6 pts |
| T150047 | off | 23 | 14.86 | 66.9% | 7385-7425 | 22 / 42 | 20 / 35 | 2 / 7 | 1.9 / 4.4 pts |

- **T142350:** without the rule, the 7305-7325 puts stay in and pull the smile's low point
  toward them. Seven strikes change from outside to within Kalshi's spread or back (7270-7290,
  7405-7415), and the options probability moves by up to 5.1 points.
- **T150047:** without the rule, the corrupted puts at 7370-7410 are fitted and the fit breaks
  (RMSE 14.9 vol points). Thirteen strikes change status, and the probability moves by up to 5.0
  points.
- With the rule on, agreement outside the gap is 25/30 and 23/32. Inside the gap it is 1/17
  and 2/10 either way: the gap is where the options say nothing.

## Morning run (snapshot 2026-11-06T112037)

Downloaded 11:20:37 ET (10:20 CT) on Friday 2026-11-06, quote clock 11:05:36 ET, index at
the quote clock 7412.33, 4.91 h to the close. Same frozen code as the 2026-11-05 rows above,
nothing retuned. Reproduce with `scripts\fit_snapshot.py data\snapshots\2026-11-06T112037`.

- **Chain:** 497 quotes, 348 with a bid (2026-11-05: 338 quotes, 245-263 with a bid).
  Dropped 117 stale, 35 wide, 149 zero bids, and **0 off the tape**: no corrupted puts this
  time. The puts just below the index, corrupted on both 2026-11-05 snapshots, were clean.
- **Parity:** forward 7412.20 from 55 clean pairs, -0.13 vs the index (2026-11-05: 1 and 11
  pairs, +3.9 and -5.3). So the forward error that dominates the resolution limit was about
  zero this morning.
- **Fit:** 51 quotes 7285-7540, RMSE 0.52 vol points (max 1.23), ATM vol 37.3%, expected move
  to 4pm 64 points. Largest strike gap near the money 7415-7425: **10 points, 0.16 expected
  moves**, against 55-90 points (1.0-1.5 expected moves) the day before. Only one Kalshi
  strike (7420) falls inside it.
- **Kalshi comparison** (after the fit, not used in it; Kalshi candles closing 11:06 ET):
  37 of 53 strikes within Kalshi's bid-ask, 36 of 52 outside the gap. Mean |options - Kalshi
  mid| 1.0 points, max 2.8.
- **The 16 misses are all on one side**, 7370-7450 apart from 7435: options above Kalshi's
  ask by 0.2-1.3 points, mean signed difference +1.0. On 2026-11-05 the misses were mostly
  below the bid. The options' 50% point is about 7418, Kalshi's about 7414. Not diagnosed. The
  index was falling (7433 at 10:51, 7412 at 11:05) and Kalshi's candle closes 24 seconds after
  the quote clock, so a move or timing offset of a few index points would be enough. Either
  way it is well below the 5-6 point resolution limit (README) and the ~3 point cost of acting,
  so **it is not a finding**. M2 should track whether a one-sided offset recurs.

### All three snapshots

| Snapshot | Quote clock (ET) | To close | Quotes with a bid | Off the tape | Parity vs index | Fitted | RMSE (vol pts) | ATM vol | Strike gap | Within Kalshi bid-ask: all / outside gap | Mean / max \|options - Kalshi\| |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 11-05 T142350 | 14:08:45 | 1.85 h | 263 / 338 | 28 | +3.9 (1 pair) | 18 | 1.57 | 55.3% | 90 pts, 1.51 EM | 26/47, 25/30 | 2.3 / 6.3 pts |
| 11-05 T150047 | 14:45:45 | 1.24 h | 245 / 338 | 14 | -5.3 (11 pairs) | 20 | 0.84 | 59.5% | 55 pts, 1.03 EM | 25/42, 23/32 | 1.3 / 3.6 pts |
| 11-06 T112037 | 11:05:36 | 4.91 h | 348 / 497 | 0 | -0.1 (55 pairs) | 51 | 0.52 | 37.3% | 10 pts, 0.16 EM | 37/53, 36/52 | 1.0 / 2.8 pts |

### Time of day

The morning chain was better on every measure of the fit: 2.5 times as many fitted quotes, no
off-the-tape corruption, a parity forward agreeing with the index, and a strike gap shrunk from over one
expected move to a sixth of one. The no-quote gap, the main open problem from 2026-11-05,
nearly disappeared.

**What this does and does not show.** It is one morning on one day against two afternoons on
another. Time of day is mixed up with the day itself (Friday vs Thursday, a calmer 37% ATM vol
vs 55-60%) and with time to expiry (4.9 h vs 1.2-1.9 h: with more time left, more strikes
near the money carry real premium). Not everything was cleaner: the morning chain is longer,
and both its stale count (117) and its zero-bid count (149) were higher than the afternoon's
(54-64 and 75-93), mostly far from the money. So "mornings are cleaner" is a working hypothesis,
not a result. It is enough to pick a time for the daily snapshot, and the schedule is set
from it: **every weekday at 11:15am New York (10:15am Central)**, so the 15-minute-delayed
quotes are from about 11am, the same point in the day as this run, about 5 h before the close.
To test the hypothesis properly, M2 needs some days with both a morning and an afternoon
snapshot.

### Still open, carried to Milestone 2

- Whether the put corruption recurs in the morning, and whether it follows the index.
- Probabilities across the strike gap on days it is wide (none needed this morning).
- The one-sided ~1 point offset seen this morning: timing, the forward, or real.
- The settlement source change to S&P Global took effect today, 2026-11-06. Check tonight's
  `expiration_value` for `KXINXU-26NOV06H1600` against the `^GSPC` close.

## Sources
- Kalshi API (public, no key): https://api.elections.kalshi.com/trade-api/v2 (`/series`, `/events`, `/markets`, `/markets/{ticker}/orderbook`, `/series/{s}/markets/{t}/candlesticks`, `/markets/trades`, `/historical/*`, `/series/fee_changes`)
- Contract terms (linked from the series; not read yet, the market `rules_primary` text was used): https://assets.kalshi.com/contract_terms/INX.pdf
- Rate limits: https://docs.kalshi.com/getting_started/rate_limits
- Fee rounding: https://docs.kalshi.com/getting_started/fee_rounding
- Fee schedule (could not open, HTTP 429): https://kalshi.com/docs/kalshi-fee-schedule.pdf
- Secondary sources for the 0.07 rate: https://defirate.com/prediction-markets/fees/, https://whirligigbear.substack.com/p/makertaker-math-on-kalshi
