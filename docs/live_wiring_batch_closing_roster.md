# Live Wiring Batch — Closing: Full Current Live Roster

**This batch added nothing to the live roster.** All 4 requested RMR watchlist
configs were deferred — see `docs/live_wiring_batch_rmr_watchlist_deferral.md` for
the full technical reason (a compounding, three-way incompatibility with
`nero_core.execution.replay.replay_single_asset_events`, the shared machinery every
currently-wired config depends on). The roster below is the pre-existing state,
unchanged by this batch, reported in full per the task's own closing instruction.

## Full roster: 12 configs live

| # | Strategy | Asset | Timeframe | verification_status |
|---|---|---|---|---|
| 1 | BREAKOUT_MOMENTUM (breakout-momentum-v1.2.0-gold-calibrated-1week) | GOLD | 1week | **triple-verified** |
| 2 | TREND_PULLBACK (trend-pullback-v1.0.0) | BNB | 12h | **verified — sample-limited** |
| 3 | COINTEGRATION_PAIRS (cointegration-pairs-v1.0.0) | BTC-ETH | 12h | **verified — weakest, live-proving** |
| 4 | BREAKOUT_MOMENTUM (breakout-momentum-v1.6.0-silver-calibrated-24h) | SILVER | 24h | promising-watchlist — forward-testing, not verified |
| 5 | TREND_PULLBACK (trend-pullback-v1.5.0-silver-calibrated-24h) | SILVER | 24h | promising-watchlist — forward-testing, not verified |
| 6 | VOLATILITY_SQUEEZE (volatility-squeeze-v1.1.0-ma200-silver-calibrated-24h) | SILVER | 24h | promising-watchlist — forward-testing, not verified |
| 7 | VOLATILITY_SQUEEZE (volatility-squeeze-v1.1.0-ma150-silver-calibrated-24h) | SILVER | 24h | promising-watchlist — forward-testing, not verified |
| 8 | VOLATILITY_SQUEEZE (volatility-squeeze-v1.1.0-ma100-silver-calibrated-24h) | SILVER | 24h | promising-watchlist — forward-testing, not verified |
| 9 | NEWS_SENTIMENT (news-sentiment-v1.0.0) | GOLD | daily | forward-test-only, no historical backtest |
| 10 | NEWS_SENTIMENT (news-sentiment-v1.0.0) | BTC | daily | forward-test-only, no historical backtest |
| 11 | ORDERFLOW_IMBALANCE (orderflow-imbalance-v1.0.0) | BTC | every run | experimental — snapshot-based, forward-testing only, no backtest exists |
| 12 | ORDERFLOW_IMBALANCE (orderflow-imbalance-v1.0.0) | ETH | every run | experimental — snapshot-based, forward-testing only, no backtest exists |

## Counts

- **Verified: 3** (BREAKOUT_MOMENTUM/GOLD, TREND_PULLBACK/BNB, COINTEGRATION_PAIRS/BTC-ETH)
- **Watchlist (promising, not verified): 5** (all SILVER, Asset Expansion Phase A)
- **Experimental / forward-test-only (no backtest exists at all): 4** (NEWS_SENTIMENT x2, ORDERFLOW_IMBALANCE x2)
- **Total live configs: 12**

## Deferred this batch (not counted above — not wired)

4 RMR watchlist configs (RANGE_MEAN_REVERSION v1.0.0 GOLD/1week and SILVER/1week,
RMR_LONG_ONLY_BTC_1D, RMR_CONFIRMATION_BTC_1D) — see the deferral report for the
full reasoning and the ready-to-use status strings for whenever the underlying
replay-machinery gap is closed in a future, separately-scoped task.

## R1 (REGIME_TRANSITION) — explicitly excluded from consideration

Per the task's own instruction, R1's watchlist configs (ETH/4h, ETH/1d, EURUSD/1d —
see `docs/ranging_regime_batch_r1_regime_transition.md`) are NOT candidates for
wiring in this or any batch: that strategy family's mechanism was refuted across
three independent tests in the Ranging-Regime Research Batch (R1 itself DIED on
11/14 configs; R2 showed more regime-filtering doesn't help; R3 showed regime-gating
doesn't transfer to established survivors). Its watchlist entries remain documented
in the research report only, never promoted toward live wiring.
