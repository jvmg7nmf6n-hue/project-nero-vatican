# execution_log.data_source — migration plan (NOT YET APPLIED)

## Status

This is a **plan only**. The `ALTER TABLE` below has been verified against a scratch
copy of the live database (see "Verification performed" below) but has **not** been
applied to `data/truth_ledger.db`. Applying it to the live file is a separate,
explicitly-approved step, following the same two-commit pattern used for the prior
`news_sentiment_log.strategy_version` migration (commits `3643de5` + `45e865d`):
a dedicated migration commit touching only the database file, then a companion code
commit. This document accompanies the code commit; the migration commit comes later.

## Why

`tools.timeframe_data.fetch_timeframe_candles` already computes an honest, descriptive
market-data provenance string per fetch (e.g. `"NATIVE: Twelve Data XAG/USD daily
candles"` vs `"NATIVE: YFinance SI=F (continuous futures proxy, not spot) daily
candles"`), but `nero_core.execution.live_scheduler.process_single_asset` discarded it
(`candles, _source = fetch_result`) before it ever reached `execution_log`. This is the
confirmed mechanism behind the SILVER incident: when `TWELVE_DATA_API_KEY` was absent,
SILVER strategies silently fell through to a YFinance continuous-futures-proxy
substitute with zero record of the substitution anywhere in the ledger or any
`docs/site_data/*.json` export.

## Existing-column check (done first, per instruction)

`execution_log.reasoning` (`nero_core/truth_ledger/execution_log.py`, `_SCHEMA`) was
considered and rejected as a place to fold this in: it already carries strategy
decision-rationale text (e.g. `"CLOSE_NOT_ABOVE_BREAKOUT_HIGH, ..."`) constructed
independently by ~30 different strategy modules with no shared format. Appending
source info there would (a) conflate two unrelated concerns in one unstructured
string, (b) require regex extraction to ever query it later (the same fragility this
codebase already tolerates for `r_multiple` embedded in EXIT reasoning, but doesn't
need to add to a second field), and (c) require touching every strategy's own
reasoning-construction code, not one centralized insert path. No other existing
column in `execution_log` represents data provenance. A new column is the right call.

## The migration

```sql
ALTER TABLE execution_log ADD COLUMN data_source TEXT;
```

- Nullable, no `DEFAULT`. Every row inserted before this column existed gets `NULL` —
  which source actually served a historical row is genuinely unrecoverable, so `NULL`
  is the honest value. Unlike the `strategy_version` migration (which could safely
  backfill all 4 pre-existing rows to `news-sentiment-v1.0.0` because every one of them
  predated the LLM variant's existence, making the backfill value unambiguous), there is
  no equivalent safe backfill here — we cannot know in hindsight whether a given
  historical GOLD/SILVER row came from Twelve Data or a fallback. No value is fabricated
  in either direction.
- Widens nothing else: the existing `UNIQUE (asset, strategy, strategy_version,
  candle_timestamp, signal_type)` constraint is untouched.

## Verification performed (against a scratch copy only)

1. Copied `data/truth_ledger.db` to a scratch path.
2. Applied the `ALTER TABLE` above to the copy.
3. Confirmed via `PRAGMA table_info(execution_log)` that `data_source` is present,
   nullable, no default.
4. Confirmed `SELECT COUNT(*) FROM execution_log` is unchanged before/after.
5. Confirmed every pre-existing row's other 12 columns are byte-for-byte unchanged
   (`SELECT id, run_id, timestamp, strategy, strategy_version, asset, signal_type,
   entry_price, exit_price, reasoning, candle_timestamp, created_at FROM execution_log`
   diffed old vs. new copy — identical).
6. Confirmed every pre-existing row's new `data_source` column reads back `NULL`.
7. Inserted one new test row with a real `data_source` value via
   `insert_execution_log_row(..., data_source="NATIVE: test")` against the copy and
   confirmed it round-trips correctly through `list_execution_log`.
8. Confirmed the existing `UNIQUE` constraint still rejects a duplicate
   `(asset, strategy, strategy_version, candle_timestamp, signal_type)` insert
   (`sqlite3.IntegrityError`, `insert_execution_log_row` returns `None`) unchanged from
   before the migration.

The scratch copy was discarded after verification; it was never committed.

## What ships in this commit vs. what still needs the live migration

The code in this commit (`ExecutionLogRow.data_source`, `insert_execution_log_row`'s
new optional `data_source` parameter, `list_execution_log` / `list_execution_log_for_run`
selecting the new column, and `process_single_asset` now passing its fetch's real
source through) is **written against the post-migration schema**. Until the `ALTER
TABLE` above is actually applied to `data/truth_ledger.db`, every `execution_log`
insert against the live database will fail with `sqlite3.OperationalError: no such
column: data_source`. This mirrors the historical precedent's dependency order exactly
(migration commit before the code commit could safely run live) but is intentionally
reversed here per this task's scope (code first, migration plan only, migration
applied as its own later approved step) — **do not merge/deploy this commit against
the live database until the migration has been applied separately.**

## Scope of what's wired vs. not

`process_single_asset` (the `SINGLE_ASSET_CONFIGS` path — the majority of strategies,
and the exact path responsible for the confirmed SILVER incident) is wired in this
commit. Three other call sites in `nero_core/execution/live_scheduler.py` discard the
same `fetch_timeframe_candles` provenance string with the identical pattern
(`process_pairs`, `process_gold_silver_ratio` — both at the point they call
`fetch_timeframe_candles(...)` and unpack with `_`) and are **not** wired here. Same
mechanical fix, deliberately left as a follow-up to keep this commit's diff and test
surface reviewable in one pass.
