# Live Wiring Batch — Post-Batch Promotion List: Closing Report

Wires exactly the 3 items recommended in `docs/three_new_hypothesis_batch_
closing_report.md`'s promotion list, no more: GOLD_SILVER_RATIO_MR/1day
(watchlist) and PEAD's two representative configs, 3%/hold10 and 8%/hold10
(verified, permanent survivor-bias caveat). CARRY_MOMENTUM (confidently DIED)
and PEAD's other 4 SURVIVED-but-redundant configs are correctly NOT wired, per
the closing report's own recommendation.

## New replay paths (generalized machinery, no bespoke infrastructure)

- `nero_core/execution/replay.py`: `replay_gold_silver_ratio_events` (reuses
  `gold_silver_ratio_mr`'s own `evaluate_entry`/`size_entry`/`evaluate_exit`
  directly — much thinner than `replay_pairs_events`, which has to reimplement
  COINTEGRATION_PAIRS' own logic inline since that strategy has no equivalent
  self-contained functions to call) and `replay_pead_events` (event-driven;
  reuses `pead.py`'s own shared `_check_pead_exit`/`_try_open_pead_trade`
  helpers, extracted mid-build specifically so the live path can never
  silently diverge from the tested backtest logic — see the design note
  below).
- `nero_core/execution/live_scheduler.py`: `process_gold_silver_ratio` (mirrors
  `process_pairs`' own shape) and `process_pead_config` (one call per (ticker,
  config) — 14 total, `PEAD_CONFIGS`). `fetch_with_retry` gained an optional
  `retryable_exceptions` parameter (default unchanged:
  `(MarketDataUnavailableError,)`, so all 17 pre-existing callers are
  untouched) so PEAD's own `EarningsDataUnavailableError`/
  `StockDataUnavailableError` get the same retry/backoff treatment every other
  config already has.

## A real design fix caught mid-build

While wiring `replay_pead_events`, I initially duplicated PEAD's own entry-
sizing and exit-check logic inline (matching `replay_pairs_events`'s own
established precedent of reimplementing rather than reusing). Given how much
financial-calculation logic that represented, I stopped and refactored
`nero_core/strategies/pead.py` instead: extracted `_check_pead_exit` and
`_try_open_pead_trade` as shared, tested helper functions that BOTH
`run_pead_backtest_rows` (the backtest path) and `replay_pead_events` (the
live path) now call — eliminating the duplication risk entirely rather than
accepting it. Proven with a direct equivalence test (`tests/
test_live_wiring_post_batch.py`): `replay_pead_events` and
`run_pead_backtest_rows` produce byte-identical exit events on the same data.

## Wiring checks, all confirmed

- **PEAD NO_SIGNAL on a no-earnings period**: confirmed directly —
  `replay_pead_events` returns `[]` gracefully (not an error) when no
  qualifying event exists in the window. No ledger row is written on an
  ordinary non-event day (by design — see that function's own docstring for
  why this differs from candle-driven strategies' per-candle NO_TRADE
  convention).
- **GOLD_SILVER_RATIO_MR pairs-leg accounting**: confirmed directly — every
  ENTRY event's reasoning records BOTH legs' own direction (one LONG, one
  SHORT) and price; the standard SHORT P&L convention
  (`apply_slippage`/inverted `gross_pnl`) already established elsewhere in
  this project handles the SHORT leg correctly, not new code.
- **strategy_version uniqueness**: confirmed directly — all 14 PEAD
  (ticker, strategy_version) pairs are unique; `verification_status_for`'s
  RMR-batch collision fix (keyed by `(strategy_id, strategy_version, asset)`)
  correctly keeps PEAD's 2 configs on the same ticker independently resolvable
  even though they currently carry the same wording.
- **Vendor-timestamp join fix in the live path**: confirmed directly —
  `process_gold_silver_ratio` calls `align_gold_silver_candles` (the same
  calendar-date join committed with the strategy itself), never a raw
  `close_time` join.
- **t+1 execution rule in the live path**: confirmed directly — a dedicated
  test forces an announcement onto a specific candle and asserts the resulting
  ENTRY event's `candle_close_time` is the FOLLOWING candle, not the
  announcement's own.
- **lxml in the CI runner**: `requirements.txt` already lists `lxml` (added in
  the research batch) and `.github/workflows/live_scheduler.yml`'s own
  `pip install -r requirements.txt` step installs it — confirmed by reading
  both files directly, no `pyproject.toml` exists to also update.

## A real production-ledger lesson (caught before it mattered)

