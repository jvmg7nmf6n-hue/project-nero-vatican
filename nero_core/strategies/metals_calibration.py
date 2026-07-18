"""SILVER/PLATINUM fee-calibration derivation — ASSET EXPANSION Phase A, Task 1.

Same methodology as nero_core.strategies.mean_reversion_gold_calibrated's GOLD
derivation: measure price/ATR(14) averaged over every 4h candle where MEAN_REVERSION
v1 actually takes an entry (RSI<35, close<lower BB, close>MA200, MA20 target above
close), then compare against GOLD's own measured ratio. See
tools/metals_data_calibration_audit.py for the measurement tool and
docs/metals_data_calibration_audit.md for the full audit report.

Both metals came out DERIVE_OWN, not REUSE_GOLD: their measured price/ATR ratios sit
much closer to BTC's (70.21) than to GOLD's (185.19) — i.e. SILVER and PLATINUM
futures are relatively much MORE volatile (as a fraction of price) than spot GOLD,
closer to crypto's volatility profile. This is itself a notable empirical finding for
the "do metals behave like GOLD or like crypto" question this research phase asks —
see the closing Phase A report.

Data source note: measured against yfinance COMEX Silver (SI=F) / NYMEX Platinum
(PL=F) CONTINUOUS FRONT-MONTH FUTURES, not spot XAG/USD or XPT/USD (Twelve Data's
free-tier plan returns HTTP 404 "available starting with the Grow or Venture plan"
for both spot symbols — confirmed directly, not inferred). Futures carry real
basis/roll effects that could differ from true spot price-to-ATR ratios, though price
ACTION (what every strategy in this codebase actually trades on) tracks spot closely
in practice for both metals.
"""
from __future__ import annotations

from nero_core.strategies.mean_reversion_gold_calibrated import BTC_MEASURED_PRICE_ATR_RATIO

# n=48 MEAN_REVERSION v1 entries, 4h SILVER (SI=F) candles, 2024-02-23 to 2026-07-17.
SILVER_MEASURED_PRICE_ATR_RATIO = 68.0986
SILVER_FEE_SCALE_FACTOR = BTC_MEASURED_PRICE_ATR_RATIO / SILVER_MEASURED_PRICE_ATR_RATIO  # ~= 1.0310

# n=16 MEAN_REVERSION v1 entries, 4h PLATINUM (PL=F) candles, 2024-02-23 to 2026-07-17.
# Sample is thinner than SILVER's (16 vs 48) — the same MIN_SAMPLE_SIZE=20 LOW-SAMPLE
# convention used everywhere else in this project applies to this calibration measurement
# too; treat PLATINUM_FEE_SCALE_FACTOR as provisional pending more live history.
PLATINUM_MEASURED_PRICE_ATR_RATIO = 72.7826
PLATINUM_FEE_SCALE_FACTOR = BTC_MEASURED_PRICE_ATR_RATIO / PLATINUM_MEASURED_PRICE_ATR_RATIO  # ~= 0.9646
