# Website D6 — Signals feed + push alerts

Date: 2026-08-07. CC-1 comprehensive directive, Parts D6/D6a/D6b/D6c.

## D6a — the exact ENTRY-event definition, confirmed before building

A genuine Forward Trial ENTRY is **an `execution_log` row, in
`data/repair_lab_forward_tracking.db` (a SEPARATE database file from
`data/truth_ledger.db` — confirmed via
`nero_core.research_agent.repair_forward_tracker.DEFAULT_FORWARD_TRACKING_DB_PATH`),
whose `strategy` column matches `TRIAL:<trial_id>` and whose `signal_type`
is `"ENTRY"`.**

Traced precisely: `nero_core/research_agent/trial.py::run_forward_tick`
calls `repair_forward_tracker.evaluate_forward_tick(..., strategy_prefix=
TRIAL_STRATEGY_PREFIX)` (`TRIAL_STRATEGY_PREFIX = "TRIAL"`), which reconstructs
whether a position is already open purely from that trial's own prior
`execution_log` rows and only ever logs `"ENTRY"` when it finds none — so
every such row is, by construction, a genuine flat-to-open transition, never
re-derived or inferred by this directive's own new code.

**This is explicitly NOT the same thing as `forward_trial.json`'s
`status == "OPEN"` / `opened_at` fields**, shown elsewhere on `/factory-loop`
— those reflect TRIAL ADMISSION (a hypothesis being accepted into the queue),
not a live market position. Confirmed with real numbers, not asserted: as of
this export, `forward_trial.json` lists **10** Trial records, all sharing
one identical `opened_at` batch timestamp and `status: "OPEN"`, but
`repair_lab_forward_tracking.db`'s `execution_log` has exactly **1** real
`TRIAL:` `ENTRY` row — `TRIAL:7f7c5980-...`, ETH, matching
`ETH_BIDIRECTIONAL_ZSCORE_FADE`, the exact example the directive itself
named. 9 of 10 admitted hypotheses have never actually opened a position.

## Real, pre-existing, OUT-OF-SCOPE finding: a local path leak

While tracing this, found that `docs/site_data/forward_trial.json` already
publicly exports each record's `forward_tracking_db_ref` as a **full local
absolute filesystem path**
(`C:\Users\<username>\...\data\repair_lab_forward_tracking.db`) — this is
live on the public site today, leaking the machine's local username and
directory layout. Not a "secret" in the API-key sense, but an unintended
information disclosure that predates this directive and is unrelated to
Part D/E's own scope (fixing it means editing whichever export currently
writes `forward_trial.json`, a `nero_core` change outside "website-layer
only"). **Not fixed here** — flagged for a separately-scoped follow-up.
The new export this directive DOES add
(`nero_core/execution/export_trial_entries.py`) deliberately never
includes any local path, tested directly
(`test_never_leaks_a_local_filesystem_path`).

## What shipped

- **`nero_core/execution/export_trial_entries.py`** (new, read-only export,
  same discipline as `export_site_data.py`): reads
  `repair_lab_forward_tracking.db`'s `execution_log` for `TRIAL:` `ENTRY`
  rows, cross-references `forward_trial.json` for `hypothesis_name`/
  `origin_agent`, and `docs/site_data/{agent_hypotheses,eve_hypotheses}.json`
  for `asset`/`timeframe` (needed so the website can fetch the right candle
  file) — all already-exported site data, never raw internal session files.
  Writes `docs/site_data/trial_entries.json`. 7 new tests, including: real
  entries included with full context; non-`TRIAL:` strategies (e.g.
  `ORDERFLOW_IMBALANCE`, `REPAIR_LAB_ATTEMPT:`) excluded; `EXIT`/`NO_TRADE`
  rows for the same trial excluded even though they share the strategy key;
  a second genuine re-entry after an exit correctly produces a second,
  distinct event (never deduplicated by `trial_id` alone); missing
  hypothesis context degrades honestly (fields become `null`, the row is
  never dropped); the local-path-leak regression guard above.
