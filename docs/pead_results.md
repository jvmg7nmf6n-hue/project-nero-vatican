# PEAD v1.0.0 — Results

See `docs/pead_data_audit.md` for the hard-gate data audit (cleared). Strategy:
`nero_core/strategies/pead.py`. New data infrastructure:
`nero_core/data_sources/earnings_data.py` (added `lxml` to `requirements.txt`).
15 passing unit tests (`tests/test_pead.py`). Sweep tool: `tools/pead_sweep.py`.

## SURVIVOR-BIAS CAVEAT — read this before the results below

**This universe (AAPL, MSFT, GOOGL, TSLA, AMZN, NVDA, META) consists of large,
currently-successful companies by construction.** Every result in this document
says nothing about whether the same effect holds for companies that failed,
were delisted, or were acquired before becoming famous. Treat these results as
"PEAD is real and strong among mega-cap survivors," not "PEAD is real and
strong, full stop."

## Full results, all 6 configs

| Config | Verdict | Train N/ExpR/CI | Test N/ExpR/CI | Edge over random (train/test) |
|---|---|---|---|---|
| 3% / hold 5 | **SURVIVED** | 257/+0.607/[0.397,0.831] | 199/+0.494/[0.289,0.705] | +0.391 / +0.351 |
| 3% / hold 10 | **SURVIVED** | 257/+0.649/[0.412,0.900] | 199/+0.622/[0.381,0.874] | +0.414 / +0.459 |
| 5% / hold 5 | **SURVIVED** | 227/+0.572/[0.358,0.797] | 168/+0.546/[0.327,0.779] | +0.370 / +0.364 |
| 5% / hold 10 | **SURVIVED** | 227/+0.594/[0.366,0.833] | 168/+0.702/[0.440,0.986] | +0.387 / +0.485 |
| 8% / hold 5 | **SURVIVED** | 213/+0.620/[0.394,0.865] | 129/+0.624/[0.378,0.886] | +0.422 / +0.454 |
| 8% / hold 10 | **SURVIVED** | 213/+0.642/[0.396,0.909] | 129/+0.806/[0.496,1.134] | +0.435 / +0.604 |

**All 6 of 6 configs SURVIVED — every one.** Every train/test half clears the
20-trade adequacy bar (N=129 to 257), every single bootstrap CI is entirely
positive (never crosses zero, in either half, in any config), and every
edge-over-random figure is strongly positive (+0.35 to +0.60) — the surprise
DIRECTION itself carries the edge, not just elevated event-day volatility that
any direction would have captured equally.

This is, by a wide margin, the strongest and cleanest result of the entire
Three New Hypothesis Batch — and one of the strongest results across every
research batch this project has run. Not spun: this matches PEAD's own standing
as one of the most-replicated anomalies in academic finance, on a universe
(mega-cap tech/growth names) where it has been repeatedly documented before —
the result is unsurprising in DIRECTION, notable in how cleanly and consistently
it shows up here.

## Reading this factually (not over-claiming)

- **Threshold barely matters; holding window matters a little.** 3%/5%/8%
  thresholds produce similar expectancy (~0.57-0.65 train) — the drift doesn't
  require a huge surprise to show up, it's present across the whole range
  tested. The 10-session holds show a modest, consistent edge over the
  5-session holds on the test half (e.g. 8%: +0.624 -> +0.806) — the drift
  continues to accrue past 5 sessions, at least through day 10.
- **STOP fires on roughly a third of trades everywhere** (e.g. 3%/hold5 train:
  79 of 257) — a real minority of trades move against the surprise direction
  hard enough to hit the 2xATR disaster stop, but the majority ride the
  TIME-based exit, and the strategy is robustly profitable across both outcomes
  pooled together.
- **All 7 tickers contribute positively to the pooled sample** (roughly
  25-50 trades each per config) — this is not one or two tickers carrying the
  whole result; the pattern is broad across the universe tested.
- **Every config here is genuinely quarterly-cadence data** — 213-257 total
  events across 7 tickers over ~20-25 years of combined history is not a huge
  raw number of INDEPENDENT companies (still just 7), even though the trade
  COUNT clears the adequacy bar. The right way to read "SURVIVED" here is
  "SURVIVED on this specific 7-mega-cap universe," not "PEAD is a proven,
  universal edge" — the survivor-bias caveat above is the load-bearing caveat,
  not a formality.

## Grid-shift

Not applicable/not run — 1day is the only timeframe this hypothesis specifies,
and per the task's own rule, 1day is capped at watch-list-eligible regardless of
the numbers (though this batch's SURVIVED classification already exceeds that
floor on every statistical measure tracked here).

## Verdict

**6 of 6 configs SURVIVED.** This is the standout result of the batch. Per the
project's own promotion discipline (adequate sample, positive both halves, CI
clears zero on both halves), every one of these 6 configs would ordinarily merit
consideration for live wiring — the closing report addresses which, if any, to
actually recommend, weighing the survivor-bias caveat and the fact that "6
configs on the same 7-ticker universe" are not 6 independent discoveries.
