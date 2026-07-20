# Replay Machinery Generalization — Closing Report

Four commits: Stage 0 design proposal, the generalization itself (Stage 1), live
wiring + test replacement (Final Stage), and this closing report. Full detail in
`docs/replay_machinery_generalization_stage0_design.md`,
`docs/live_wiring_batch_rmr_watchlist_deferral.md` (what was deferred and why,
before this batch), and the commit messages themselves.

## Stage 0 design, as built

Exactly as proposed — no deviation during implementation:

- `tools/backtest_compare.py`'s `VariantSpec` gained 3 additive fields:
  `state_factory`, `evaluate_exit_fn`, `direction_aware_sizing` — all defaulting to
  the exact hardcoded behavior every one of the 17 pre-existing entries relied on.
  Zero edits to any of those 17 entries.
- `nero_core/execution/replay.py`'s `replay_single_asset_events` (and
  `backtest_compare.run_backtest`, kept consistent with it) now read
  `spec.state_factory(...)` / `spec.evaluate_exit_fn(...)` instead of hardcoding
  `MeanReversionState(...)` / `mean_reversion.evaluate_exit(...)`, and branch on
  `spec.direction_aware_sizing` to optionally pass `direction` to `size_entry_fn`.
- `nero_core/strategies/registry.py` — untouched, exactly as predicted (it holds no
  behavior at all).
- The confirmation variant's 2-candle lookback needed no special-cased replay
  logic — `evaluate_confirmation_entry(as_of_intraday, len(as_of_intraday) - 1,
  state, params)` is an exact substitution for `evaluate_confirmation_entry
  (evaluable, i, state, params)`, proven by direct trade-for-trade comparison
  below, not just argued by construction.
- No `OpenTrade`/state dataclass changes anywhere, for any strategy.
- One additional gap found and fixed during Stage 1 that Stage 0 didn't originally
  flag as needing a code change: `verification_status_for`'s key was `(strategy_id,
  asset)`, which would have silently collided the two BTC/24h RMR variants onto one
  shared status string. Extended to `(strategy_id, strategy_version, asset)` — a
  small, contained, necessary addition to the design.

## Before/after equivalence proof for existing strategies

Not claimed by argument — captured and diffed twice:

1. Fetched real candle data ONCE for all 7 pre-existing `SingleAssetConfig`
   entries (GOLD/1week BREAKOUT_MOMENTUM, BNB/12h TREND_PULLBACK, 5x SILVER/24h),
   cached it, so both runs replay against byte-identical inputs.
2. Ran `replay_single_asset_events` from each account's full inception (not just
   the newest candle — thousands of ENTRY/EXIT/NO_TRADE events per config) BEFORE
   touching any code. `diff before.json after.json` after the Stage 1 refactor:
   **byte-for-byte identical** — same event count, same signal types, same entry/
   exit prices, same final equity, for all 7 configs.
3. Re-ran the identical check again at the fully-implemented final state (after
   live wiring + all test fixes): **still byte-for-byte identical.**

Additionally, for the 4 newly-wired RANGE_MEAN_REVERSION configs specifically (no
prior behavior to preserve, but correctness still needed proving, not assuming):
ran each module's own bespoke `run_backtest` against the new generic adapter path
on the same 3000-candle synthetic dataset. v1.0.0 (GOLD-calibrated): 89 trades,
every single trade matching exactly (net_pnl, exit_reason, exit_price). Long-only:
38 trades, exact match. Confirmation: 52 trades, exact match. Separately confirmed
both LONG (38) and SHORT (51) directions are genuinely opened over the same
dataset — proving `direction_aware_sizing` threads SHORT signals through correctly
rather than silently dropping them, which was the whole point of that flag.

## Configs wired: all 4, none still deferred

Every config requested in the original Live Wiring Batch is now live:

| Config | Asset/Timeframe | Registered version |
|---|---|---|
| RANGE_MEAN_REVERSION v1.0.0 | GOLD / 1week | range-mean-reversion-v1.0.0 |
| RANGE_MEAN_REVERSION v1.0.0 | SILVER / 1week | range-mean-reversion-v1.0.0 |
| RMR_LONG_ONLY_BTC_1D | BTC / 24h | range-mean-reversion-v1.1.0-long-only |
| RMR_CONFIRMATION_BTC_1D | BTC / 24h | range-mean-reversion-v1.3.0-confirmation |

No config needed further deferral — the generalization closed all three original
blockers (state, exit logic, direction-less sizing) plus the confirmation
variant's timing, for all four requested configs simultaneously.

## Updated live roster

**16 configs live** (was 12 before this batch):

- **Verified: 3** (unchanged) — BREAKOUT_MOMENTUM/GOLD, TREND_PULLBACK/BNB,
  COINTEGRATION_PAIRS/BTC-ETH.
- **Watchlist (promising, not verified): 9** (was 5) — 5 SILVER Phase A configs +
  4 new RANGE_MEAN_REVERSION configs (GOLD/1week, SILVER/1week, BTC/24h long-only,
  BTC/24h confirmation), each with its own specific, honest status string (band-
  timing-beat-random for the two 1week configs; mechanism-backed/LOW-SAMPLE/CI-
  crosses-zero for long-only; 68%-vs-32%-exit-mix/LOW-SAMPLE/CI-crosses-zero for
  confirmation — all four "1d grid-shift structurally unavailable" where
  applicable).
- **Experimental / forward-test-only (no backtest exists at all): 4** (unchanged)
  — NEWS_SENTIMENT x2, ORDERFLOW_IMBALANCE x2.

R1 (REGIME_TRANSITION)'s watchlist configs remain correctly excluded — that
family's mechanism was refuted across three independent tests and stays
documented in the research report only, never a wiring candidate.

## Test count

**1139 tests, all passing** (was 1131 before this batch: +4 new
`test_live_wiring_rmr_watchlist.py` tests net of -4 deleted obsolete deferral
tests, +4 updated existing tests fixed for the grown roster, plus incidental
fixture fixes). Full suite runtime dropped from an initial ~290s (during
mid-refactor, caused by a missing test fixture entry silently retrying against
real `time.sleep`) back down to ~60s once the fixture gap was closed — confirmed
not to be a symptom of the generalization itself, but of an incomplete test
fixture update caught and fixed in the same stage.
