# FUNDING_EXTREME — Data Source, Strategy, and Verification Report

## Data source

`nero_core/data_sources/funding_data.py` fetches historical Binance USDT-perp funding
rate settlements (`fapi/v1/fundingRate`, no API key needed) for BTC, ETH, SOL, BNB,
caches to disk (`data/funding_cache/<ASSET>_funding.csv`, same convention as
`nero_core.data_sources.macro_data`), and stores each settlement's exact UTC timestamp
verbatim as `settlement_time` (epoch ms) — never derived or rounded.

### History depth (live, per asset)

| Asset | Settlements | Range | Span |
|---|---|---|---|
| BTC | 7,508 | 2019-09-10 to 2026-07-17 | ~2,502 days |
| ETH | 7,274 | 2019-11-27 to 2026-07-17 | ~2,424 days |
| SOL | 6,475 | 2020-09-13 to 2026-07-17 | ~2,133 days |
| BNB | 7,049 | 2020-02-10 to 2026-07-17 | ~2,349 days |

## Two real bugs caught and fixed before reporting

Both were caught by actually running the tool against live data rather than trusting
the first output — consistent with this project's standing practice of verifying
against real feeds before reporting.

1. **Full-history fetch was silently truncated to ~166 days.** The first live run
   returned exactly 500 settlements per asset, all from the same recent ~166-day
   window, regardless of the requested page count. Root cause: Binance's
   `fapi/v1/fundingRate` endpoint returns only its most-recent ~500-record window when
   `startTime` is omitted (or sent as `0`) — verified empirically (`startTime=0` and
   no `startTime` both produced the same truncated recent window; an explicit real date
   like `2024-01-01` correctly returned data from that date forward). Fixed by always
   sending an explicit `startTime` — a `FUNDING_HISTORY_GENESIS_MS` constant
   (2019-01-01 UTC, predating every supported symbol's listing) on the first page, then
   paginating forward from each page's last settlement. Guarded by
   `StartTimeAlwaysSentRegressionTest` in `tests/test_funding_data.py`.
2. **The 8h candle-to-settlement join matched zero rows.** The first full sweep run
   showed exactly 0 trades on every single 8h config across all 4 assets — a strong
   enough anomaly (given 2,000+ days of history) to investigate rather than report.
   Root cause: Binance kline `close_time` is `period_end - 1ms` (not the boundary
   itself), while `fundingTime` carries its own few-millisecond exchange jitter, so an
   exact-integer-equality join between the two never matches. Fixed by switching to a
   `pd.merge_asof(..., direction="nearest", tolerance=60_000)` join — a tolerance
   (1 minute) far smaller than the 8h gap between settlements, so there is no risk of
   matching the wrong period. Guarded by a regression test reproducing the exact -1ms
   offset in `tests/test_funding_extreme.py`.

A third, smaller cache-read bug (mixed fractional-second precision in round-tripped CSV
timestamps breaking a single-format `pd.to_datetime` parse) was also caught and fixed
(`format="ISO8601"`), with its own regression test.

## Strategy: FUNDING_EXTREME v1.0.0

Contrarian, long-only, regime-style (see `nero_core/strategies/funding_extreme.py` for
full documentation of every lookahead-safety rule):

- **Entry**: LONG when the just-settled funding rate is negative AND at or below the
  trailing 90-calendar-day 10th percentile of its own funding distribution (crowded
  shorts). The trailing window is `closed="left"` (excludes the current settlement from
  its own distribution) and every value is shifted forward one row before use (signals
  act on the NEXT candle, t+1).
- **Exit**: funding rises back above the trailing 90-day median, OR a 2.0x ATR(14)
  disaster stop is hit. No fixed profit target, no max-holding-hours cap — both fields
  are absent from `FundingExtremeParameters` by design, not defaulted to "unlimited."
- **Timeframes**: 8h candles resampled from native 1h onto the 00:00/08:00/16:00 UTC
  settlement grid (`resample_hourly_to_grid`, the same volume-sum-verified grid-shift
  utility used elsewhere in this project), and native 24h daily candles (which use only
  each day's LAST — 16:00 UTC — settlement).
- Standard 1% risk-per-trade sizing, 10bps/2bps fee/slippage — identical to every other
  strategy in this codebase.

## Results (live data, 70/30 chronological split, upgraded harness)

| Asset/TF | Split | N | ExpR | Bootstrap 95% CI | Random baseline edge |
|---|---|---|---|---|---|
| BTC/8h | Train | 69 | 0.190 | [-0.050, 0.448] crosses zero | +0.148 |
| BTC/8h | Test | 72 | -0.083 | [-0.239, 0.080] crosses zero | +0.027 |
| BTC/24h | Train | 38 | 0.256 | [-0.060, 0.592] crosses zero | -0.067 |
| BTC/24h | Test | 24 | -0.034 | [-0.331, 0.276] crosses zero | +0.030 |
| ETH/8h | Train | 67 | 0.209 | [-0.052, 0.497] crosses zero | +0.144 |
| ETH/8h | Test | 74 | **-0.191** | **[-0.339, -0.041] clears zero (negative)** | -0.061 |
| ETH/24h | Train | 38 | 0.227 | [-0.068, 0.548] crosses zero | +0.071 |
| ETH/24h | Test | 38 | 0.148 | [-0.091, 0.416] crosses zero | +0.159 |
| SOL/8h | Train | 94 | 0.032 | [-0.214, 0.312] crosses zero | +0.006 |
| SOL/8h | Test | 82 | **-0.194** | **[-0.336, -0.050] clears zero (negative)** | -0.112 |
| SOL/24h | Train | 40 | 0.174 | [-0.186, 0.612] crosses zero | +0.124 |
| SOL/24h | Test | 38 | **-0.160** | **[-0.316, -0.012] clears zero (negative)** | -0.100 |
| BNB/8h | Train | 67 | **0.400** | **[0.009, 0.829] clears zero (positive)** | **+0.325** |
| BNB/8h | Test | 12 *LOW SAMPLE* | 0.042 | [-0.769, 1.129] crosses zero | +0.169 |
| BNB/24h | Train | 32 | 0.006 | [-0.374, 0.434] crosses zero | +0.066 |
| BNB/24h | Test | 13 *LOW SAMPLE* | 0.117 | [-0.458, 0.707] crosses zero | +0.078 |

## Factual read

**No asset/timeframe combination clears the bar this project's other strategies were
held to** (positive expectancy, CI clear of zero, on BOTH halves). Specifically:

- **Every train half looks reasonably positive** (ExpR 0.006 to 0.400), but **none of
  their CIs clear zero** except BNB/8h — meaning most of that apparent train-half edge
  isn't statistically distinguishable from noise even before checking out-of-sample.
- **Three test halves are STATISTICALLY SIGNIFICANTLY NEGATIVE** (CI clears zero on the
  negative side): ETH/8h (-0.191), SOL/8h (-0.194), SOL/24h (-0.160). This is a stronger
  and more concerning finding than "inconclusive" — it's evidence of genuine
  out-of-sample degradation on three of eight configs, not just a wide, uninformative
  CI.
- **BNB/8h train is the single strongest result** in the whole sweep (ExpR 0.400, CI
  clears zero positive, and by far the largest edge over random at +0.325), but its
  test half is a LOW SAMPLE (N=12) that neither confirms nor refutes it — the point
  estimate is small and positive (0.042) but the CI is very wide.
- **Random-entry baseline edge is inconsistent**: several configs show the specific
  "extreme funding" entry trigger performing WORSE than random entries within the same
  eligible pool on their test half (BTC/24h train -0.067, ETH/8h test -0.061, SOL/8h
  test -0.112, SOL/24h test -0.100) — meaning on those configs, timing entries off the
  funding extreme specifically added no value over random timing when funding data was
  available.

**Bottom line: FUNDING_EXTREME v1.0.0 does not show a robust, cross-validated edge on
any of the 8 asset/timeframe combinations tested.** BNB/8h is the only config with a
statistically-clear-of-zero positive train-half result, and its test half is too small
a sample to confirm it. This strategy is registered (versionable, as required) but is
**not** a candidate for the live scheduler based on this evidence.
