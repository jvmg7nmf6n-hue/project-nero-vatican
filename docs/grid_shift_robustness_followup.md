# Grid-Shift Robustness Follow-Up (H6 continuation)

## Purpose

H6's robustness audit found several previously-qualifying configs' trades clustering
heavily on specific days/hours (e.g. one config had 100% of its trades close at hour 11
UTC). This follow-up asks the direct question: **does positive expectancy survive moving
the candle grid's boundaries in wall-clock time, or does it vanish/flip?**

## Method

- Native 1h candles fetched live per asset (Binance, longest available history).
- `nero_core/data_sources/candle_resampling.py::resample_hourly_to_grid` rebuilds
  12h/2h candles at a chosen UTC-clock offset (bin edges shifted by `offset_hours`),
  keeping only complete, gap-free bins (partial leading/trailing bins and any bin
  straddling missing source data are dropped, never fabricated).
- Grids tested: **12h** configs at offset +0h (control), +3h, +6h; **2h** configs at
  offset +0h (control), +1h. The native exchange-provided grid is also fetched
  independently as a reference alongside the offset+0h resampled control.
- Same registered strategy, same parameters (via `build_calibrated_params`), same
  70/30 chronological train/test split, run independently on every grid variant.
- Filter: **PASS** = positive expectancy in both train and test, with ≥20 trades in
  each half (same bar used throughout this research program). **FAIL** = filter not met
  on that grid (negative expectancy in either half, or below-sample).

## Volume aggregation verification

Verified with a deterministic unit test (`tests/test_candle_resampling.py::
test_ohlcv_aggregation_is_open_first_high_max_low_min_close_last_volume_sum`) using
synthetic 1h candles with known, hand-computed values: for 12 consecutive candles with
volumes 0..11, the resampled 12h candle's volume equals `sum(0..11) = 66` exactly, its
open equals the first candle's open, high the max of all highs, low the min of all lows,
and close the last candle's close. A separate test confirms bins straddling a gap in the
source data are dropped rather than aggregated over missing candles. All 7 tests in that
file pass.

## Results

Legend: `N` = trade count, `Win%` = win rate, `ExpR` = expectancy in R, `PF` = profit
factor, `*` = below 20-trade minimum sample (exploratory only).

### BTC / 12h / MEAN_REVERSION relaxed-pullback

| Grid | Candles | Split | N | Win% | ExpR | PF | Filter |
|---|---|---|---|---|---|---|---|
| Native (Binance 12h) | 6511 | Train | 46 | 52.2% | 0.048 | 1.08 | |
| | | Test | 25 | 56.0% | 0.099 | 1.19 | **PASS** |
| offset+0h (control) | 6480 | Train | 44 | 52.3% | 0.067 | 1.12 | |
| | | Test | 24 | 54.2% | 0.079 | 1.14 | **PASS** |
| offset+3h | 6467 | Train | 45 | 53.3% | 0.088 | 1.18 | |
| | | Test | 22 | 54.5% | 0.085 | 1.17 | **PASS** |
| offset+6h | 6472 | Train | 46 | 58.7% | 0.109 | 1.24 | |
| | | Test | 21 | 47.6% | -0.046 | 0.91 | **FAIL** (test flips negative) |

### BNB / 12h / TREND_PULLBACK

| Grid | Candles | Split | N | Win% | ExpR | PF | Filter |
|---|---|---|---|---|---|---|---|
| Native (Binance 12h) | 6349 | Train | 57 | 50.9% | 0.147 | 1.27 | |
| | | Test | 30 | 56.7% | 0.243 | 1.55 | **PASS** |
| offset+0h (control) | 6319 | Train | 56 | 53.6% | 0.186 | 1.37 | |
| | | Test | 29 | 55.2% | 0.206 | 1.45 | **PASS** |
| offset+3h | 6307 | Train | 60 | 51.7% | 0.156 | 1.29 | |
| | | Test | 28 | 50.0% | 0.105 | 1.20 | **PASS** |
| offset+6h | 6312 | Train | 56 | 51.8% | 0.183 | 1.35 | |
| | | Test | 30 | 56.7% | 0.233 | 1.53 | **PASS** |

### BNB / 12h / MEAN_REVERSION relaxed-pullback

| Grid | Candles | Split | N | Win% | ExpR | PF | Filter |
|---|---|---|---|---|---|---|---|
| Native (Binance 12h) | 6349 | Train | 49 | 46.9% | 0.014 | 1.02 | |
| | | Test | 21 | 57.1% | 0.207 | 1.43 | **PASS** |
| offset+0h (control) | 6319 | Train | 49 | 46.9% | 0.014 | 1.02 | |
| | | Test | 21 | 57.1% | 0.207 | 1.43 | **PASS** |
| offset+3h | 6307 | Train | 47 | 44.7% | -0.013 | 0.97 | |
| | | Test | 23 | 60.9% | 0.172 | 1.39 | **FAIL** (train flips negative) |
| offset+6h | 6312 | Train | 55 | 45.5% | -0.009 | 0.97 | |
| | | Test | 22 | 59.1% | 0.074 | 1.16 | **FAIL** (train flips negative) |

