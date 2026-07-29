# execution_log quarantine — migration plan (NOT YET APPLIED)

## Status

This is a **plan only**, describing a possible future durable alternative to the
documented-cutoff quarantine actually shipped in `nero_core/execution/quarantine.py`.
No `ALTER TABLE` in this document has been run against any copy of the database, live
or scratch — this plan has not even been verification-tested yet, unlike the
`data_source` migration plan it follows the format of. Applying it is a separate,
explicitly-approved future step, if the documented-cutoff approach turns out to be
insufficient (see "Why the cutoff approach was chosen instead, for now" below).

## Why

2026-07-29 orderflow-verification investigation confirmed: before commit `c106b8d`
("fix Binance 451 bug", 2026-07-28T05:33:53Z), `ORDERFLOW_IMBALANCE`'s BTC/ETH 1h
candle fetches were silently falling through Binance → Coinbase/Kraken on essentially
every GitHub Actions run (api.binance.com 451s US runner IPs). Because ENTRY and EXIT
are logged by two independent scheduler runs, not one atomic transaction, a trade's
entry and its own exit could legitimately have been priced off two different
exchanges — not a valid paper-traded round trip. 23 of 27 BTC and 23 of 25 ETH
resolved `ORDERFLOW_IMBALANCE` trades (as of this investigation) predate the fix and
cannot be trusted for statistical evaluation (bootstrap CI, win rate, etc.).

`nero_core/execution/quarantine.py`'s `QUARANTINE_CUTOFFS` dict + `is_quarantined`/
`exclude_quarantined`/`list_clean_execution_log` implement the exclusion today, against
the CURRENT schema, no migration needed. This document exists so the more durable
column-based alternative is written down rather than lost, in case the cutoff approach
proves insufficient later (see below).

## Why the cutoff approach was chosen instead, for now

- **No schema risk today.** The cutoff constants work immediately against the live
  `data/truth_ledger.db` with zero `ALTER TABLE`, zero migration-ordering dependency,
  and zero risk of the "code ships before the live migration lands" failure mode the
  `data_source` migration plan explicitly had to sequence around.
- **The incident is fully bounded and already known.** Both cutoffs
  (`QUARANTINE_CUTOFFS` in `quarantine.py`) were derived once, from a confirmed,
  closed investigation — there's no ongoing process that needs to keep marking new
  rows quarantined going forward (Task 1 of the same investigation wired
  `data_source` into `process_orderflow_imbalance`, so future rows carry real
  provenance directly and don't need cutoff-based inference at all).
- **A column doesn't remove the need to know the cutoff logic anyway.** Even with a
  `quarantined BOOLEAN` column, *populating* it correctly still requires the exact
  same candle_timestamp-boundary reasoning encoded in `quarantine.py` today — the
  column would just cache that function's output instead of computing it at read
  time. For two constants and ~50 affected rows, the caching isn't currently worth
  the migration-ordering risk.

## When a column WOULD be worth it

If quarantine logic needs to cover more strategies/incidents in the future (this one
is scoped narrowly to `ORDERFLOW_IMBALANCE`/BTC/ETH), or if `QUARANTINE_CUTOFFS`
grows past a handful of entries, or if quarantine status needs to be queryable
directly in SQL (e.g. from `docs/site_data/*.json` export scripts) rather than only
through `nero_core.execution.quarantine`'s Python filter, a column becomes the better
tradeoff. The migration would look like:

```sql
ALTER TABLE execution_log ADD COLUMN quarantined INTEGER NOT NULL DEFAULT 0;
```

- `INTEGER` (0/1), not `BOOLEAN` — SQLite has no native boolean type; this matches
  no other column in this schema needing the distinction today, so there's no
  existing convention to break.
- `NOT NULL DEFAULT 0` (not nullable like `data_source`) is deliberate here, unlike
  the `data_source` migration: "quarantined or not" is a computable fact for every
  row (apply `is_quarantined` from `quarantine.py` once, at migration time, to every
  existing row), not a genuinely-unrecoverable-for-old-rows value the way "which
  exchange served this candle" was. A backfill pass would run
  `nero_core.execution.quarantine.is_quarantined` against every pre-existing row and
  set the column accordingly — this is a legitimate backfill, not a fabrication,
  because the boundary logic is deterministic and already verified against the data.
- New inserts would need `process_orderflow_imbalance` (and any future quarantine-
  aware caller) to compute and pass `quarantined=...` at insert time, mirroring how
  `data_source` is passed today.

## Verification this document does NOT claim

Unlike `docs/execution_log_data_source_migration_plan.md`, this plan has **not** been
tested against a scratch copy of the database. If this path is chosen later, that
verification (row-count parity, byte-for-byte diff of untouched columns, UNIQUE
constraint behavior, round-trip insert) must be performed first, following the exact
checklist in that document.
