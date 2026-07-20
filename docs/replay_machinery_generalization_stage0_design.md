# Replay Machinery Generalization — Stage 0 Design Proposal

## Where behavior actually lives (and where it doesn't)

`nero_core/strategies/registry.py`'s `StrategyRegistry` holds exactly one thing per
`(strategy_id, version)`: an immutable parameter dict + description
(`StrategyVariant`). **It has no behavior-dispatch capability at all** — no function
references, no state-class binding. Per-strategy-family behavior (which
`add_indicators`/`evaluate_entry`/`size_entry` to call) already lives entirely in
`tools/backtest_compare.py`'s hand-maintained `VariantSpec` dataclass + `VARIANT_SPECS`
dict. **That is the correct, pre-existing extension point** — this generalization
extends `VariantSpec`, not the registry.

## The three confirmed blockers, and how each resolves

1. **State field mismatch** (`tests.test_live_wiring_rmr_watchlist_deferral.
   StateClassMismatchTest`): `nero_core/execution/replay.py`'s
   `replay_single_asset_events` hardcodes `state = MeanReversionState(equity=...)`.
   RANGE_MEAN_REVERSION needs `RangeMeanReversionState.consecutive_high_adx_bars`.
   **Fix**: add `state_factory: Callable[[float], Any]` to `VariantSpec`, defaulting
   to `lambda equity: MeanReversionState(equity=equity)` (byte-identical to today's
   hardcoded line for every existing spec, since no existing spec entry needs to set
   this field). New RMR specs set `state_factory=lambda equity:
   RangeMeanReversionState(equity=equity)`.

2. **Exit logic mismatch / crash risk** (`ExitLogicMismatchTest`): the hardcoded call
   is `nero_core.strategies.mean_reversion.evaluate_exit`, which reads
   `trade.target` — a field RANGE_MEAN_REVERSION's `OpenTrade` doesn't have (its
   profit exit is a floating SMA20 cross, recomputed every candle, never stored).
   **Fix**: add `evaluate_exit_fn: Callable[[pd.Series, Any, Any], Any]` to
   `VariantSpec`, defaulting to the currently-imported `mean_reversion.evaluate_exit`
   (again byte-identical for every existing spec). New RMR specs set
   `evaluate_exit_fn=range_mean_reversion.evaluate_exit` — its own, correct exit
   logic (ADX regime-break, SMA20 reversion target, short-side P&L). **No OpenTrade
   dataclass changes anywhere** — each strategy's own `OpenTrade` shape stays exactly
   as registered; making the exit function pluggable means the RIGHT function reads
   the RIGHT shape, instead of forcing one shape through the wrong function.

3. **Direction-less sizing** (`EntrySignatureMismatchTest`): `size_entry_fn`'s
   contract is `(candle, state, params)` — no way to pass `direction`, so
   RANGE_MEAN_REVERSION's bidirectional (LONG/SHORT) `size_entry(candle, state,
   params, direction)` can't be called correctly. **Fix**: add
   `direction_aware_sizing: bool = False` to `VariantSpec` (default False — zero
   changes to any of the 17 existing dict entries). The call site branches: when
   `False` (every existing spec), call `size_entry_fn(candle, state, params)` exactly
   as today; when `True` (new RMR specs only), call `size_entry_fn(candle, state,
   params, direction)` where `direction = getattr(evaluation, "direction", "LONG")`.
   Every existing strategy's own `EntryEvaluation` (BREAKOUT_MOMENTUM, TREND_PULLBACK,
   MEAN_REVERSION, VOLATILITY_SQUEEZE — confirmed by reading each dataclass) has no
   `.direction` field, so this `getattr` default is inert for them; RANGE_MEAN_
   REVERSION's own `EntryEvaluation` already carries `.direction`, so it flows through
   correctly. This is a flag, not a signature change to any existing lambda — zero
   edits needed to the 17 existing `VARIANT_SPECS` entries.

4. **Confirmation variant's 2-candle lookback** — not actually a 4th blocker
   requiring special-cased replay logic. `replay_single_asset_events` already computes
   `as_of = evaluable.iloc[: i + 1]` on every iteration (for every strategy, not just
   `needs_daily` ones) and passes it into `evaluate_entry_fn`. Since
   `evaluate_confirmation_entry(evaluable, i, state, params)` only ever reads rows
   `i-2` and `i-1` (confirmed by reading its source — no lookahead by construction),
   the substitution `evaluate_confirmation_entry(as_of, len(as_of) - 1, state,
   params)` is **exactly equivalent**, not an approximation: `as_of.iloc[i-2]` and
   `as_of.iloc[i-1]` hold the identical values `evaluable.iloc[i-2]` /
   `evaluable.iloc[i-1]` would. The adapter is a plain lambda, no changes to
   `range_mean_reversion_confirmation.py` itself, and no changes to
   `replay_single_asset_events`'s loop shape beyond the two additions above.

## One more gap found during this investigation (not in the original 3)

`process_single_asset`'s warmup-dropna step reuses `backtest_compare.
INDICATOR_COLUMNS_TO_CHECK = ["rsi", "bb_lower", "ma20", "ma200", "atr",
"breakout_high", "trend_ma", "ma50"]`, filtered to whichever columns are actually
present. RANGE_MEAN_REVERSION's `add_indicators` produces `sma20` and `adx`, neither
of which is in that list — so live replay would evaluate rows the backtest itself
would have dropped as insufficient-warmup. Not a crash (RANGE_MEAN_REVERSION's own
`evaluate_entry`/`evaluate_exit` already defend against NaN internally), but a real
warmup-filtering discrepancy versus the backtest. **Fix**: add `"sma20"` and
`"adx"` to the shared list — purely additive, inert for every existing strategy
(none of them produce those columns).

## Blast radius

- **Modified**: `tools/backtest_compare.py` (3 new `VariantSpec` fields with
  backward-compatible defaults; `INDICATOR_COLUMNS_TO_CHECK` gains 2 entries;
  `run_backtest` gains the same pluggable state/exit/direction wiring
  `replay_single_asset_events` does, for consistency between backtest and live
  paths). `nero_core/execution/replay.py` (`replay_single_asset_events` reads the 3
  new spec fields instead of hardcoding).
- **NOT modified**: `nero_core/strategies/registry.py` (no behavior lives there —
  nothing to change), every existing strategy module (`mean_reversion.py`,
  `breakout_momentum.py`, `trend_pullback.py`, `volatility_squeeze.py`, and their
  calibrated variants), `replay_pairs_events` (COINTEGRATION_PAIRS is untouched by
  this generalization — it already has its own dedicated replay function), any
  `OpenTrade`/state/exit dataclass anywhere.
- **Existing strategies touching the modified code**: all 17 `VARIANT_SPECS` entries
  read through the new default values (byte-identical behavior by construction,
  proven empirically below, not just claimed).

## Verdict: minimal generalization, proceeding to implementation

Three additive fields on one dataclass, all defaulting to today's hardcoded
behavior, plus a 2-entry addition to a warmup-column list. No schema changes, no
new state classes beyond ones that already exist, no changes to any currently-wired
strategy's own module. This is materially smaller than a rewrite — proceeding to
Stage 1 with a concrete before/after equivalence proof for every currently-wired
config before touching anything.
