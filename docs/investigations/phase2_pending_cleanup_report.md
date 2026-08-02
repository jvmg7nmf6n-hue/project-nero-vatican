# Phase 2 Pending Cleanup — Closing Report

**Branch:** `feature/phase2-pending-cleanup`, branched fresh from `origin/main`
at **`6512b1f`**. Pushed to origin; **not merged into main**.

**ROLE NOTE (per this session's own instruction, same as the two branches
before it):** authored by CC-1 as a one-off substitution for CC-2, no
second reviewer. This branch touches production code in several places
(`hypothesis_gen.py`, `repair_forward_tracker.py`, `repair_lab.py`,
`chartDescription.ts`) — a human should independently diff-review before
merge, not rely on this summary alone. Review command:

```
git diff origin/main..feature/phase2-pending-cleanup
```

## Phase F — Pricing staleness guard

**Fixed.** Added `INTRODUCTORY_RATE_EXPIRY` (2026-08-31) and
`_pricing_staleness_warning(now)` to `hypothesis_gen.py`, called at the
start of both `generate_hypotheses` and `generate_web_hypotheses`. Follows
the existing "surface without halting" convention already established by
`validate_api_key`'s own non-401 preflight note (appended to the
`GenerationRunResult.errors` list under a `"(pricing staleness check)"`
sentinel label, never raised). Also fixed three of `generate_web_
hypotheses`'s early-return paths that previously built a fresh literal
`errors` list rather than using the mutable one, which would otherwise
have silently dropped the staleness warning in exactly those cases.
Pricing values themselves are unchanged (not yet 2026-08-31). 3 new tests
(fires past expiry, silent before expiry, web-generator path also checks),
red-then-green.

## Phase G — ETH "No price data yet"

**Root-cause classified: not a bug — confirmed via direct code inspection
and real data.** ETH's only roster entry is `ORDERFLOW_IMBALANCE` at
`"snapshot"` cadence (order-book depth, no OHLCV concept). `docs/site_
data/strategies.json` confirms this directly — no other ETH entry exists.
`export_candle_data.py`'s own header comment explicitly documents this as
a **prior, deliberate decision**, correcting an earlier wrong assumption:
*"the task spec that produced this module assumed ETH 'is already covered
as a standalone asset.' Checked directly against strategies.json: it is
not... ETH is deliberately NOT included here. Add it in a later batch if a
standalone ETH config is ever wired live."* Zero `ETH_*.json` candle files
exist anywhere in `docs/site_data/candles/`. `buildMarketAssetList`
correctly falls back to ETH's only available timeframe (`"snapshot"`,
sorted last since it has no finite duration), and the resulting fetch
correctly fails since no candle file for that cadence has ever existed by
design. "No price data yet" is the honest, correct consequence — not a
malfunction. **No fix attempted**, per this task's own instruction for a
structural root cause (fixing it would mean either wiring a new standalone
candle-export config for an asset no live strategy needs, touching the
shared `export_candle_data.py` pipeline every other asset relies on, or a
product decision to reword the tile for snapshot-only assets — both are
human decisions, not a small scoped fix).

## Phase H — Homepage counters showing 0

**Root-cause classified: not a bug — confirmed via direct code inspection,
client-side JS-animated counters, not server-computed zeros.**
`HeroStats.tsx` is a client component (`"use client"`); the 4 stat values
(`configsTested`, `liveSignals`, `verifiedConfigCount`, `trackingDays`) are
computed from real server-fetched props (`summary`/`roster`/`heartbeat`),
then rendered through `useCountUp(value)`. That hook's own initial React
state is `useState(target > 0 ? 0 : target)` — for any positive target,
the pre-hydration SSR snapshot is deterministically `0`; the actual
count-up only happens inside a `useEffect`, which never runs on a raw
HTML fetch (no JS execution). Confirmed the underlying data is genuinely
populated, not also broken: `site_summary.json` shows
`configs_tested: 1515`, the roster has 37 entries (`liveSignals`), 27
configs classify as verified, and `heartbeat.json` has a real
`tracking_since`-derivable timestamp. **No fix needed or attempted** — this
is an artifact of how the page was checked (a raw fetch/curl, not a real
browser), stated explicitly as the resolution per this task's own
instruction.

## Phase I — chartDescription.ts GOOGL sibling gap