- **`website/app/signals/page.tsx`** (new): lists every real entry, most
  recent first, with hypothesis name, asset, direction, entry/stop/target,
  origin agent, and a `CandlestickChart` (D2's `ma`/`ema` overlays on by
  default) with the real `ENTRY` marker at the entry's own candle. Honest
  empty state when zero entries exist (today's real state) and a per-entry
  "chart coming soon" fallback when candle data isn't available for that
  asset/timeframe. `website/lib/types.ts`/`lib/data.ts` get `TrialEntry`/
  `fetchTrialEntries`, `app/layout.tsx` gets the nav link. 5 new tests.
- **`signal_alerts.js`** (new, repo root, per the directive's own file
  placement) + **`.github/workflows/signal_alerts.yml`** (new): runs the
  Python export, then checks `docs/site_data/trial_entries.json` for
  entries not yet in `signal_alerts_state.json`, pushes one ntfy
  notification per new entry, commits the updated state file back.

## One deliberate, reasoned deviation from "port near-verbatim"

The given `btc-monitor-main` skeleton's `COOLDOWN_MS = 2 * 3600 * 1000` +
"prune state entries older than 7 days" exists to debounce a
**continuously-polled** condition (a live price threshold that can stay
true across many ticks). A Forward Trial ENTRY is the opposite shape: a
**discrete, already-logged, immutable historical fact** — one
`execution_log` row, forever, read from an append-only, ever-growing JSON
export every run. Applying a 7-day-expiry cooldown here would be actively
wrong: once an old entry's cooldown/retention expired, the SAME historical
entry (still present in the feed) would fire a second, spurious alert.
`signal_alerts.js` therefore dedupes by `execution_log_id` **permanently**
(no expiry) — the state-file MECHANISM (a small local JSON map, checked
before pushing, updated after) is unchanged from the original pattern;
only the retention policy is adapted to fit a once-ever event instead of a
debounced continuous one. Documented in the script's own header, not a
silent drift.

## D6c — secret handling, confirmed

`NTFY_TOPIC` is read via `process.env.NTFY_TOPIC` only, sourced from
`secrets.NTFY_TOPIC` in the workflow YAML. `signal_alerts.js` never prints,
logs, or interpolates the topic value anywhere — confirmed by direct
inspection of every `console.log` call in the file: the one presence check
(`NTFY_TOPIC not set (length: 0)`) is a hardcoded literal, not derived from
the actual variable, and fires only in the not-set branch. No `.env` entry
added, matching the directive's own instruction.

## Verification

- Smoke-tested `export_trial_entries.py` against the REAL production
  `repair_lab_forward_tracking.db` (read-only) — correctly produced exactly
  the 1 real entry, matching the directive's own named example
  (`ETH_BIDIRECTIONAL_ZSCORE_FADE`, ETH, SHORT, entry 1916.646594).
- Ran `signal_alerts.js` locally twice in a row (dry run, `NTFY_TOPIC`
  unset): first run reported "1 new alert" and wrote state; second run
  correctly reported "0 new alerts" — confirmed idempotent.
- `next build` compiles; real Playwright screenshot of `/signals` shows
  the honest empty state (correct: the live site's `raw.githubusercontent.com`
  copy of `trial_entries.json` doesn't exist until this commit is pushed),
  zero console errors, nav link present.
- Python: 7 new tests, full scoped run (`test_export_trial_entries`,
  `test_export_site_data`, `test_execution_log`) — 69/69 passing. Confirmed
  no write to either production database (`git status` on both files clean
  before and after every real-data smoke test).
- Website: 660 total tests, 658 passing (2 pre-existing, unrelated
  `siteDataSchema.test.ts` failures, same as every other Part D report this
  session). One real bug caught and fixed in the new
  `signalsPage.test.tsx` itself: `jest.resetAllMocks()` in `afterEach` was
  wiping the shared `lightweight-charts` manual mock's default
  `createChart` implementation (set up once at module load, never
  re-established per test) — the 3rd test in the file, the first to
  actually render a chart, got `undefined` back. Fixed by using
  `jest.clearAllMocks()` instead, which clears call history without
  discarding mock factory implementations.
