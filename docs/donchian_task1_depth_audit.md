# Donchian Cross-Asset Deep-Dive, Task 1 — Data Depth Audit

Data-availability check only, no strategy/backtest code. Confirms maximum available
history per asset before the Task 2 sweep, and flags one real gap between "what this
project's existing helpers return by default" and "what's actually available."

## Stocks (yfinance, native 1week + 1day)

| Symbol | Timeframe | Candles | Start | End |
|---|---|---|---|---|
| SPY | 1week | 1,747 | 1993-02-01 | 2026-07-20 |
| SPY | 1day | 8,424 | 1993-01-30 | 2026-07-21 |
| QQQ | 1week | 1,428 | 1999-03-15 | 2026-07-20 |
| QQQ | 1day | 6,882 | 1999-03-11 | 2026-07-21 |
| AAPL | 1week | 2,380 | 1980-12-15 | 2026-07-20 |
| AAPL | 1day | 11,491 | 1980-12-13 | 2026-07-21 |
| MSFT | 1week | 2,106 | 1986-03-17 | 2026-07-20 |
| MSFT | 1day | 10,165 | 1986-03-14 | 2026-07-21 |
| GOOGL | 1week | 1,144 | 2004-08-23 | 2026-07-20 |
| GOOGL | 1day | 5,513 | 2004-08-20 | 2026-07-21 |

SPY confirms the expected ~33 years (1993 inception). All five comfortably clear
the 20+-year target except QQQ (~27yr) and GOOGL (~22yr, both still well above it).

## Forex (Twelve Data, native 1week)

| Pair | Candles | Start | End |
|---|---|---|---|
| EUR/USD | 2,202 | 1974-12-30 | 2026-07-20 |
| USD/JPY | 2,898 | 1971-01-04 | 2026-07-20 |
| GBP/USD | 2,899 | 1971-01-04 | 2026-07-20 |
| USD/CHF | 2,899 | 1971-01-04 | 2026-07-20 |

All four pairs exceed 50 years of weekly history. USD/JPY (the strongest performer
in prior batches) has full depth back to 1971 — no shortfall here.

## Metals (Twelve Data / yfinance, weekly)

**GOLD — a real gap found and worked around.** This project's existing
`tools.timeframe_data.fetch_timeframe_candles` helper hardcodes
`NATIVE_INTERVAL_CANDLES["1week"] = 2_000`, an artificial cap unrelated to any
vendor limit. Fetched through that helper, GOLD 1week returns only 2,000 candles
starting **1988-03-28**. Querying Twelve Data's `XAU/USD` endpoint **directly**
with `outputsize=5000` (the vendor's own real cap) returns the TRUE depth:
**2,949 candles, 1970-01-05 → 2026-07-20** — confirming the ~56-year depth this
task expected, and recovering 19 additional years (1970–1988) the capped helper
would have silently discarded. **Task 2's sweep will fetch GOLD weekly via a
direct Twelve Data call, not the capped helper**, to honor this batch's own
"maximum available history, not capped" instruction. This project's shared
`tools/timeframe_data.py` constant was NOT modified — it's used elsewhere for
other timeframes/purposes, and changing a shared cap as a side effect of this
research task would be out of scope; only this batch's own sweep tool bypasses it
for the weekly-GOLD case.

**SILVER**: 1,351 candles (yfinance `SI=F`, continuous futures proxy — not spot),
2000-08-28/09-04 → 2026-07-20 (the ±1 candle difference between two fetch
attempts is an unclosed-current-week trim, not a discrepancy). Independently
confirmed directly against yfinance (`period="max", interval="1wk"`) — this is
SILVER's genuine maximum depth via this source, no artificial cap found. ~26
years, comfortably above the 20-year target but far short of GOLD's 56.

One Twelve Data `429 Too Many Requests` was hit on the first GOLD attempt (this
session's cumulative API usage across today's batches) — resolved on a single
retry moments later; not a depth or data-quality issue.

## Crypto (Binance, comparison baseline)

| Asset | Timeframe | Candles | Start | End |
|---|---|---|---|---|
| BTC | 24h | 3,260 | 2017-08-17 | 2026-07-20 |
| BTC | 1week | 466 | 2017-08-20 | 2026-07-19 |
| ETH | 24h | 3,260 | 2017-08-17 | 2026-07-20 |
| ETH | 1week | 466 | 2017-08-20 | 2026-07-19 |

~9 years daily, ~9 years / 466 candles weekly — as expected, far shorter than
every other asset class here. Included strictly as the comparison baseline the
task specifies, not expected to match stocks/forex/metals' sample-size advantage.

## Summary for Task 2

Every Priority Tier asset clears the "adequate for a 70/30 split with N up to 40
weeks" bar with room to spare — forex and GOLD in particular offer 50+ years,
making them the best candidates to finally break DONCHIAN_TREND's persistent
sample-size ceiling. GOLD weekly will be fetched via a direct, uncapped Twelve
Data call in Task 2 to use its full confirmed depth.
