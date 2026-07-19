# Live Execution Scheduler — Design

`nero_core/execution/live_scheduler.py` runs every 30 minutes (GitHub Actions cron
`0,30 * * * *`, see `.github/workflows/live_scheduler.yml`) and produces an append-only
audit trail of live paper-tracking signals for the four Phase 1 survivors, plus (as of
the Asset Expansion Phase A follow-up) five SILVER PROMISING-WATCHLIST forward-tests —
see the section below.

## Why these four, and why THIS GOLD version

1. `GOLD` / `1week` / `BREAKOUT_MOMENTUM` **`breakout-momentum-v1.2.0-gold-calibrated-1week`**
2. `BNB` / `12h` / `TREND_PULLBACK` `trend-pullback-v1.0.0`
3. `BTC-ETH` / `12h` / `COINTEGRATION_PAIRS` `cointegration-pairs-v1.0.0`
4. `NEWS_SENTIMENT` (`GOLD`, `BTC`) `news-sentiment-v1.0.0` — forward-test-only, no backtest

The GOLD config was originally requested as `v1.1.0-gold-calibrated`. That version's
`max_holding_hours=24` was never corrected for 1week candles (168h each) — every trade
would be force-exited via the TIME rule at the very next candle, before its stop or
target could ever fire. `v1.2.0-gold-calibrated-1week`
(`nero_core/strategies/breakout_momentum_gold_calibrated_1week.py`) is the corrected
version and is the one that actually produced every GOLD/1week positive-expectancy
result referenced in this project's research phase. Wiring `v1.1.0` live would mean
generating real signals from a configuration with no validated track record at all —
confirmed with the user before building this scheduler.

## SILVER additions (Asset Expansion Phase A follow-up) — NOT survivors

Five more configs were added at the user's explicit request, to forward-test the
Asset Expansion Phase A metals sweep's PROMISING-WATCHLIST candidates and accrue live
evidence (see `docs/metals_phase_a_full_sweep.md`, `docs/metals_grid_shift_verification.md`,
`docs/metals_phase_a_report.md`):

5. `SILVER` / `24h` / `BREAKOUT_MOMENTUM` `breakout-momentum-v1.6.0-silver-calibrated-24h`
6. `SILVER` / `24h` / `TREND_PULLBACK` `trend-pullback-v1.5.0-silver-calibrated-24h`
7. `SILVER` / `24h` / `VOLATILITY_SQUEEZE` `volatility-squeeze-v1.1.0-ma200-silver-calibrated-24h`
8. `SILVER` / `24h` / `VOLATILITY_SQUEEZE` `volatility-squeeze-v1.1.0-ma150-silver-calibrated-24h`
9. `SILVER` / `24h` / `VOLATILITY_SQUEEZE` `volatility-squeeze-v1.1.0-ma100-silver-calibrated-24h`

Unlike the four above, none of these earned SURVIVED status — zero of the 76 Phase A
configs did. Each is positive in both backtest halves with an adequate sample, but
grid-shift verification does not apply at 24h (COMEX/NYMEX daily settlement gap breaks
`resample_hourly_to_grid`'s contract for any 24h bin — a genuine structural property of
exchange-settled futures, not a bug). `nero_core/execution/verification_status.py`
labels all five `"promising-watchlist — forward-testing, not verified"` and
`nero_core/execution/notify_ntfy.py` appends `"(watchlist)"` to their display names, so
this distinction stays visible everywhere a signal from one of them surfaces — never
worded as equivalent to the four proven survivors above.

BOS_CONTINUATION and MACRO_RISK_ON — the two other strategy families the Phase A sweep
also flagged PROMISING-WATCHLIST for SILVER (MACRO_RISK_ON/24h was in fact the
single best-sampled result in the whole sweep) — are NOT wired here. Both have their
own bespoke `evaluate_exit`/`OpenTrade` shapes (direction-aware sizing for BOS,
regime-driven exit for MACRO) incompatible with `replay_single_asset_events`'s hardcoded
call to `nero_core.strategies.mean_reversion.evaluate_exit`. Wiring either live would
require new bespoke replay functions (mirroring `replay_pairs_events`'s existing
precedent) rather than a config addition — a larger, riskier change to code that writes
directly to the Truth Ledger, left as a follow-up rather than rushed in alongside the
five straightforward additions above.

## No persisted mutable state — replay from the ledger, always

Nothing about equity, open positions, or account age is pickled, cached, or written to a
state file between runs. Instead (`nero_core/execution/replay.py`):