**Fixed.** Confirmed the gap Phase 1 Fix A's closing report flagged still
existed exactly as described: `chartDescription.ts`'s `statusLine` had no
handling for `unverified_trades` at all, so GOOGL's real state (a resolved
ENTRY+EXIT round trip excluded solely by `exclude_unrecorded_source`) fell
into `"No completed trades yet"` — wrong, since a real round trip happened.
Added a new branch, checked before the existing unverified-open-entry
branch (matching `statLine.ts`'s own precedence), rendering `"N trade(s)
pending source verification — strategy is live and monitoring for
setups."`, reusing the existing `pluralTrades()` helper. 2 new tests
(GOOGL's real shape, and precedence when both unverified_trades and
unverified_open_entries are present), red-then-green.

## Phase J — Investigation Phase D & E fixes

**Both fixed**, in 3 commits (bring-in, then one fix commit each).

**Phase D:** a real discrepancy from this task's own fix-location
description was found and flagged rather than silently worked around — the
task said to check `insert_execution_log_row`'s return value in the EXIT
path, mirroring the ENTRY path. That would not have fixed the confirmed
failure: on the repeat call that triggers the bug, `_reconstruct_open_
trade` already reports no open position (the last logged row is the prior
EXIT), so the `if open_trade is not None` branch — where that insert call
lives — never runs a second time at all; the repeat call falls straight
through to entry evaluation, which is where the phantom `ENTRY` actually
gets logged. Implemented the investigation's own fix sketch instead:
idempotency now keyed on "has this attempt logged *any* row for this
`candle_timestamp` already," checked once before either branch runs.
`tests/test_repair_lab_forward_tracker_exit_idempotency.py` now passes;
full `test_repair_lab_forward_tracker.py` (11/11) unaffected, including the
test proving a *new* candle after an exit still correctly opens a new
position.

**Phase E:** matched the investigation's fix sketch exactly, no
discrepancy. `_is_legitimate_direction_mirror` now explicitly rejects a
condition whose op self-mirrors (`mirror_condition(long_c).op ==
long_c.op` — true only for `"eq"` today) before reaching the op-mismatch
check that let a value change hide behind it. Generic over any future
self-mirroring op, not special-cased to the string `"eq"`.
`tests/test_repair_lab_mirror_eq_boundary.py` now passes (both cases);
`test_research_agent_rule_dsl_direction.py`'s completeness check (15/15)
confirms no behavior change for any op other than `eq`.

## Untracked-file accounting (rail #8 — every file, explicit)

None of the following were created this session; all predate this branch
(and most predate the prior two branches) by several days. Nothing needs
adding or deleting:

| Path(s) | Dated | Verdict |
|---|---|---|
| `check_news.py`, `check_news2.py`, `check_ns.py`, `check_pead.py`, `check_pead2.py`, `check_pead3.py`, `check_pead4.py`, `check_pead_logs.py`, `check_pead_status.py`, `check_results.py`, `daily_check.bat` | 2026-07-29 | Pre-existing ad-hoc read-only diagnostic scripts (query `stats.json`/`strategies.json`/`news_sentiment_log`, grep git log, a local pull+status convenience batch file). Not referenced by any code or test. **Leave alone.** |
| `data/backups/truth_ledger.pre_data_source_migration.*.db`, `truth_ledger.pre_origin_main_reconcile.*.db` | 2026-07-29 | Deliberate, descriptively-named timestamped safety backups of `data/truth_ledger.db` made before two specific prior risky operations. Legitimate local safety nets, not debris. **Leave alone.** |
| `data/funding_cache/*.csv`, `data/macro_cache/*.csv` | 2026-07-29 | Pre-existing local caches of external API responses (funding rates, FRED macro series) used by other tooling. **Leave alone.** |
| `tests/fixtures/frozen_candles/backward_compat_baseline_after.json`, `baseline_before_run.log.err` | 2026-08-01 | Confirmed in an earlier session this same conversation: scratch output from a manual verification run, distinct from the real tracked fixture (`backward_compat_baseline_before.json`), referenced by zero tests anywhere in the repo. **Leave alone.** |

No file in this list was touched by, or is required by, any commit on this
branch.

## Full verification

- **Python suite:** `python -m unittest discover` → **2033 tests, 0
  failures** (before: main's 2027; after: 2033 — +3 Phase F, +3 Phase J's
  two new test files brought in and fixed).
- **No-auto-wire suite:** 3/3 passing, unchanged.
- **Website suite:** `npm test` → **48 suites / 541 tests, 0 failures**
  (before: 539; after: 541 — +2 from Phase I).
- **`RESEARCH_AGENT_ENABLED`** confirmed still defaults to disabled.
- **No `live_scheduler`/`default_registry` references** introduced by any
  phase.

## Commit list (each independently revertable)

```
1c0f737  Phase F: pricing staleness guard for INPUT_COST_PER_MTOK/OUTPUT_COST_PER_MTOK
681057f  Phase I: chartDescription.ts resolved-trade "pending verification" message (GOOGL sibling gap)
8d1eb70  Phase J (1/3): bring in the two failing tests from feature/investigation-phase1-infra-audit
3fe593b  Phase J (2/3): fix repair_forward_tracker.py EXIT-idempotency gap
5d3d259  Phase J (3/3): fix mirror_condition eq-operator boundary in repair_lab.py
```

(No commit for Phase G or H — both confirmed not-a-bug, nothing to change.)

## Status

Pushed to origin (`feature/phase2-pending-cleanup`). **Not merged.** Awaiting
human review and merge decision. `feature/investigation-phase1-infra-audit`
and `feature/phase1-fixes-a-and-b` remain intact and untouched.
