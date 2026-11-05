# Milestone 1: is the data good enough?

Checked on Wednesday 2026-11-04, mostly after the 4pm close (about 7pm New York). Every
number below was observed directly, from Kalshi's public API, Kalshi's docs, or Yahoo via
yfinance, unless it is marked **(general knowledge)** or **(unverified)**.

## Verdict: feasible, with one check still open

- **The Kalshi side works.** It is free, needs no account or key, has the right contracts,
  real two-sided quotes during the day, and free minute-by-minute price history.
- **The SPX option side is promising but not yet verified live.** Yahoo serves same-day SPX
  expiries, and their strikes and settlement line up with Kalshi's. But after the close every
  option bid is zero, so tonight I could not test quote quality or the SVI fit on a same-day
  smile. **This needs one snapshot during market hours** (any weekday 10am-3:30pm New York).
  That run is the go/no-go for Milestone 4.
- **The big limit is history on the options side.** Yahoo has no past option chains. The
  backtest and scoreboard can only use snapshots we save from now on, so the sample builds up
  at one day per trading day.

## Kalshi

| Question | Answer | Source |
|---|---|---|
| Which series? | `KXINXU` "S&P 500 above/below": one event per hour, 10am to 4pm New York, every trading day. We use the 4pm event, e.g. `KXINXU-26NOV05H1600`. `KXINX` "S&P 500 range" (daily 4pm) also exists; not needed. | `GET /series/KXINXU`, `GET /events?series_ticker=KXINXU` |
| What does a contract pay? | $1 if "the end-of-day S&P 500 index value ... is above 7744.9999", i.e. at or above 7745.00. | `rules_primary` field of each market |
| Strikes | 60-80 per 4pm event, **5 index points apart** (Nov 3: 7425-7720; Nov 4: 7375-7770). | `GET /markets?event_ticker=...` |
| Settlement value | Published per market as `expiration_value`: 7568.92 (Nov 3), 7688.62 (Nov 4). Both equal the S&P 500 close on Yahoo (`^GSPC`). So actual outcomes come free from Kalshi. | API + yfinance |
| Settlement source change | Kalshi: "Effective Friday, November 6, 2026, this event's source agency will change to S&P Global Inc." Same index, different feed. Worth watching for any mismatch. | `product_metadata` of the series |
| Trading hours | The next day's 4pm event opened at 4:16pm the previous afternoon (`open_time`), and closes at 4pm on the day. | market JSON |
| Liquidity | 264k contracts traded on the Nov 3 4pm event, 469k on Nov 4. | `volume_fp` summed over strikes |
| Spreads during the day | From hourly candles: at 11am, 13:00 and 3pm New York, 9-30 strikes were priced 5-95 cents with both a bid and an ask. **Median spread 1-3 cents, widest 5 cents.** Overnight (7pm): median 4 cents. | `GET /series/KXINXU/markets/{ticker}/candlesticks` |
| Historical prices? | **Yes.** 1-minute, hourly and daily candles of the YES bid and ask (open/high/low/close) and volume, plus individual trades, all public for recent markets. Markets settled before 2026-09-05 move to a `/historical` archive. Archived market details and settlement values load fine there, but my one archived candle request failed (**unverified** whether archived candles are available). | `/candlesticks`, `/markets/trades`, `/historical/cutoff`, `/historical/markets` |
| Do we need a key? | No. Every request above was an unauthenticated GET. | observed |
| Rate limits | Kalshi documents token budgets for logged-in accounts: Basic tier 200 read tokens per second, about 20 requests per second. Limits for requests without a key are not documented (**unverified**). A snapshot makes 2 requests. | docs.kalshi.com/getting_started/rate_limits |
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
| Quote quality | **Not yet measured.** At 7pm only 1 of 338 contracts had a bid, so cleaning kept nothing (expected after the close). | `scripts/snapshot.py` |
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

## Still to check (the first run during market hours)

1. How many same-day SPX quotes survive `clean_chain` (two-sided, spread under 50% of mid)?
2. Does SVI fit that smile well (RMSE in vol points), and do the fitted probabilities fall
   smoothly from 1 to 0 across Kalshi's strikes?
3. How delayed are the option quotes and the index level, measured?

If (1) and (2) look reasonable at midday, the project is fully feasible and Milestone 4 goes
ahead. If not, the fallback is SPY with a forward-ratio mapping.

## Sources
- Kalshi API (public, no key): https://api.elections.kalshi.com/trade-api/v2 (`/series`, `/events`, `/markets`, `/markets/{ticker}/orderbook`, `/series/{s}/markets/{t}/candlesticks`, `/markets/trades`, `/historical/*`, `/series/fee_changes`)
- Contract terms (linked from the series; not read yet, the market `rules_primary` text was used): https://assets.kalshi.com/contract_terms/INX.pdf
- Rate limits: https://docs.kalshi.com/getting_started/rate_limits
- Fee rounding: https://docs.kalshi.com/getting_started/fee_rounding
- Fee schedule (could not open, HTTP 429): https://kalshi.com/docs/kalshi-fee-schedule.pdf
- Secondary sources for the 0.07 rate: https://defirate.com/prediction-markets/fees/, https://whirligigbear.substack.com/p/makertaker-math-on-kalshi