### XRP / 2h / MEAN_REVERSION deep-value

| Grid | Candles | Split | N | Win% | ExpR | PF | Filter |
|---|---|---|---|---|---|---|---|
| Native (Binance 2h) | 35915 | Train | 84 | 51.2% | 0.116 | 1.21 | |
| | | Test | 35 | 45.7% | 0.060 | 1.08 | **PASS** |
| offset+0h (control) | 35897 | Train | 84 | 51.2% | 0.116 | 1.21 | |
| | | Test | 35 | 45.7% | 0.060 | 1.08 | **PASS** |
| offset+1h | 35890 | Train | 87 | 41.4% | -0.153 | 0.76 | |
| | | Test | 50 | 36.0% | -0.136 | 0.77 | **FAIL** (both halves flip negative) |

### NEAR / 2h / MEAN_REVERSION deep-value

| Grid | Candles | Split | N | Win% | ExpR | PF | Filter |
|---|---|---|---|---|---|---|---|
| Native (fell back to Coinbase 2h) | 300 | Train | 0 | — | 0.000 | — | **DATA ISSUE** — see note below |
| | | Test | 0 | — | 0.000 | — | |
| offset+0h (control) | 25209 | Train | 61 | 44.3% | 0.024 | 1.03 | |
| | | Test | 27 | 44.4% | 0.086 | 1.14 | **PASS** |
| offset+1h | 25208 | Train | 65 | 35.4% | -0.191 | 0.71 | |
| | | Test | 25 | 32.0% | -0.237 | 0.66 | **FAIL** (both halves flip negative) |

**Data note:** the "native" NEAR/2h fetch fell back to Coinbase (Binance's live call did
not succeed on this run) and Coinbase caps replies at 300 candles — additionally,
`MarketDataClient._coinbase_granularity` has no `"2h"` entry and silently defaults to
3600 seconds (1h), so this fallback path does not actually deliver 2h candles at all.
This is a pre-existing gap in `nero_core/data_sources/market_data.py`, not something
introduced by this follow-up, and not something this task asked to fix — flagged here
factually rather than silently reported as a real 0-trade result. The offset+0h
resampled-from-1h control (25,209 candles) is unaffected by this gap and is the
trustworthy reference for this config.

### BTC-ETH / 12h / COINTEGRATION_PAIRS

| Grid | Candles | Split | N | Win% | ExpR | PF | Filter |
|---|---|---|---|---|---|---|---|
| Native (Binance 12h, both legs) | 6509 | Train | 61 | 49.2% | 0.047 | 3.65 | |
| | | Test | 22 | 50.0% | 0.003 | 1.20 | **PASS** |
| offset+0h (control) | 6479 | Train | 57 | 49.1% | 0.049 | 3.50 | |
| | | Test | 22 | 50.0% | 0.003 | 1.20 | **PASS** |
| offset+3h | 6467 | Train | 42 | 52.4% | 0.082 | 5.00 | |
| | | Test | 23 | 60.9% | 0.006 | 1.49 | **PASS** |
| offset+6h | 6472 | Train | 33 | 39.4% | 0.056 | 3.28 | |
| | | Test | 21 | 42.9% | 0.005 | 1.31 | **PASS** |

### BTC-SOL / 12h lag5 / LEADLAG_FOLLOW

| Grid | Candles | Split | N | Win% | ExpR | PF | Filter |
|---|---|---|---|---|---|---|---|
| Native (both legs) | 4332 | Train | 133 | 50.4% | 0.134 | 1.27 | |
| | | Test | 49 | 55.1% | 0.222 | 1.46 | **PASS** |
| offset+0h (control) | 4321 | Train | 133 | 51.1% | 0.151 | 1.31 | |
| | | Test | 49 | 55.1% | 0.222 | 1.46 | **PASS** |
| offset+3h | 4318 | Train | 130 | 44.6% | 0.016 | 1.02 | |
| | | Test | 50 | 48.0% | 0.101 | 1.18 | **PASS** |
| offset+6h | 4320 | Train | 122 | 47.5% | 0.063 | 1.11 | |
| | | Test | 56 | 41.1% | -0.077 | 0.86 | **FAIL** (test flips negative) |

### BTC-XRP / 12h lag3 / LEADLAG_FOLLOW

