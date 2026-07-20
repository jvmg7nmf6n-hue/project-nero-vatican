# Three New Hypothesis Batch — Closing Consolidated Report

Three hypotheses, three commits (plus this closing report). Full detail in
`docs/gold_silver_ratio_data_audit.md` + `docs/gold_silver_ratio_mr_results.md`,
`docs/carry_momentum_data_audit.md` + `docs/carry_momentum_results.md`, and
`docs/pead_data_audit.md` + `docs/pead_results.md`. 62 new unit tests across
three new strategy modules plus two new data-source modules
(`nero_core/data_sources/fred_rates.py`, `nero_core/data_sources/
earnings_data.py`); full suite at 1209 tests, OK.

## Hypothesis 1 — GOLD_SILVER_RATIO_MR (Metals)

Data audit found and fixed a real alignment gotcha (GOLD/SILVER daily closes
stamped 4 hours apart across vendors — calendar-date join, not close_time).
18.7/25.9 years of history. Genuine two-leg pairs trade (both LONG and SHORT
legs modeled, unlike COINTEGRATION_PAIRS' long-leg-only simplification).

**1d and 1week: both PROMISING-WATCHLIST.** Positive both halves on both
timeframes; 1d clears the 20-trade adequacy bar on both halves (N=59/26); 1week
is thinner (N=11/6). Positive edge-over-random in 3 of 4 half-configs. Neither
reaches SURVIVED (every CI crosses zero) but both show a real, mechanistically
plausible, consistently-positive-direction signal.

## Hypothesis 2 — CARRY_MOMENTUM (Forex)

Data audit verified 8 FRED policy-rate series live (3 daily, 5 documented
monthly OECD-interbank substitutions, several stale candidates explicitly
tested and rejected). All 7 forex pairs confirmed accessible and calendar-
aligned.

**1d and 1week: both DIED.** Negative expectancy on every half, adequately
sampled on both timeframes (N=653/277 and N=120/116) — 1d's train-half CI is
entirely negative, not merely unproven. Edge-over-random is negative in 3 of 4
half-configs — the ranking-by-differential mechanism this strategy is built
around does not show value over randomly picking among momentum-passing
candidates. A confidently negative, well-sampled result, not a thin one.

## Hypothesis 3 — PEAD (Stocks)

Hard-gate data audit cleared: built a new earnings-surprise fetcher from
scratch, confirmed lookahead-safe entry timing across all 7 tickers' full
history, confirmed SPY has no earnings of its own (benchmark-only).

**All 6 of 6 configs SURVIVED.** Every half clears the 20-trade adequacy bar
(N=129-257), every bootstrap CI is entirely positive, every edge-over-random
figure is strongly positive (+0.35 to +0.60) — surprise DIRECTION carries the
edge, not just event-day volatility. The strongest, cleanest result across this
entire batch and one of the strongest across every research batch this project
has run this session. **SURVIVOR-BIAS CAVEAT (permanent, load-bearing, not a
formality)**: this universe is 7 large, currently-successful companies by
construction — the result says nothing about companies that failed, were
delisted, or were acquired before becoming famous.

## Aggregate: which hypothesis showed the most life?

**PEAD, by a wide margin** — 6/6 SURVIVED vs GOLD_SILVER_RATIO_MR's 2/2
PROMISING-WATCHLIST vs CARRY_MOMENTUM's 0/2 DIED. If this batch has a single
headline finding, it's PEAD's.

## Cross-asset macro thread: does one exist?

**No — the data does not support a common macro-sensitivity story.**
CARRY_MOMENTUM is the one hypothesis in this batch genuinely driven by
macro/policy inputs (FRED rate differentials) and it DIED. GOLD_SILVER_RATIO_MR
(a pure price-ratio mean-reversion, not itself a macro signal, though gold and
silver both have macro-sensitive demand drivers) showed a weak positive signal;
PEAD (a pure market-microstructure/behavioral anomaly, no macro input at all)
showed the strongest signal. If anything, this batch's results point AWAY from
"macro-sensitivity is a common driver of the live signals" — the two
mechanisms that showed life (ratio mean-reversion, earnings drift) are not
macro-driven, and the one that IS macro-driven (carry) is the one that failed.
Reported factually, not forced into a narrative the data doesn't support.

## EXPLICIT PROMOTION LIST

Per the task's own instruction to classify generously toward watch-list and
route thin-but-positive results to live forward-testing rather than auto-fail
them:

### Recommended for the next live-wiring batch

1. **GOLD_SILVER_RATIO_MR, 1d** (`gold-silver-ratio-mr-v1.0.0`, GOLD+SILVER
   pair) — status string: **"watchlist — forward-testing, not verified
   (positive both halves, edge over random in 3 of 4 half-configs; adequate
   sample on 1d; CI crosses zero; grid-shift capped at watchlist per task
   rule)"**. The stronger of the two timeframes (adequate sample on both
   halves, vs 1week's thin N=11/6) — recommended as the primary candidate;
   1week is a secondary, lower-priority watch candidate if the business wants
   both timeframes live.

2. **PEAD, 3% threshold / 10-session hold** (`pead-v1.0.0-surprise3pct-hold10`,
   pooled across the 7-ticker universe) — status string: **"verified —
   survivor-bias caveat: 7 large, currently-successful companies only (mega-cap
   universe, not a general claim); adequate sample, CI clears zero both
   halves, strong edge over random"**. Chosen over the other 5 PEAD configs as
   the broadest-net representative (catches the most events/tickers while
   still SURVIVED on every measure) — wiring all 6 configs would be largely
   redundant (same underlying signal, overlapping tickers and time windows),
   not 6 independent discoveries.

3. **PEAD, 8% threshold / 10-session hold** (`pead-v1.0.0-surprise8pct-hold10`)
   — status string: same framing as #2, noting this is the single
   strongest-edge config in the whole sweep (test-half ExpR +0.806,
   edge-over-random +0.604) — recommended as a second, more-selective PEAD
   candidate alongside #2, giving the business both a broad and a
   high-conviction PEAD variant to forward-test live, without wiring all 6
   near-duplicate configs.

### Not recommended

- **GOLD_SILVER_RATIO_MR, 1week** — eligible in principle (same logic as #1)
  but deprioritized given its thinner sample; revisit once more weekly history
  accrues.
- **CARRY_MOMENTUM (both timeframes)** — DIED confidently, well-sampled,
  negative CI on 1d train. Not a promotion candidate.
- **PEAD's other 4 configs** (3%/hold5, 5%/hold5, 5%/hold10, 8%/hold5) — all
  independently SURVIVED and are legitimate future candidates, but wiring all 6
  would just be redundant coverage of the same signal; #2 and #3 above are
  judged the most useful pair to represent the finding live.

## Data decided; business keeps its pipeline fed

Per the task's own framing: this batch found one confident kill
(CARRY_MOMENTUM), one genuine watch-list candidate worth accruing live evidence
on (GOLD_SILVER_RATIO_MR), and one strong, clean survivor with a permanent
caveat attached (PEAD). Three new promotion candidates are ready for the next
live-wiring batch — the replay machinery generalized in the prior batch already
supports arbitrary strategy shapes (multi-leg pairs, portfolio positions,
event-driven entries), so none of these three should hit the kind of
architecture-mismatch blocker RANGE_MEAN_REVERSION did before that
generalization.