- **Inception** = the earliest `candle_timestamp` ever logged to `execution_log` for a
  given `(asset, strategy, strategy_version)`. On the very first run ever for a config,
  there is no inception yet, so the account starts at the **newest currently-closed**
  candle — a fresh deployment never backfills history as if it had been trading all
  along (mirrors `tools/backtest_hypothetical_investment.py`'s "state starts fresh at a
  cutoff" design, just anchored to the ledger instead of a lookback-days parameter).
- Every run replays the **entire** account history from inception to the newest
  evaluable candle, using the exact same `evaluate_entry` / `evaluate_exit` /
  `size_entry` functions backtests use, to deterministically reconstruct `equity` and
  any `open_trade`.
- Only candles strictly **after** the last-already-logged `candle_timestamp` are
  actually inserted. Everything before that is replayed silently, purely to get `state`
  right. A missed or delayed run self-heals on the next one; there is nothing to lose
  and nothing to reconcile.
- `execution_log`'s `UNIQUE (asset, strategy, strategy_version, candle_timestamp,
  signal_type)` constraint is a defense-in-depth backstop — `insert_execution_log_row`
  returns `None` instead of raising if a row already exists, so even a bug in the replay
  cursor logic can't produce a duplicate row.

**Known limitation:** if an account's fetched candle window doesn't reach back far
enough to include its own inception candle (a long-lived account against a bounded
fetch), `find_account_start_index` falls back to the earliest available row instead of
raising — documented here rather than silently reported as full history.

## Timeframe boundary detection (`candle_schedule.py`)

`candle_boundary_due(timeframe, now)` is a cheap, deliberately **generous** pre-filter —
not the source of correctness — that decides whether a config is even worth fetching
this run (so GOLD's weekly strategy isn't re-fetched 48 times a day). Tolerance windows
(40 minutes) are wider than the 30-minute run cadence to absorb realistic GitHub Actions
scheduling delay. The actual "is this a genuinely new signal" gate is always the
replay-vs-ledger comparison above — being wrong in the generous direction here costs one
wasted fetch; being wrong in the strict direction would silently miss a real signal, so
every window errs generous.

`NEWS_SENTIMENT` uses `daily_time_due(hour_utc=19, now)` instead — it isn't tied to any
candle close. Its own dedupe (`has_news_sentiment_logged_today`) prevents a delayed or
retried run within the same UTC day from double-logging.

## No-lookahead guards

- `MarketDataClient` already drops any candle whose `close_time` hasn't passed
  (`_drop_unclosed`) — no in-progress candle ever reaches strategy logic.
- News Sentiment: a headline only counts if its **published** timestamp (parsed via
  `email.utils.parsedate_to_datetime`, never guessed) is at least
  `min_publication_age_hours` (default 2h) before evaluation time
  (`select_eligible_headlines` in `nero_core/strategies/news_sentiment.py`). An
  unparseable or missing published timestamp excludes the headline — never assumed
  eligible. **Signals act on news >= 2h old to avoid lookahead bias.**
- Replay always evaluates candles in chronological order using only `.iloc[:i+1]`
  history slices, matching every existing backtest tool's no-lookahead convention.

## Error-handling taxonomy

`MarketDataClient` collapses every underlying source's failure into one
`MarketDataUnavailableError` carrying a joined message string, not a structured error
type. `classify_market_data_error` in `live_scheduler.py` is therefore a **heuristic**
string-pattern classifier, not a precise one:

- **PERMANENT** (message matches `missing api key` / `unauthorized` / `401` / `403` /
  `invalid api key` / `forbidden`): never retried, recorded straight to
  `errors_encountered` with `classification: "FATAL"`.
- **TRANSIENT** (everything else — the safe default, since retrying a genuinely
  transient failure is harmless and retrying a permanent one just costs a few seconds):
  retried up to 3x with backoff `1s, 3s, 10s`. If still failing, recorded as
  `classification: "FETCH_INCOMPLETE"` and that asset is skipped for this run.
- **DATA_QUALITY**: detected *after* a successful fetch — if indicator warmup leaves
  zero evaluable rows (e.g. not enough history yet), recorded as `classification:
  "DATA_QUALITY"` and skipped. GOLD's Twelve Data feed legitimately reports
  `volume=0.0` for every candle (see `market_data.py`), so zero volume alone is never
  treated as a data-quality signal.
- Any other unexpected exception during a single asset's processing is caught at the
  `run_once` loop level and recorded as `classification: "FATAL"` — it never aborts
  processing for the other assets/strategies in the same run. Partial results (e.g.
  2 of 4 configs logged) are the expected outcome of a partial failure, not an error
  state in themselves.

`main()` never raises: it wraps `run_once()` in a top-level `try/except`, printing a
full traceback to stdout on any unexpected failure and returning normally, so the
GitHub Actions workflow's git-commit step still runs and any rows already inserted
before the failure are not lost.

## Immutable-log principle

`nero_core/truth_ledger/execution_log.py` provides **no update or delete functions** for
`execution_log`, `execution_metadata`, or `news_sentiment_log` — not "update functions
that are unused," but genuinely absent from the module. Corrections happen by inserting
a new row (e.g. a later run's replay naturally produces the correct EXIT event once real
data confirms it), never by rewriting a prior run's history. `execution_metadata` is
inserted exactly once per run, at the very end, after all per-asset processing has
completed (successfully or not) — so a run's summary always reflects what actually
happened, and per-asset `execution_log` rows (inserted incrementally as each asset
completes) survive even if a later asset in the same run crashes.

## Persistence

`data/truth_ledger.db` (a single SQLite file, not `.gitignore`d) holds the prediction
ledger and all three execution tables. The GitHub Actions workflow commits it back to
the repo after each run, the same pattern `.github/workflows/nero-prediction-lab.yml`
already uses for its CSV outputs. A `concurrency` group on the workflow (see
`.github/workflows/live_scheduler.yml`) prevents overlapping runs from racing on the
git push.