A real-data smoke test of both new live paths (confirming they work against
actual Twelve Data/yfinance responses, not just mocks) initially ran against
the DEFAULT (production) Truth Ledger path and inserted one real row under a
fake `run_id`. Caught immediately, the row was deleted and the ledger file
reverted to its last-committed state before anything was staged — no
contamination reached a commit.

## Test count

**1224 tests, all passing** (was 1209 before this batch: +15 new
`tests/test_live_wiring_post_batch.py` tests). Full suite runtime: ~70s.

A missing PEAD test fixture initially triggered the exact real-`time.sleep`
contamination bug this project has now hit three times (RMR batch, CARRY_
MOMENTUM/PEAD research batch, and now here) — 14 PEAD configs each retrying
3x with real 1+3+10s backoff ballooned one test run to 287s and made another
appear to hang entirely. Fixed the same way each time: mock the missing
fetcher, and pass `sleep_fn=lambda s: None` at every call site that doesn't
already override it.

## Updated live roster

**31 configs live** (was 29 before this batch — SINGLE_ASSET_CONFIGS(11) +
COINTEGRATION_PAIRS(1) + ORDERFLOW_IMBALANCE(2) + NEWS_SENTIMENT(2) +
GOLD_SILVER_RATIO_MR(1) + PEAD(14) = 31):

- **Verified: 17** (was 3) — BREAKOUT_MOMENTUM/GOLD (triple-verified),
  TREND_PULLBACK/BNB, COINTEGRATION_PAIRS/BTC-ETH, plus **14 new PEAD
  configs** (7 tickers x 2 configs), each carrying the permanent survivor-bias
  caveat string.
- **Watchlist (promising, not verified): 10** (was 9) — 5 SILVER Phase A + 4
  RMR + **1 new GOLD_SILVER_RATIO_MR/1day**.
- **Experimental / forward-test-only (no backtest exists at all): 4**
  (unchanged) — NEWS_SENTIMENT x2, ORDERFLOW_IMBALANCE x2.

### Every config, with its status string

| # | Strategy | Asset | Status |
|---|---|---|---|
| 1 | BREAKOUT_MOMENTUM (v1.2.0-gold-1week) | GOLD | triple-verified |
| 2 | TREND_PULLBACK (v1.0.0) | BNB | verified — sample-limited |
| 3 | COINTEGRATION_PAIRS (v1.0.0) | BTC-ETH | verified — weakest, live-proving |
| 4-8 | BREAKOUT_MOMENTUM/TREND_PULLBACK/VOLATILITY_SQUEEZE x3 (silver-calibrated-24h) | SILVER | promising-watchlist — forward-testing, not verified |
| 9-12 | RANGE_MEAN_REVERSION (v1.0.0 x2, v1.1.0-long-only, v1.3.0-confirmation) | GOLD/SILVER/BTC/BTC | watchlist — forward-testing, not verified (config-specific detail) |
| 13 | NEWS_SENTIMENT (v1.0.0) | GOLD | forward-test-only, no historical backtest |
| 14 | NEWS_SENTIMENT (v1.0.0) | BTC | forward-test-only, no historical backtest |
| 15 | ORDERFLOW_IMBALANCE (v1.0.0) | BTC | experimental — snapshot-based, forward-testing only, no backtest exists |
| 16 | ORDERFLOW_IMBALANCE (v1.0.0) | ETH | experimental — snapshot-based, forward-testing only, no backtest exists |
| **17** | **GOLD_SILVER_RATIO_MR (v1.0.0)** | **GOLD-SILVER** | **watchlist — forward-testing, not verified (positive both halves, edge-over-random positive 3/4 configs; pairs-aware stop; vendor-timestamp fix applied; 1day grid-shift structurally unavailable)** |
| **18-24** | **PEAD (surprise3pct-hold10)** | **AAPL, MSFT, GOOGL, TSLA, AMZN, NVDA, META** | **verified — survivor-bias caveat: tested on 7 large successful companies only; CI entirely positive; edge-over-random +0.35 to +0.60; real-world performance may differ** |
| **25-31** | **PEAD (surprise8pct-hold10)** | **AAPL, MSFT, GOOGL, TSLA, AMZN, NVDA, META** | **verified — survivor-bias caveat: tested on 7 large successful companies only; CI entirely positive; edge-over-random +0.35 to +0.60; real-world performance may differ** |

## Not wired (by instruction)

- CARRY_MOMENTUM (both timeframes) — confidently DIED, no paper-tracking
  value.
- PEAD's other 4 SURVIVED configs (3%/hold5, 5%/hold5, 5%/hold10, 8%/hold5) —
  redundant coverage of the same signal, per the research batch's own
  recommendation.
