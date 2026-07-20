# Ranging-Regime Research Batch — Closing Consolidated Report

Three hypotheses, three commits (plus this closing report), built directly on RMR's
own validated finding that regime-detection — not entry timing — carries whatever
performance RANGE_MEAN_REVERSION showed. Full detail in
`docs/ranging_regime_batch_r1_regime_transition.md`,
`docs/ranging_regime_batch_r2_range_maturity.md`, and
`docs/ranging_regime_batch_r3_regime_allocator.md`. All three reuse
`range_mean_reversion.adx()` directly — no new ADX implementation was written
anywhere in this batch. 59 new unit tests across three new strategy modules plus two
gated variants of existing modules, all passing; full suite at 1127 tests, OK.

## R1 — REGIME_TRANSITION: does trading the regime CHANGE itself work?

New strategy, full state machine (mature-range detection, no-self-reference frozen
boundaries, ceiling/floor stop with aggregate stop-type tracking, range-height
target, failed-transition exit). Swept across 14 asset/timeframe configs with a
bespoke random-entry baseline isolating the boundary-break trigger's value from the
regime-ending condition alone.

**3 of 14 PROMISING-WATCHLIST (ETH/4h, ETH/1d, EURUSD/1d). 11 DIED. 0 SURVIVED.** All
three promising configs carry a LOW SAMPLE flag on at least one half — this
mechanism (a 10-candle mature range followed by a qualifying transition) is
low-frequency by construction on every timeframe tested. 0 configs reached the
grid-shift qualifying bar (both halves >= 20 trades, positive both halves).
**Answer: not established.** The mechanism works exactly as designed (verified by 30
unit tests); the live-market signal is not yet distinguishable from noise at the
sample sizes available.

## R2 — RANGE_MATURITY: does range age fix RANGE_MEAN_REVERSION's reversion signal?

One new gate on v1.0.0 (unchanged otherwise): entry requires ADX<25 for >= N
consecutive closed candles beforehand (N=20 for 4h/1d, N=8 for 1week). Compared
against FRESH v1.0.0 baselines on the identical data window across 7 targeted
configs.

**The gate never rescued a single DIED baseline**, and it actively WORSENED
GOLD/1week — RMR's single best result across the whole session — flipping train-half
expectancy from +0.026 to -0.038. SILVER/1week is the one config that held its
PROMISING-WATCHLIST status, but with a SMALLER sample and a SMALLER edge under the
gate, the same "shrinks without concentrating" signature RMR's own Stage 3 stacking
experiment already established as evidence against a robust effect. **Answer: no.**
Range age is not the missing variable RMR's closing report speculated it might be.

## R3 — REGIME_ALLOCATOR: does regime-gating improve strategies we already trust?

ADX(14)>=20-gated, append-only new versions of two already-verified, LIVE survivors
(BREAKOUT_MOMENTUM GOLD/1week, TREND_PULLBACK BNB/12h), each vs a fresh ungated
baseline on the identical window. Caught and fixed a real bug along the way:
TREND_PULLBACK's uncalibrated 1h-reference `max_holding_hours` was corrupting the
BNB/12h comparison (force-closing trades via TIME after 2 candles) until
`build_calibrated_params` was applied — the exact bug class this project's own
`backtest_survivor_verification.py` already flags for this config.

**Neither config's classification changed under gating** (GOLD/1week stayed
SURVIVED; BNB/12h stayed PROMISING-WATCHLIST under this run's bootstrap-CI lens, a
stricter bar than the config's original verification used — reported factually, not
as a live-wiring concern). Gating traded ~10% of the sample for a marginal,
split-direction shift in expectancy (worse train, better test, on BOTH configs) — not
the consistent, both-halves improvement a genuine regime-gating effect would
produce. **Answer: no, not meaningfully — and per the task's own framing, that is
itself the useful, neutral answer.** Simplicity wins for these two strategies;
neither live base registration was touched.

## Promotion recommendation: NOTHING IS PROMOTED

No config, gate, or new strategy from this entire batch merits live paper-tracking
wiring. R1's most promising configs are all sample-limited below the 20-trade bar on
at least one half. R2 produced a clean negative result — the maturity gate actively
hurts more than it helps. R3 produced a clean null result — gating neither helps nor
hurts either already-verified survivor meaningfully. All three findings are useful
(this is explicitly not framed as a batch-wide failure), but none clears this
project's own bar for live wiring (adequate, positive-both-halves sample AND
grid-shift-clearing where applicable — see the SILVER precedent from Asset Expansion
Phase A).

## What do we now know about ranging-regime structure that we didn't before?

**Regime-detection alone (ADX-based ranging/trending classification) is not, by
itself, a source of tradeable edge in this codebase's data — its value, where any
exists, is narrowly specific to RANGE_MEAN_REVERSION's own particular construction,
not a general-purpose filter that improves other strategies or supports a
freestanding transition-trading strategy.** Three independent tests point the same
direction:

1. **R1 shows the regime-ending MOMENT itself isn't a reliable trading signal** —
   trading the transition directly (rather than trading INSIDE a detected range, as
   RANGE_MEAN_REVERSION does) produces mostly DIED results, and even its most
   promising configs are thin-sample, not robust.
2. **R2 shows that MORE regime-detection (a stricter, longer-maturity ranging
   precondition) doesn't improve RANGE_MEAN_REVERSION** — if regime quality were the
   missing variable, filtering harder should have helped monotonically; instead it
   actively hurt the batch's best-known case (GOLD/1week) and merely thinned the one
   case it didn't hurt (SILVER/1week).
3. **R3 shows regime-gating doesn't transfer to strategies where regime detection
   ISN'T the core signal** — BREAKOUT_MOMENTUM and TREND_PULLBACK's own directional
   filters (breakout/MA200/RSI; established-uptrend pullback) already do the
   relevant work, and bolting ADX on top adds noise-level sample reduction, not
   signal.

Put together: RANGE_MEAN_REVERSION's own regime gate (ADX<25 as an entry
PRECONDITION, exactly as originally designed) appears to be doing something specific
to THAT strategy's band-extreme-inside-a-range mechanism — not a discoverable,
portable "ranging regime edge" that generalizes to transition-trading, stricter
maturity filtering, or gating unrelated trend-following strategies. This is a
narrower, more modest conclusion than the batch's founding hypothesis, and it is the
batch's most important finding: the regime filter's value (where real) is
mechanism-specific, not a standalone tradeable signal. Reported factually — data
decided this, not intuition.
