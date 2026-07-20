# GOLD_SILVER_RATIO_MR — Data Audit

**Result: CLEARED.** Both timeframes comfortably clear the 5-year adequacy bar.

## Alignment gotcha found and fixed

GOLD (Twelve Data XAU/USD) and SILVER (yfinance SI=F continuous futures) daily
candles are stamped at **different times of day** — confirmed directly: GOLD's
close is timestamped `00:00 UTC`, SILVER's at `04:00 UTC`, a fixed 4-hour offset
from each source's own convention. An exact `close_time` join between the two
produces **zero matches**. `nero_core.strategies.gold_silver_ratio_mr.
align_gold_silver_candles` joins on the normalized **calendar date** instead — the
correct alignment for "the same trading day" across two data sources with
different intraday stamping conventions.

## History depth

| Timeframe | Aligned candles | Span |
|---|---|---|
| 1d | 3,830 | 18.7 years |
| 1week | 1,351 | 25.9 years |

## Ratio statistics (full history)

| Timeframe | Mean | Std | Min (date) | Max (date) | Full-history 10th/90th pct |
|---|---|---|---|---|---|
| 1d | 72.18 | 13.81 | 31.96 (2011-04-26) | 125.35 (2020-03-19) | 52.78 / 88.00 |
| 1week | 69.35 | 13.46 | 31.14 (2011-05-02) | 131.47 (2020-03-23) | 51.68 / 86.61 |

## The structural extreme, and why a fixed band would be wrong

The 2020-03 COVID spike pushed the ratio to **125.35 (1d) / 131.47 (1week)** —
exactly the ">120" extreme the task anticipated. This event alone drags the
**full-history** 90th percentile up to 88.0/86.6 — a threshold permanently
distorted by one historical shock, not representative of "currently extreme."

**This is precisely why the strategy uses a ROLLING 252-session percentile, not a
fixed threshold computed once over all history.** The most recent rolling-252
band sits at:

| Timeframe | Rolling 10th pct | Rolling median | Rolling 90th pct |
|---|---|---|---|
| 1d | 58.15 | 66.66 | 87.68 |
| 1week | 66.01 | 83.85 | 91.22 |

The rolling band adapts as the 2020 spike ages out of each 252-session trailing
window, rather than permanently biasing the entry threshold toward a level set by
one shock a decade-plus of subsequent history has already moved past.

## Warmup

3,579 of 3,830 daily candles (1d) and 1,100 of 1,351 weekly candles (1week) have a
valid rolling-252 band once the `shift(1)` no-lookahead convention and 252-session
warmup are both satisfied — an adequate evaluable sample either way.

**Verdict: not blocked. Proceeding to strategy build.**
