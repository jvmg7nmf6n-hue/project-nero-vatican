# MACRO_RISK_ON (macro-risk-on-v1.0.0) — Report

## Data design

- **Dollar leg**: cascaded Twelve Data UUP → DXY → inverted EUR/USD. Live run used
  **UUP** (Invesco DB US Dollar Bullish Fund daily close) — DXY is not a valid Twelve
  Data symbol (confirmed by a direct API call: `symbol or figi parameter is missing or
  invalid`), so DXY exists only as a documented fallback branch, untested against a live
  response. EUR/USD (inverted via reciprocal, `1/close`) was verified live to also work
  as a fallback. Sign convention verified: UUP is designed to move WITH the dollar
  (falling UUP = weakening dollar, no inversion needed); the EUR/USD fallback is
  inverted specifically because EUR/USD itself rises when the dollar weakens — the
  reciprocal keeps "falling = weakening" true in every branch.
- **Real-yield leg**: FRED DFII10 (10Y TIPS real yield). `FRED_API_KEY` was present in
  `.env` (verified via presence/length check only — value never printed or logged), so
  this leg was built. Treasury publishes each business day's real yield the next
  business day; a **t+2** execution buffer is applied (that 1-day reporting lag plus
  the same 1-day closed-candle buffer used for the dollar leg).
- **Alignment**: `nero_core/data_sources/macro_data.py::align_macro_to_daily_candles`
  forward-fills each leg's lagged value onto the daily candle grid via
  `pd.merge_asof(..., direction="backward")` — proven by
  `tests/test_macro_data.py::test_saturday_candle_sees_fridays_value_not_mondays` to
  carry Friday's value across Saturday/Sunday rather than reaching forward to Monday's.
  A separate test proves a candle before any macro history exists gets `NaN`, never a
  back-filled future value.
- **Change computation**: `compute_lagged_change` computes the 20-day change
  (`value[d] - value[d - 20]`) on each series' own native business-day index first,
  then shifts the result by the leg's lag (1 for dollar, 2 for DFII10) — still on the
  native business-day index — before any forward-fill onto the calendar grid. Verified
  by hand-computed values in `tests/test_macro_data.py::ComputeLaggedChangeTest`.
- **Caching**: both series are cached to `data/macro_cache/*.csv` (gitignored) after a
  successful live fetch; a cache hit skips the live fetch (and does not require an API
  key at all — verified by test).

## Strategy

`nero_core/strategies/macro_risk_on.py` — DAILY timeframe only. Entry: `risk_on` true
(both legs' 20-day change negative, each already lag-adjusted) and no open trade. Exit:
2.0x-ATR(14) stop (checked first) or the regime turning off, whichever comes first — no
fixed target, no max-holding cap (documented registry-level decision, matching
DONCHIAN_TREND's precedent: a regime-follower's premise is staying in as long as the
regime holds). Standard 1% fixed-fractional sizing. Registered as
`MACRO_RISK_ON` / `macro-risk-on-v1.0.0`. 23 tests cover parameter shape (no
max-holding/target fields), entry/exit paths (including stop-takes-priority-over-
regime-off on the same candle), sizing, and registry versioning.

## Sweep methodology

Full available daily history for BTC (Binance) and GOLD (Twelve Data XAU/USD), 70/30
chronological split. Matching every other split tool in this codebase (see
`tools/backtest_train_test_split.py`'s "no information crosses the boundary" rule): the
TRAIN half's regime is built using only macro data up to train's own last date, and the
TEST half's regime is built using only macro data from test's own first date onward —
the test half's 20-day-change warmup restarts from scratch, using none of train's macro
history, even though a live system would legitimately have had continuous access to it.

## Results

| Asset | Split | Candles | % days risk-on | Trades | Win% | ExpR | PF | MaxDD | Flag |
|---|---|---|---|---|---|---|---|---|---|
| BTC | FULL | 3256 | 28.6% | 126 | 44.4% | 0.091 | 1.27 | -12.0% | |
| BTC | TRAIN | 2279 | 25.6% | 86 | 46.5% | 0.191 | 1.73 | -7.1% | |
| BTC | TEST | 977 | 33.7% | 39 | 38.5% | -0.140 | 0.63 | -7.8% | |
| GOLD | FULL | 5000 | 29.6% | 264 | 42.8% | -0.000 | 0.99 | -11.8% | |
| GOLD | TRAIN | 3500 | 29.9% | 202 | 41.1% | -0.019 | 0.92 | -11.8% | |
| GOLD | TEST | 1500 | 27.9% | 62 | 48.4% | 0.018 | 1.05 | -5.2% | |

No cell fell below the 20-trade minimum in this run — daily-timeframe full-history data
gave enough sample size that the LOW-SAMPLE flag this strategy family was expected to
trip did not fire here.

**Strict filter (positive expectancy in both train and test, ≥20 trades each): BTC
fails (train +0.191, test -0.140 — flips negative). GOLD fails (train -0.019, test
+0.018 — flips positive, but train itself is negative). Neither asset passes.**
