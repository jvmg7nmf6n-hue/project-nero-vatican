# Live Wiring Batch — Donchian Cross-Asset Deep-Dive: Closing Roster

Wires exactly the 4 configs recommended in `docs/donchian_deep_dive_closing_report.md`'s
promotion list, no more: GOLD/1week/N20, EUR/USD/1week/N20, GBP/USD/1week/N20,
USD/JPY/1week/N40 — all watchlist forward-tests, none a survivor. Vatican never
places real orders; every one of these writes paper signals to the Truth Ledger only.

## What was wired

- **GOLD/1week/N20** — added to `SINGLE_ASSET_CONFIGS`, fetched via the standard
  `fetch_timeframe_candles`/`MarketDataClient` path (same as every other GOLD
  config already live).
- **EUR/USD, GBP/USD/1week/N20, USD/JPY/1week/N40** — `MarketDataClient` has no
  forex routing at all, so these 3 get their own `DONCHIAN_FOREX_CONFIGS` list and
  `process_donchian_forex_config` function (structurally the same shape as
  `PEAD_CONFIGS`/`process_pead_config`), fetching via
  `nero_core.data_sources.forex_data.fetch_forex_ohlcv`. Both paths converge on the
  same generic `replay_single_asset_events` — no strategy-specific replay logic was
  written.
- **`nero_core/strategies/donchian_bracket_live_configs.py`** — 4 new registered
  `STRATEGY_VERSION`s under `STRATEGY_ID="DONCHIAN_TREND"`
  (`donchian-trend-v2.0.0-bracket-{gold,eurusd,gbpusd,usdjpy}-n{20,20,20,40}-1week`),
  each built via `build_parameters_for_n` with the exact fee/slippage values the
  backtest itself used (metals 10bps, forex 5bps).
- **4 new `VARIANT_SPECS` entries** in `tools/backtest_compare.py`, each with
  `evaluate_exit_fn=donchian_bracket_evaluate_exit` explicitly set and
  `direction_aware_sizing=False` (Donchian infers LONG/SHORT internally from
  proximity to the N-period high/low, unlike RANGE_MEAN_REVERSION's external
  4-arg direction parameter) — see the wiring checks below for why the
  `evaluate_exit_fn` override specifically is mandatory, not optional.
- **`verification_status.py`** — 4 new entries, exact wording as specified.
- **`export_site_data.py`** — `DONCHIAN_FOREX_CONFIGS` imported and added to both
  `_trading_roster_keys()` and `_roster_entries()` (GOLD flows in automatically via
  `SINGLE_ASSET_CONFIGS`, no export-side change needed for it).

## Wiring checks, all confirmed

- **N-period lookback, closed-candle-only**: confirmed through the actual live
  replay path (not just `donchian_breakout_bracket.py`'s own unit tests) — a
  breakout candle's own high never counts toward its own threshold
  (`tests/test_live_wiring_donchian_deep_dive.py::NPeriodLookbackNoLookaheadTest`).
- **Holding caps per N, not a generic default**: N20 configs carry 30-week
  (5,040h) caps, the N40 config carries a 52-week (8,736h) cap — confirmed both as
  a direct params check and behaviorally, via a live-replayed position that
  correctly TIME-exits at its own 30-week cap
  (`HoldingCapPerNTest`).
- **SHORT signals genuinely generated, not silently dropped**: a breakdown candle
  produces a real SHORT `ReplayEvent` through the full live path, with entry
  slippage in the correct ("sell to open") direction and stop-above/target-below
  geometry (`ShortSignalNotSilentlyDroppedTest`). Separately confirmed that all 4
  `VariantSpec` entries explicitly override `evaluate_exit_fn` to
  `donchian_bracket_evaluate_exit` — leaving any one at the long-only default would
  have compiled and run without error (both OpenTrade shapes carry a `.target`
  field) while silently applying the wrong stop/target logic to that config's
  SHORT trades, the exact "runs without error but wrong" failure class flagged in
  `docs/live_wiring_batch_rmr_watchlist_deferral.md`.
- **`strategy_version` uniqueness**: all 4 `(strategy_id, strategy_version, asset)`
  keys are unique against each other AND against the entire pre-existing live
  roster (`StrategyVersionUniquenessAcrossFullRosterTest`) — no collision risk,
  since both `strategy_version` and `asset` differ per config (unlike RMR's
  same-asset-different-version case that originally motivated the
  `verification_status.py` keying fix).
- **Weekly boundary convention (metals vs. forex)**: GOLD and all 3 forex pairs
  share the identical `candle_boundary_due("1week", ...)` gate and constant. One
  real, honest correction to this task's own framing: checked directly (not
  assumed) — both GOLD's and EUR/USD's actual Twelve Data `1week` candles close at
  **Monday 00:00 UTC**, not Friday. This does not affect correctness (GOLD's
  existing live config has run on this exact convention since it was first wired,
  and `candle_boundary_due` is documented as a deliberately cheap, generous
  pre-filter — the real correctness guarantee is the downstream
  `already_logged_close_time_ms` comparison, which is timezone/weekday-agnostic).
  The 3 new forex configs inherit precisely the same behavior as GOLD's
  already-running config, not a new or different one — no code change was made to
  `candle_schedule.py`, since that's a pre-existing, shared, already-accepted
  property of every 1week config, not something introduced by this batch.

