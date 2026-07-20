# Live Wiring Batch — RMR Watchlist Configs: Deferral Report

**Requested**: wire 4 RMR watchlist configs into the 30-min live scheduler as free
paper-tracking forward-tests (the SILVER precedent — watchlist wiring accrues live
evidence, it does not claim proof):

1. RANGE_MEAN_REVERSION v1.0.0 — GOLD/1week
2. RANGE_MEAN_REVERSION v1.0.0 — SILVER/1week
3. RMR_LONG_ONLY_BTC_1D (range-mean-reversion-v1.1.0-long-only) — BTC/1d
4. RMR_CONFIRMATION_BTC_1D (range-mean-reversion-v1.3.0-confirmation) — BTC/1d

**Result: all 4 are deferred.** Per the task's own explicit instruction ("If any
config's logic doesn't fit the existing replay machinery, defer that one and
report — no bespoke infrastructure in this batch"), a concrete investigation (not
just a design read) found that all four share the same disqualifying
incompatibility with `nero_core.execution.replay.replay_single_asset_events` — the
exact machinery every currently-wired single-asset config
(BREAKOUT_MOMENTUM/TREND_PULLBACK/VOLATILITY_SQUEEZE/MEAN_REVERSION families) goes
through. No live_scheduler.py, replay.py, or export_site_data.py changes were made.

## What was actually tested, not just reasoned about

`replay_single_asset_events` was invoked directly against RANGE_MEAN_REVERSION's own
`add_indicators`/`evaluate_entry`/`size_entry`, wrapped in a `VariantSpec`-shaped
adapter (the same pattern every other single-asset config uses). This surfaced three
independent, compounding blockers — confirmed by reading the actual dataclass fields
and function signatures involved (`tests/test_live_wiring_rmr_watchlist_deferral.py`
locks all three in as executable regression tests):

**1. State class mismatch.** `replay_single_asset_events` hardcodes
`state = MeanReversionState(...)` and a hardcoded, non-pluggable call to
`nero_core.strategies.mean_reversion.evaluate_exit` — never RANGE_MEAN_REVERSION's
own state or its own `evaluate_exit`. RANGE_MEAN_REVERSION's own, CORRECT exit logic
needs `state.consecutive_high_adx_bars` (the ADX regime-break hysteresis counter);
`MeanReversionState` has no such field.

**2. Exit logic mismatch — a real crash risk, not a style nitpick.**
`mean_reversion.evaluate_exit` unconditionally reads `trade.target` (a fixed price
level) to check the profit exit. RANGE_MEAN_REVERSION's `OpenTrade` has NO `target`
field at all — its profit exit (REVERSION_TARGET) is a floating SMA20 cross,
recomputed fresh every candle, never stored on the trade. Wiring RANGE_MEAN_REVERSION
through the hardcoded `mean_reversion.evaluate_exit` would raise
`AttributeError: 'OpenTrade' object has no attribute 'target'` the first time any
trade survives past its entry candle — not an edge case, the normal path. Even
setting the crash aside: `mean_reversion.evaluate_exit` has no ADX regime-break
check, no SMA20 reversion-target check, and no short-side P&L inversion at all — it
is a categorically different exit mechanism. Running RANGE_MEAN_REVERSION's entry
through it would silently execute and log a strategy that is neither v1.0.0 nor
anything ever verified, mislabeled in the Truth Ledger as RANGE_MEAN_REVERSION. That
is disqualifying on its own, independent of the crash.

**3. Entry/sizing signature mismatch.** `VariantSpec.size_entry_fn`'s contract is a
strict 3-argument callable, `(candle, state, params) -> trade`. Every strategy
currently wired through this machinery is long-only or has direction baked into the
entry rule itself, so 3 arguments suffice. RANGE_MEAN_REVERSION's own `size_entry`
takes a required 4th argument, `direction` (`"LONG"` or `"SHORT"`) — it is genuinely
bidirectional. There is no way to thread `direction` through the existing 3-argument
contract without silently hardcoding one side, which would silently drop every SHORT
signal from the ledger rather than fail loudly — confirmed directly by wiring a
hardcoded-`"LONG"` adapter and observing it run without error on data that should
have produced SHORT signals too.