| Grid | Candles | Split | N | Win% | ExpR | PF | Filter |
|---|---|---|---|---|---|---|---|
| Native (both legs) | 5991 | Train | 174 | 45.4% | 0.022 | 1.03 | |
| | | Test | 76 | 51.3% | 0.096 | 1.17 | **PASS** |
| offset+0h (control) | 5964 | Train | 176 | 44.3% | -0.000 | 0.99 | |
| | | Test | 76 | 51.3% | 0.096 | 1.17 | **FAIL** (train ~flat/negative) |
| offset+3h | 5953 | Train | 181 | 42.0% | -0.053 | 0.89 | |
| | | Test | 73 | 47.9% | 0.043 | 1.06 | **FAIL** (train negative) |
| offset+6h | 5958 | Train | 168 | 45.2% | 0.028 | 1.04 | |
| | | Test | 90 | 41.1% | -0.094 | 0.84 | **FAIL** (test negative) |

### BTC-DOGE / 12h lag3 / LEADLAG_FOLLOW

| Grid | Candles | Split | N | Win% | ExpR | PF | Filter |
|---|---|---|---|---|---|---|---|
| Native (both legs) | 5136 | Train | 158 | 49.4% | 0.114 | 1.23 | |
| | | Test | 64 | 50.0% | 0.103 | 1.18 | **PASS** |
| offset+0h (control) | 5118 | Train | 161 | 49.1% | 0.108 | 1.21 | |
| | | Test | 64 | 50.0% | 0.103 | 1.18 | **PASS** |
| offset+3h | 5110 | Train | 141 | 46.1% | 0.079 | 1.15 | |
| | | Test | 63 | 52.4% | 0.201 | 1.41 | **PASS** |
| offset+6h | 5116 | Train | 151 | 47.0% | 0.067 | 1.12 | |
| | | Test | 71 | 42.3% | -0.061 | 0.89 | **FAIL** (test flips negative) |

### BTC-NEAR / 12h lag5 / LEADLAG_FOLLOW

| Grid | Candles | Split | N | Win% | ExpR | PF | Filter |
|---|---|---|---|---|---|---|---|
| Native (both legs) | 4204 | Train | 124 | 52.4% | 0.173 | 1.36 | |
| | | Test | 50 | 46.0% | 0.043 | 1.07 | **PASS** |
| offset+0h (control) | 4193 | Train | 127 | 52.0% | 0.163 | 1.33 | |
| | | Test | 50 | 46.0% | 0.043 | 1.07 | **PASS** |
| offset+3h | 4190 | Train | 115 | 45.2% | 0.028 | 1.04 | |
| | | Test | 44 | 38.6% | -0.118 | 0.80 | **FAIL** (test flips negative) |
| offset+6h | 4192 | Train | 122 | 45.1% | 0.032 | 1.04 | |
| | | Test | 57 | 33.3% | -0.215 | 0.68 | **FAIL** (test flips negative) |

### Out of scope

BTC-BNB / 24h lag1 / LEADLAG_FOLLOW: only 12h (+3h/+6h) and 2h (+1h) offsets were
specified for this grid-shift test; no 24h offset was given, so this pair was not
retested rather than assigned an arbitrary shift.

## Filter-pass matrix (PASS = positive expectancy both halves, ≥20 trades each)

| Config | Native | offset+0h | offset+3h | offset+6h (or +1h) |
|---|---|---|---|---|
| BTC/12h MR relaxed-pullback | PASS | PASS | PASS | FAIL |
| BNB/12h TREND_PULLBACK | PASS | PASS | PASS | PASS |
| BNB/12h MR relaxed-pullback | PASS | PASS | FAIL | FAIL |
| XRP/2h MR deep-value | PASS | PASS | FAIL | — |
| NEAR/2h MR deep-value | DATA ISSUE | PASS | FAIL | — |
| BTC-ETH/12h COINTEGRATION_PAIRS | PASS | PASS | PASS | PASS |
| BTC-SOL/12h LEADLAG_FOLLOW | PASS | PASS | PASS | FAIL |
| BTC-XRP/12h LEADLAG_FOLLOW | PASS | FAIL | FAIL | FAIL |
| BTC-DOGE/12h LEADLAG_FOLLOW | PASS | PASS | PASS | FAIL |
| BTC-NEAR/12h LEADLAG_FOLLOW | PASS | PASS | FAIL | FAIL |

2 of 10 configs (BNB/12h TREND_PULLBACK, BTC-ETH/12h COINTEGRATION_PAIRS) pass the strict
filter on every grid tested (native, +0h, +3h, +6h). The remaining 8 pass on the native
grid but fail the filter on at least one shifted grid.