## A real production-ledger discipline followed

A real-data smoke test of both new live paths (GOLD via `MarketDataClient`, all 3
forex pairs via `fetch_forex_ohlcv`) ran against a **temporary** SQLite file, never
the default production Truth Ledger path — all 4 configs evaluated cleanly against
real current market data (3 correctly returned `NO_BREAKOUT`/`NO_TRADE`; USD/JPY's
N40 config genuinely opened a real ENTRY on the actual current breakout), and the
temp file was deleted afterward. No row was ever written to the real ledger during
testing.

## Test suite regressions found and fixed (pre-existing tests, not new bugs)

Adding a 3rd GOLD config and 4 new roster entries broke 6 pre-existing hardcoded
counts in `tests/test_export_site_data.py` and `tests/test_live_scheduler.py`
(roster order, `assets_skipped` count, GOLD strategy-version count, GOLD error
count, GOLD retry call count) — all legitimate updates to reflect the real new
roster shape, not bugs in the new wiring. `tests/test_live_scheduler.py` also
needed a new `fetch_forex_ohlcv` test fixture (mirroring the existing
`load_intraday`/`load_daily`/PEAD fixture pattern) so the general scheduler tests
don't make real network calls for the 3 new forex configs.

## Test count

**1,289 tests, all passing** (was 1266 before this batch: +23 new — 7
`tests/test_donchian_bracket_live_configs.py` + 16
`tests/test_live_wiring_donchian_deep_dive.py`).

## Full live roster (35 entries)

| Bucket | Count | Configs |
|---|---|---|
| triple-verified | 1 | BREAKOUT_MOMENTUM/GOLD |
| verified | 16 | TREND_PULLBACK/BNB, COINTEGRATION_PAIRS/BTC-ETH, PEAD (14: 7 tickers x 2 configs) |
| **watchlist** | **9** | RANGE_MEAN_REVERSION x4 (GOLD, SILVER, BTC long-only, BTC confirmation), GOLD_SILVER_RATIO_MR/GOLD-SILVER, **DONCHIAN_TREND x4 (GOLD/N20, EUR/USD/N20, GBP/USD/N20, USD/JPY/N40)** |
| promising-watchlist | 5 | SILVER x5 (BREAKOUT_MOMENTUM, TREND_PULLBACK, VOLATILITY_SQUEEZE x3) |
| forward-test-only | 2 | NEWS_SENTIMENT (GOLD, BTC) |
| experimental | 2 | ORDERFLOW_IMBALANCE (BTC, ETH) |

**N20 cross-asset pattern, confirmed visible in the live roster**: 3 of the 4 new
DONCHIAN_TREND entries — GOLD, EUR/USD, and GBP/USD — all run the SAME N20 preset
(20-candle channel, 30-week holding cap), exactly the pattern
`docs/donchian_deep_dive_closing_report.md` flagged as a genuine cross-asset
signal rather than an asset-specific fluke. USD/JPY runs N40 (structural), the
one config in this batch on a different preset.

### Every DONCHIAN_TREND config, with its status string

| Asset | N | Strategy version | Status |
|---|---|---|---|
| GOLD | 20 | donchian-trend-v2.0.0-bracket-gold-n20-1week | watchlist — CI clears zero both halves, adequate sample, breakout-timing edge confirmed vs random baseline; grid-shift structurally unavailable at 1week (settlement gaps) — this is the ceiling, not a data shortfall |
| EUR/USD | 20 | donchian-trend-v2.0.0-bracket-eurusd-n20-1week | watchlist — positive both halves, N20 cross-asset pattern confirmed; grid-shift structurally unavailable at 1week |
| GBP/USD | 20 | donchian-trend-v2.0.0-bracket-gbpusd-n20-1week | watchlist — positive both halves, N20 cross-asset pattern confirmed; grid-shift structurally unavailable at 1week |
| USD/JPY | 40 | donchian-trend-v2.0.0-bracket-usdjpy-n40-1week | watchlist — positive both halves, structural-trend parameter; grid-shift structurally unavailable at 1week |

None of the 4 is presented as a proven edge anywhere in code, docs, or exported
site data — every status string above carries its own caveat, matching this
project's permanent verification-status discipline.
