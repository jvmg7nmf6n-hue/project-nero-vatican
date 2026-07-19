# RMR Variant Research Cycle — Stage 3: Refine (Max 2, Diagnosis-Justified)

Tool: `tools/rmr_variant_research_stage3.py`. Two refinements, each citing the
specific Stage 2 finding it addresses, each tested ONLY on the asset/timeframe where
that weakness was diagnosed — no scope expansion. Full raw output:
`docs/rmr_stage3_raw_output.txt`.

## Refinement 1: RMR_LONG_ONLY_CONFIRMATION_BTC_1D (v1.4.0)

**Citation**: Stage 2(b) found the short leg cost ~-0.264 R/trade on BTC/1d
(substantial). Stage 2(d) found the confirmation entry's exit mix shifted BTC/1d
from 32% to 68% REVERSION_TARGET (the clearest mechanistic evidence in the cycle).
Both weaknesses/improvements were diagnosed on BTC/1d specifically — this refinement
stacks both fixes and is tested ONLY on BTC/1d.

| Half | N | ExpR |
|---|---|---|
| TRAIN | 8\* | +0.090 |
| TEST | 7\* | +0.219 |

**Positive both halves — PROMISING-WATCHLIST.** Grid-shift: NOT_APPLICABLE (native
daily data, per this task's own rule for 1d configs).

**Honest read**: stacking did NOT clearly improve on either individual filter.
Compare: v1.1.0-long-only alone (train +0.052, test +0.535) and v1.3.0-confirmation
alone (train +0.118, test +0.156) both showed a LARGER test-half ExpR than the
stacked v1.4.0 (+0.219) or a smaller one, respectively — no clean "compounding"
effect. What clearly DID compound was the sample shrinkage: 8/7 trades, the thinnest
sample of any BTC config in this entire cycle (down from 19/8 for long-only alone,
14/11 for confirmation alone). Stacking two diagnosis-backed filters produced a
still-positive but even less statistically supported result — a real signal
direction, not a clearly better one.

## Refinement 2: v1.1.0-long-only applied to ETH/4h

**Citation**: Stage 2(b) found substantial short-leg costs on the two assets actually
measured (EUR/USD -0.449 R/trade, BTC -0.264 R/trade). ETH's own Stage 1 refinement
(adx-falling) was the weakest and most inconsistent of the four — this refinement
tests whether ETH's weakness is ALSO short-side driven, using the SAME
already-registered v1.1.0-long-only variant (no new strategy code needed) applied to
the one asset where the OTHER filter underperformed. Tested ONLY on ETH/4h.

| Half | N | ExpR |
|---|---|---|
| TRAIN | 87 | -0.071 |
| TEST | 31 | -0.050 |

**Both halves still negative — DIED.** Compare to ETH baseline (train -0.162, test
-0.083): long-only IMPROVES the magnitude in both halves (about half the loss) but
never turns positive. **This refutes the hypothesis** — ETH's weakness is NOT
primarily short-side driven the way EUR/USD's and BTC's were. Something else is
limiting ETH/4h specifically; disabling shorts helps at the margin but isn't the
fix. Does not qualify for grid-shift consideration (requires positive both halves).

## Summary going into Stage 4

Neither refinement clearly outperforms what Stage 1 already found. Refinement 1
(BTC stacked) stays directionally positive but with a smaller, less reliable sample
than either individual filter. Refinement 2 (ETH long-only) DIED, closing off the
"maybe it's just the short leg everywhere" hypothesis for ETH specifically. No new
information here should be read as strengthening the case for promotion beyond what
Stage 1 already showed.
