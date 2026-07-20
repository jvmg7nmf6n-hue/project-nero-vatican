# Ranging-Regime Research Batch — R3: REGIME_ALLOCATOR

**Question: does regime-gating improve strategies we already trust?**

If regime-detection (ADX(14), reused from range_mean_reversion.py) is a real,
independent skill, it should improve strategies with an already-verified, LIVE edge
— not just underperform new, ranging-specific strategies. Two ADX(14) >= 20-gated
variants, each an append-only new registered version (the live base variant's own
registration and module code are never touched):

- `nero_core/strategies/breakout_momentum_gold_calibrated_1week_adx_gated.py`
  (breakout-momentum-v1.6.0-gold-calibrated-1week-adx-gated) — gates
  breakout-momentum-v1.2.0-gold-calibrated-1week (live: GOLD/1week).
- `nero_core/strategies/trend_pullback_adx_gated.py` (trend-pullback-v1.1.0-adx-gated)
  — gates trend-pullback-v1.0.0 (live: BNB/12h).

20 new unit tests across both modules (`tests/test_breakout_momentum_gold_
calibrated_1week_adx_gated.py`, `tests/test_trend_pullback_adx_gated.py`): gate
rejection/acceptance, coexistence with the base module's own rejection reasons,
end-to-end backtest smoke tests, and registration discipline (including a field-by-
field check that ONLY the new ADX fields differ from the live base's own parameters).
All pass.

**Data bug caught and fixed during this task**: `trend_pullback`'s registered
parameters carry a 1h-reference `max_holding_hours=24` default (documented in its own
module docstring as needing per-timeframe recalibration — the same bug class the
GOLD/1week BREAKOUT_MOMENTUM fix addressed earlier this project, and one
`tools/backtest_survivor_verification.py` already flags for this exact BNB/12h
config). The first sweep run used the raw, uncalibrated default and force-closed
nearly every trade via TIME after 2 candles, producing a false DIED result for BOTH
the gated and ungated BNB/12h variants. Fixed by applying
`timeframe_calibration.build_calibrated_params` before both runs — the corrected
numbers below reflect the fix.

## Gated vs fresh ungated baseline, same data window, same run

| Config | Ungated (fresh) | Gated |
|---|---|---|
| BREAKOUT_MOMENTUM GOLD/1week | **SURVIVED** — TRAIN 63/+0.395 [0.142,0.648], TEST 31/+0.426 [0.062,0.789] | **SURVIVED** — TRAIN 57/+0.387 [0.110,0.664], TEST 28/+0.501 [0.099,0.902] |
| TREND_PULLBACK BNB/12h | PROMISING-WATCHLIST — TRAIN 57/+0.147 [-0.151,0.447], TEST 30/+0.243 [-0.154,0.619] | PROMISING-WATCHLIST — TRAIN 50/+0.126 [-0.185,0.443], TEST 26/+0.287 [-0.155,0.699] |

(TREND_PULLBACK BNB/12h shows PROMISING-WATCHLIST rather than its previously-reported
SURVIVED status under this run's stricter bootstrap-CI lens — both halves' 95% CIs
cross zero here. This mirrors `tools/backtest_survivor_verification.py`'s own
explicit precedent of "reporting factually, including if a survivor looks weaker
under a stricter lens" — not a claim that the live registration is wrong, just that
this specific re-run, on the specific data window fetched today, doesn't clear the
same statistical bar. No live wiring changes as a result of this observation.)

## Reading this factually

- **Neither config is meaningfully improved by gating.** GOLD/1week stays SURVIVED
  either way; BNB/12h stays PROMISING-WATCHLIST either way. Gating does not flip
  either config's classification in either direction.
- **Gating trades sample size for a marginal, inconsistent shift in expectancy.**
  Both configs lose 6-10% of their trades to the gate (GOLD: 63->57 train, 31->28
  test; BNB: 57->50 train, 30->26 test). In exchange, train-half expectancy is
  slightly WORSE under gating in both configs (GOLD: 0.395->0.387; BNB: 0.147->0.126)
  while test-half expectancy is slightly BETTER in both (GOLD: 0.426->0.501; BNB:
  0.243->0.287). This split pattern (worse train, better test) is consistent with
  gating removing a handful of idiosyncratic trades rather than systematically
  filtering out a real source of losses — if ADX were doing real, directional work
  here, the improvement should show up on both halves, not just one.
- **Both live strategies already have their own directional signal doing the real
  work** (a 20-bar breakout + MA200 + RSI filter for BREAKOUT_MOMENTUM; an
  established-uptrend pullback-to-MA50 for TREND_PULLBACK) — an ADX regime gate on
  top of an already-directional, already-trending-market strategy has much less room
  to add value than it does for RANGE_MEAN_REVERSION or a pure regime-transition
  strategy, where the regime IS the entire signal.

## Grid-shift

Not applicable to this comparison structure. GOLD/1week is native (not resampled)
data — grid-shift is NOT_APPLICABLE regardless of outcome, per this project's own
established precedent. BNB/12h is fetched as native Binance 12h in this sweep (not
resampled from finer data), and — per the corrected RMR Stage 3 understanding — a
genuine grid-shift test WOULD be possible by resampling BNB's own 1h history to 12h
at different offsets, but since neither the gated nor ungated variant reaches
SURVIVED under this run's bootstrap-CI lens (both PROMISING-WATCHLIST, CI crosses
zero on both halves), neither meets the qualifying bar that would make such a test
meaningful.

## Verdict: does gating improve the survivors?

**No, not meaningfully — and that is itself the useful, neutral answer this
hypothesis was designed to produce.** Per the task's own framing, this is not a
failure: it means simplicity wins for these two already-verified strategies. Neither
gated variant is promoted or wired anywhere; both live base registrations
(breakout-momentum-v1.2.0-gold-calibrated-1week, trend-pullback-v1.0.0) are
completely unchanged.
