# PEAD Diagnostic — GOOGL/TSLA 2026-07-22 Earnings Producing Zero Signals

## The question

GOOGL and TSLA reported earnings on 2026-07-22. By 2026-07-26, PEAD's
`signal_counts` for both tickers showed all zeros (ENTRY: 0, EXIT: 0, WATCH: 0,
NO_TRADE: 0), despite PEAD being correctly registered and verified. Investigated
directly against live data and the actual evaluation code — **this was a real bug,
not vendor lag, and it is now fixed.**

## Step 1 — is the EPS data actually available?

Queried `yf.Ticker(...).get_earnings_dates()` directly, live, for both tickers:

| Ticker | Announcement | EPS Estimate | Reported EPS | Surprise |
|---|---|---|---|---|
| GOOGL | 2026-07-22 16:00 ET | 2.90 | 9.11 | **+214.23%** |
| TSLA | 2026-07-22 16:00 ET | 0.54 | 0.33 | **-38.35%** |

Both fully resolved (estimate + actual both present), both far beyond even the
strictest wired threshold (8%). `fetch_earnings_surprises` (which drops any row
missing either value) correctly returns both rows. **No data-availability
problem, no vendor lag, no swallowed exception in the fetch path.**

## Step 2 — trace the actual evaluation function

Called `build_entry_plan` directly with the live-fetched events and candles:
it correctly identifies both events, computes the right direction (LONG for
GOOGL, SHORT for TSLA) and the right entry candle (the first trading day
strictly after the announcement, 2026-07-23) for every wired config
(3%/hold10, 8%/hold10). The entry plan itself was never the problem.

Stepping through `replay_pead_events`'s actual replay loop (the exact function
`process_pead_config` calls every day) against the live data surfaced **two
independent, compounding bugs**, both in code that is shared between backtesting
and the live path:

### Bug 1 — `find_account_start_index`'s "fresh account" rule doesn't fit PEAD

`nero_core/execution/replay.py`'s module docstring documents the shared replay
convention: on a brand-new account (`inception_close_time_ms is None`, i.e.
nothing has ever been logged for this exact `(strategy_id, strategy_version,
asset)` triple), start at the **newest closed candle only** — never backfill a
fake trading history — and states "a missed/delayed run self-heals on the next
one."

That self-healing claim is true for every continuously-evaluated, candle-driven
strategy (BREAKOUT_MOMENTUM, TREND_PULLBACK, etc.): if today's run misses a
setup, tomorrow's candle is a fresh, independent look. It is **false for PEAD**:
an earnings announcement is a one-time calendar event, not a recurring
per-candle opportunity. `earliest_logged_candle_timestamp('PEAD', <version>,
'GOOGL'/'TSLA')` confirmed both tickers have **zero rows ever logged** for
either wired version — genuinely their first live evaluation. Because that
first evaluation didn't happen to land exactly on 2026-07-23 (the correct entry
candle), "start at the newest candle only" **permanently and silently** excluded
that one-time entry — there is no future candle that can resurrect it.

### Bug 2 — a backtest-only guard was reused unmodified in the live path

Independent of Bug 1: `_try_open_pead_trade` (shared by `run_pead_backtest_rows`
and `replay_pead_events`) refuses to open a position unless
`holding_window_sessions` **more** candles already exist past the entry candle
in the currently-fetched frame:

```python
if i + params.holding_window_sessions >= n:
    return None  # insufficient forward history -- discard, not counted either way
```

This is correct and necessary for `run_pead_backtest_rows`, whose contract only
reports fully-resolved `closed_trades` — you don't want a trade you can't yet
verify the outcome of polluting backtest statistics. It is **wrong** for the
live path: `replay_pead_events`/`PeadState` already correctly persist an open
position across separate scheduler runs (exactly like every other strategy's
open-position handling) — an exit discovered on a *later* day's run is normal,
not a defect. Reusing this guard unmodified meant a live PEAD entry could never
be recognized until 10 (the wired holding window) **more** trading days had
already elapsed past the true entry candle — at which point it would open using
that much later day's price, defeating the "enter the day after the surprise"
mechanism entirely.

Confirmed empirically: calling `replay_pead_events` with the live GOOGL/TSLA
data and `inception_close_time_ms=None` returned **zero events** before the fix,
for exactly the reasons above (verified via direct manual step-through of the
replay loop, not inference).

## The fix

Both committed in this batch:

1. `replay_pead_events` (`nero_core/execution/replay.py`): when
   `inception_close_time_ms is None`, a fresh PEAD account now starts
   `holding_window_sessions` candles back from the newest, not literally the
   single newest candle — enough to catch a still-relevant recent event, not
   enough to backfill a stale one whose holding window has already fully
   elapsed.
2. `_try_open_pead_trade` (`nero_core/strategies/pead.py`): added a
   `require_full_forward_history` keyword (default `True`, preserving the
   existing, correct backtest behavior unchanged). `replay_pead_events` now
   passes `require_full_forward_history=False`.

Re-ran the exact live GOOGL/TSLA data through the fixed code:

```
GOOGL 3%:  ENTRY LONG  surprise=214.23  ->  EXIT STOP  r_multiple=-1.035
GOOGL 8%:  ENTRY LONG  surprise=214.23  ->  EXIT STOP  r_multiple=-1.035
TSLA  3%:  ENTRY SHORT surprise=-38.35 (still open, no exit yet)
TSLA  8%:  ENTRY SHORT surprise=-38.35 (still open, no exit yet)
```

GOOGL's entry was stopped out at a loss despite the huge EPS beat — plausible
(price didn't follow the earnings surprise; the market may have already priced
in expectations differently, or the beat included a one-time item) and not
itself a bug; reported factually, not adjusted to look better.

Added regression tests (`tests/test_live_wiring_post_batch.py`) for both root
causes independently, so either one regressing again would be caught. Full
suite: 1318 tests, passing.

## What happens next

This is not "wait for NVDA to find out." The next live scheduler run (within 30
minutes, gated by the existing `24h` PEAD schedule) will re-evaluate GOOGL and
TSLA with the fixed code and correctly log the entries (and GOOGL's stop-out
exit) that were silently missed. NVDA's next earnings (2026-08-26) is a good
*additional* confirmation that the fix holds going forward, but it is not the
first test — GOOGL and TSLA's already-resolved 2026-07-22 events are.

## Verdict

**Real bug — fixed, not vendor lag.** Two independent, compounding defects, both
in code shared between backtesting and live execution, both specific to PEAD's
event-driven (not continuously-evaluated) mechanics. Neither affects any other
strategy in the codebase.