**4. CONFIRMATION variant compounds all three, plus its own timing mismatch.**
RMR_CONFIRMATION_BTC_1D's own entry decision needs a 2-closed-candle lookback
(`evaluate_confirmation_entry(evaluable, i, state, params)`) and executes at the
CONFIRMATION candle's OPEN, not its close — its own bespoke `run_backtest` loop
exists specifically because the standard per-candle loop assumes the decision candle
and the entry candle are the same row. `replay_single_asset_events` makes exactly
that assumption.

**5. A second, independent gap in the site-export layer** (surfaced while auditing,
relevant if any future fix addresses only the replay-layer issues above):
`nero_core.execution.verification_status.verification_status_for` and
`export_site_data._roster_entries()` key a config's status string by
`(strategy_id, asset)` only — dropping `strategy_version`. RMR_LONG_ONLY_BTC_1D and
RMR_CONFIRMATION_BTC_1D are both `("RANGE_MEAN_REVERSION", "BTC")` under this keying
scheme; wiring both as separate `SingleAssetConfig` entries would make them silently
share (and the later-registered one silently overwrite) the same status string in
`strategies.json`, even though `build_stats_export`'s own trade-stats keying (which
DOES include `strategy_version`) would keep their actual P&L numbers correctly
separate. This would need its own fix (a version-aware verification-status key)
before both BTC/1d variants could be wired side by side — out of scope for "no
bespoke infrastructure in this batch," documented here so it isn't rediscovered from
scratch.

## Nothing else in this batch changed

No `SingleAssetConfig` entries were added. No `verification_status.py` entries were
added (the 3 honest status strings the task specified are recorded below, ready to
use the moment a future fix closes the replay-machinery gap, but they are not yet
live anywhere). No ntfy/`docs/site_data` export changes — there is nothing new for
either to pick up. `tests/test_live_wiring_rmr_watchlist_deferral.py` (4 tests, all
passing) locks in the current, unwired state and the specific technical reasons for
it, so this deferral is a documented, intentional decision — not a silently stalled
task — and so the test suite itself will flag when a future replay-machinery
generalization makes revisiting this batch worthwhile.

## Status strings, ready for whenever this is revisited

- `("RANGE_MEAN_REVERSION", "GOLD")`: "watchlist — forward-testing, not verified
  (band-timing beat random both halves; N below 20-trade bar)"
- `("RANGE_MEAN_REVERSION", "SILVER")`: same string as GOLD (1week config).
- BTC/1d long-only: "watchlist — forward-testing, not verified (mechanism-backed,
  LOW SAMPLE, CI crosses zero, 1d grid-shift structurally unavailable)"
- BTC/1d confirmation: "watchlist — forward-testing, not verified (68%
  reversion-target exit rate vs 32% baseline; LOW SAMPLE, CI crosses zero, 1d
  grid-shift structurally unavailable)"

## What a real fix would look like (not built here, by instruction)

`replay_single_asset_events` (and `tools/backtest_compare.run_backtest`, which has
the identical hardcoding) would need to accept a pluggable state-factory and a
pluggable `evaluate_exit_fn` per `VariantSpec`, the same way `add_indicators_fn`/
`evaluate_entry_fn`/`size_entry_fn` already are — and `size_entry_fn`'s contract
would need to grow an optional `direction` parameter (defaulting to a no-op for
today's long-only variants). `verification_status_for` would need `strategy_version`
added to its key. Each of these is a real, scoped, generalizing change to shared
infrastructure — exactly what this batch's own instruction ruled out building now.
If the user wants RANGE_MEAN_REVERSION's watchlist configs live, that
generalization is the right next task to scope, separately from a "just wire these
4" batch.
