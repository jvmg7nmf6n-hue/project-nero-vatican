# PSX Strategy Sweep, Task 1 — Data Pipeline + Corporate-Action Guard

Builds `nero_core/data_sources/psx_data.py`, the data pipeline for Vatican's first
PSX (Pakistan Stock Exchange) research batch, directly on the findings of
`docs/psx_data_audit.md` (YELLOW verdict). No strategy or backtest logic in this
task — data pipeline and its tests only.

## What was built

- **`fetch_psx_stock_ohlcv(symbol)`** — daily OHLCV for OGDC, LUCK, HBL (and MARI,
  which the guard below halts) via yfinance's `.KA` suffix, reusing
  `nero_core.data_sources.stock_data.fetch_stock_ohlcv` unchanged. An unknown symbol
  raises `ValueError` — no suffix-guessing, matching `stock_data.py`'s own ticker-
  resolution discipline.
- **`fetch_kse100_daily(start_year, end_year)`** — KSE-100 index daily OHLCV via
  PSX's own `dps.psx.com.pk/historical` portal endpoint (symbol `"KSE100"`, no
  hyphen — confirmed in the audit). This is the only source with index-level
  history; yfinance has none. Parses the endpoint's HTML table with
  `pandas.read_html` (already available via the existing `lxml` dependency — no new
  dependency added). Raises `StockDataUnavailableError` if the entire requested
  range returns zero rows.
- **Corporate-action guard** — `detect_corporate_action_breaks(prices,
  threshold_pct=40.0)` flags any close-to-close move exceeding 40% in either
  direction. `fetch_psx_stock_ohlcv` runs this automatically on every fetch and
  raises `PsxCorporateActionSuspectedError` (halting, not returning, that ticker's
  data) if a break is found — directly protecting against the exact failure mode
  the audit confirmed in MARI (an unadjusted ~8:1 split cliff in Sept 2024, present
  in both the raw DPS data and yfinance's own `Adj Close`). OGDC/LUCK/HBL were
  confirmed clean of this in the audit; the guard exists so any future ticker
  addition (MARI, ENGRO/ENGROH, or a broader Phase 2 universe) can't silently slip
  corrupted data into a backtest.
- **Macro proxies** — `fetch_usd_pkr_daily()` (yfinance `"PKR=X"`, confirmed 2002–
  present) and `fetch_oil_price_daily()` (yfinance `"CL=F"`, confirmed 2000–present),
  both cached to `data/macro_cache/` exactly like the existing dollar-proxy/DFII10
  pattern in `nero_core.data_sources.macro_data`.
- **`fetch_sbp_policy_rate()`** — always raises `PsxMacroDataUnavailableError`,
  documented, not silently stubbed. Checked directly during this batch: FRED's
  Pakistan discount-rate series is annual frequency with its last observation in
  2017, and was itself superseded by the State Bank of Pakistan's own Policy Rate
  regime in May 2015 — a 9-years-stale annual series is unusable for any daily-bar
  signal. SBP's own website publishes rate decisions as PDF/HTML press releases,
  not a machine-readable feed, so no scrape target exists either. Per the task's
  own documented fallback, PSX macro research proceeds with **USD/PKR as the sole
  macro proxy**.
- **`build_psx_regime_frame_oil_and_currency`** / **`build_psx_regime_frame_currency_only`**
  — construct the Pakistan-adapted MACRO_RISK_ON regime frame (used in Task 2): for
  OGDC, `risk_on = (USD/PKR rising) AND (oil rising)`; for LUCK/HBL, `risk_on =
  (USD/PKR rising)` alone. Both reuse `macro_data.compute_lagged_change` /
  `align_macro_to_daily_candles` unchanged (20-day change on each series' own
  native business-day index, t+1 lag, forward-fill onto the candle grid — identical
  discipline to the original dollar/DFII10 regime). The output columns are
  deliberately named `dollar_change_20d`/`dfii10_change_20d` (documented in the
  docstring) so the frame plugs directly into `nero_core.strategies.macro_risk_on`'s
  **unmodified** `add_indicators`/`run_macro_risk_on_backtest` — no changes to that
  strategy file were needed or made.

## Currency

PKR (Pakistani Rupee) confirmed for every PSX instrument — there is no USD-quoted
alternative on this exchange. This module returns raw PKR prices, unconverted.
Documented explicitly (module docstring) for future users: Vatican's strategies
score and size trades in R-multiples (`net_pnl / risk_dollars`), a dimensionless,
risk-normalized ratio that is identical regardless of the underlying currency —
nothing about R-multiple accounting requires a common currency across assets. A
cross-asset USD-denominated equity curve mixing PSX with crypto/GOLD positions is a
different, out-of-scope question not addressed here.

## Tests

`tests/test_psx_data.py` — 16 tests, all passing:
- Corporate-action detection: clean data produces no flags; a synthetic MARI-shaped
  ~8:1 cliff fires; a move exactly at the 40% threshold does not fire (strictly
  greater-than); empty/single-row frames produce no flags.
- `fetch_psx_stock_ohlcv`: unknown symbol raises `ValueError`; a clean mocked series
  passes through untouched; an injected corporate-action break raises
  `PsxCorporateActionSuspectedError` rather than returning the corrupted series.
- `fetch_kse100_daily`: parses a real-shaped DPS HTML table into the standard candle
  columns; a zero-row range raises `StockDataUnavailableError`.
- Macro proxies: cached USD/PKR returned without a network call; a native oil fetch
  writes the cache; `fetch_sbp_policy_rate` always raises with the documented
  reason; a graceful-fallback pattern (SBP fails -> USD/PKR alone) works end to end.
- Regime frames: OGDC's regime requires both legs positive (false when oil is
  falling even with PKR weakening); the currency-only regime tracks USD/PKR alone
  with its unused second leg fixed at a neutral 0.0, never NaN.

No synthetic/fabricated OHLCV was ever returned by `fetch_psx_stock_ohlcv` or
`fetch_kse100_daily` themselves — only the corporate-action and macro-proxy tests
above use synthetic fixtures, and only to exercise the guard/fallback logic itself.
