# RMR Variant Research Cycle — Stage 4: Verdict + Promotion List

Classification of all 6 configs tested across Stages 1 and 3, per this project's
standard taxonomy (SURVIVED / PROMISING-WATCHLIST / DIED / SKIPPED).

## Full classification

| # | Config | Asset/TF | Verdict | Train N/ExpR | Test N/ExpR | Grid-shift |
|---|---|---|---|---|---|---|
| 1 | RMR_LONG_ONLY_EURUSD_4H | EUR/USD/4h | **DIED** | 30/-0.243 | 12\*/-0.280 | N/A (DIED) |
| 2 | RMR_ADX_FALLING_ETH_4H | ETH/4h | **DIED** | 141/-0.192 | 61/+0.035 | N/A (DIED) |
| 3 | RMR_LONG_ONLY_BTC_1D | BTC/1d | **PROMISING-WATCHLIST** | 19\*/+0.052 | 8\*/+0.535 | NOT_APPLICABLE (native 1d) |
| 4 | RMR_CONFIRMATION_BTC_1D | BTC/1d | **PROMISING-WATCHLIST** | 14\*/+0.118 | 11\*/+0.156 | NOT_APPLICABLE (native 1d) |
| 5 | RMR_LONG_ONLY_CONFIRMATION_BTC_1D | BTC/1d | **PROMISING-WATCHLIST** | 8\*/+0.090 | 7\*/+0.219 | NOT_APPLICABLE (native 1d) |
| 6 | v1.1.0-long-only on ETH/4h (Refinement 2) | ETH/4h | **DIED** | 87/-0.071 | 31/-0.050 | N/A (DIED) |

**0 of 6 configs SURVIVED. 3 PROMISING-WATCHLIST (all BTC/1d). 3 DIED.**

Every PROMISING-WATCHLIST config is capped there for the same structural reason:
1d/daily data is native (not resampled) for BTC in this pipeline, so grid-shift
verification cannot run at all — the SURVIVED bar requires holding across grid
shifts, and an untestable claim cannot be promoted, regardless of how the numbers
look. This mirrors the exact precedent already established for metals' settlement
gaps and stocks'/forex's native daily data in prior research phases.

## Promotion recommendation: NOTHING IS PROMOTED

**No config in this cycle merits live paper-tracking wiring in a follow-up batch.**
This is stated plainly, not as a consolation:

- **All three PROMISING-WATCHLIST configs have LOW SAMPLE flags on every single
  half tested** (7 to 19 trades per half, against a 20-trade adequacy bar). Even the
  best-sampled one (RMR_LONG_ONLY_BTC_1D, train N=19) falls one trade short.
- **Stage 3's own stacking experiment (Refinement 1) undercuts confidence rather than
  building it**: combining the two individually-promising BTC filters did not
  produce a larger or more consistent edge — it just shrank the sample further (to
  7-8 trades), the thinnest of the whole cycle. If these were a genuine, robust
  effect, stacking two independently-supportive filters should have concentrated it
  further, not merely thinned the sample while leaving the edge magnitude flat or
  smaller.
- **Every train-half 95% CI for the BTC configs crosses zero** (Stage 1: [-0.329,
  0.437] for long-only, [-0.304, 0.527] for confirmation) — even setting aside the
  grid-shift and sample-size problems, these results are not yet statistically
  distinguishable from noise on the train half alone.
- The one refinement that WOULD have been genuinely testable via grid-shift
  (v1.1.0-long-only on ETH/4h) DIED outright — the strongest, most rigorously-tested
  config in the entire cycle is also the clearest failure.

**If this line of research is revisited**, the three BTC/1d configs are reasonable
candidates to re-test once more BTC daily history accrues (more trades would let the
sample-size and CI concerns resolve on their own, one way or the other) — but that is
a "keep watching with more data" recommendation, not a "wire it live now" one. None
of the three would carry an honest label stronger than "promising-watchlist,
sample-limited, grid-shift-untestable" if surfaced anywhere today, and per this
project's own discipline (see the SILVER precedent in Asset Expansion Phase A —
wired live only with adequate-sample, positive-both-halves results, never on samples
this thin), that bar has not been cleared.
