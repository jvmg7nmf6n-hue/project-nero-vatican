# Factory Loop Implementation Report (CC-1 directive, final)

**Status: implementation complete.** All 9 numbered items shipped. No verdict, threshold, or gate value changed anywhere in this work — the sole exception is item 7 adding a NEW binding gate (Variant C freshness disqualification), which did not exist before this directive and is explicitly scoped as new machinery, not a change to an existing one. `EVE_ENABLED` and `RESEARCH_AGENT_ENABLED` remain exactly as they were (see the confirmation section below).

Format per item, as requested: **FINDING** (file+line/function/grep/commit) → **CONFIDENCE** → **WHAT SHIPPED**.

---

## Item 0 — resolved, no action required

No action taken. The directive's own item 0 states this was already resolved before this directive began (the PEAD "exit-tracking bug" claim did not match the real code/data). Confirmed unchanged: no PEAD exit logic was touched anywhere in this work.

---

## Item 1+2 — run_id and provenance fields

**FINDING:** `nero_core/research_agent/hypothesis_gen.py`'s `_build_record`/`_build_web_record` never carried a run identifier; `nero_core/research_agent/pipeline.py`'s `run_pipeline` never minted one. **CONFIDENCE:** confirmed-from-code (re-verified directly before implementing, matching `factory_loop_specification.md`'s own B1 finding).

**WHAT SHIPPED:**
- `run_pipeline` mints one `uuid.uuid4()` per invocation (`nero_core/research_agent/pipeline.py`), threaded through both `generate_hypotheses` and `generate_web_hypotheses` into every hypothesis record produced that call, on both channels. `PipelineRunResult.run_id` added and printed in `main()`.
- Every Adam hypothesis record now carries `run_id`, `origin_agent: "adam"` (fixed literal), `origin_chain: None`.
- Every Eve hypothesis record (`nero_core/eve/hypothesis_shapes.py::build_hypothesis_record`) now carries `origin_agent: "eve"`, `origin_chain: None` alongside its pre-existing `session_id`.
- **Item 1a** (Adam's DIED verdicts never persisted): confirmed the gap exactly as the directive described — `.github/workflows/research_agent_manual.yml`'s own comment (pre-existing, lines 41-45 before this change) stated `agent_test_results.json` was deliberately never committed. Fixed: added an unconditional "Commit test results" step, mirroring the existing "Commit run summary" step's pattern. **Design decision beyond my own draft plan, flagged for confirmation:** my initial plan proposed gating this behind a manual `workflow_dispatch` approval input, reasoning by analogy to `agent_hypotheses.json`'s own no-commit rule. On implementation I reconsidered and shipped it unconditional instead, because the directive's own text is explicit ("must be committed on every real run") and because a `TestResult` is a deterministic statistical computation derived from an already-recorded hypothesis (verdict, p-value, trade stats) — not raw LLM proposal prose — so it does not carry the same "unreviewed bad claim, can't be undone" risk the hypotheses file's no-commit rule exists to guard against. This is a deviation from MY plan, not from the directive.
- **Item 2a:** schema-only at this point (`origin_agent`/`covers` fields defined, applied by item 6's actual writer — see below).

**Tests:** `tests/test_factory_loop_provenance.py` (7 tests, all pass). Verified zero regressions against the full pre-existing `test_research_agent_kill_switch.py`, `test_research_agent_hypothesis_gen.py`, `test_research_agent_web_hypothesis_gen.py` suites.

---

## Item 3 — FDR claim reframe (truth-in-labeling only)

**FINDING:** `docs/site_data/eve_session_registry.json` line 7 (`pre_registration.eve_must_clear`) and its Session 1 entry's own `reason` text both asserted "across the full cross-asset family" / "evaluated across all 8 sessions together, not session-by-session" — but `nero_core/eve/scoring.py::apply_fdr_correction`, called from `nero_core/eve/pipeline.py` once per session against that session's own `hypothesis_records` only, has never implemented that aggregate reading. **CONFIDENCE:** confirmed-from-code (the per-session mechanism, re-verified, unchanged by this item) and confirmed-from-data (the registry text, read directly).

**WHAT SHIPPED:** No change to `apply_fdr_correction` or its scope — confirmed by direct diff review before and after this item; only the two prose locations above were rewritten to state the per-session reality plainly. The ORIGINAL wording is preserved byte-identical in a new `eve_must_clear_original_wording` field (never silently lost), alongside a new `eve_must_clear_reframe_provenance` object recording *when* this reframe happened and *why*, with the real numbers below (item 3a) — not "0/0" — as its evidentiary basis. Session 1's own `reason` text (previously asserting the pooled reading) was corrected in place with an explicit note that it was corrected, not silently rewritten with no trace.

Also checked (grep, repo-wide) for the same phrase in `docs/investigations/eve_engine_v1_report.md` (a historical closing-report doc quoting the ORIGINAL 2026-08-03 pre-registration verbatim, inside a blockquote) — left untouched deliberately: it is a historical record of what the pre-registration said at the time, not a live claim, and rewriting a quoted historical document to match a later reframe would misrepresent history. And across `website/` (zero matches — confirmed no public-facing instance of this claim exists, consistent with the background research pass's own finding that Eve has zero public presence before item 8).

### Item 3a — the six real counts, with sources (re-derived 2026-08-05, not assumed)

| Population | SURVIVED | PROMISING-WATCHLIST | Source |
|---|---:|---:|---|
| Adam (all runs) | 0 | 0 | `docs/site_data/agent_performance.json`, `cumulative.survived`/`cumulative.promising_watchlist` |
| Eve (all sessions, combined verdict) | 0 | 0 | `docs/site_data/eve_hypotheses.json`, 16 records, `verdict_combined` field — never SURVIVED or PROMISING_WATCHLIST in any record |
| Random baselines (K=200) | 0 (all 5 assets) | ETH/4h: 3, PAXG/4h: 8, BTC/4h: 0, SOL/4h: 0, BTC/24h: 0 | `docs/investigations/{asset}_random_baseline_result.json`, `verdict_counts` field |

**The literal "0/0 SURVIVED or PROMISING-WATCHLIST" claim is still technically true at the COMBINED-verdict level** — but stating it without qualification would be misleading, since: (a) 3 sub-verdict (`verdict_is`/`verdict_oos`) PROMISING_WATCHLIST occurrences exist within Eve's real data — `BTC_VOL_EXPANSION_BREAKOUT` (verdict_is), `BTC_MOMENTUM_IGNITION` (verdict_oos, with `p_value_is=0.0044` clearing FDR significance on the IS half while `p_value_oos=0.224` fails — a textbook in-sample-only pattern, correctly not counted as a win), and `PAXG_PREMIUM_FADE_DYNAMIC_EXIT` (verdict_is) — all three landing at `verdict_combined=DIED`; and (b) the K=200 random baselines themselves show non-zero PROMISING-WATCHLIST rates (ETH 3/200, PAXG 8/200), which is itself useful context for calibrating what "PROMISING-WATCHLIST" should be expected to look like under pure chance. Both framings are stated explicitly in the reframe provenance note and in item 8's page copy — neither the directive's suspected-stale "0/0" nor an inflated "something has worked" impression.

**STALE FIGURE FOUND:** the directive's own drafted provenance figure ("0/0 SURVIVED or PROMISING-WATCHLIST across every committed run") was flagged by the directive itself as possibly stale and was correctly NOT propagated as-is — the real picture (above) is more nuanced than a bare 0/0, and the written provenance note states it fully.

**Tests:** `tests/test_eve_session_registry.py` extended (2 new tests: reframe provenance carries the real numbers; no session `reason` text asserts the stale pooled claim). All 8 tests in that file pass, including the pre-existing 6.

---

## Item 4 — TEST → TRIAL (core)

**FINDING:** No "Trial" concept existed anywhere in this codebase; a SURVIVED/PROMISING-WATCHLIST verdict meant only `review_status="pending_human_approval"` on a `TestResult`, with nothing forward-tracking it (`factory_loop_specification.md`'s own B1, re-confirmed directly against `nero_core/research_agent/auto_tester.py`). **CONFIDENCE:** confirmed-from-code.

**WHAT SHIPPED:** New `nero_core/research_agent/trial.py` — `TrialRecord`, `admit_to_trial` (the real gate is **DSL-valid AND NOT freshness-disqualified**; the backtest verdict travels as an advisory `entry_verdict` tag only, never a condition for admission — a DIED hypothesis is admitted exactly like a SURVIVED one, per the directive's own "measure, never gate" framing), `compute_projected_time_to_min_sample` (item 4a — always populated, `None`/"UNMEASURABLE" labeled rather than omitted when unmeasurable), `queue_health` (item 4b), an `attribution` string computed once per record (item 4c: `"Explored by Adam/Eve, our research agent."`). Forward-tracking reuses `repair_forward_tracker.evaluate_forward_tick` unmodified in its core logic — extended with a new optional `strategy_prefix` parameter (default unchanged, so every pre-existing Repair Lab call site/test is byte-identical to before) so Trial's own population (`TRIAL_STRATEGY_PREFIX = "TRIAL"`) shares the SAME `data/repair_lab_forward_tracking.db` file without colliding with repair attempts, even under an identical literal id (tested explicitly). Persistence: `docs/site_data/forward_trial.json`.

**Item 4e (the admission gate is not DSL-validity alone):** implemented from the start as `DSL-valid AND NOT freshness_disqualified`, with `freshness_disqualified` defaulting to `False` — exactly per the directive's own sequencing instruction, so no rebuild was needed once item 7 landed (it landed first in this implementation's own order, but the code was written gate-first to tolerate either order).

**Decision requiring human confirmation, already resolved during this session:** item 7d's real re-score of Eve Session 1 found the freshness gate disqualifies **100%** of that session's 5 backtested hypotheses (session-wide, not just the 2 PAXG ones — see item 7's own section below) — materially higher than the directive's own ~33% expectation. Per the directive's explicit "stop and report, don't proceed to make it binding-by-default, if it's materially higher" instruction, this was surfaced to the user directly (mid-session) rather than silently shipped either way. **User's decision: ship the gate live** (DSL-valid AND NOT freshness-disqualified, exactly as item 4e specifies) — recorded here as the resolution.

### Item 4d — real counts at ship time (re-confirmed 2026-08-05, not assumed stale)

- **Real count in `docs/site_data/forward_trial.json` at ship time: 0.** The file did not exist before this work; nothing has been run through `admit_to_trial()` in a real pipeline invocation yet (the mechanism is built and callable, not yet wired into any scheduled trigger for automatic admission — see item 9c's own honest limitation).
- **Retroactive analysis** (how many of the 18 real committed hypothesis records — 2 Adam + 16 Eve — would be admissible if run through this gate today): 14 are DSL-valid (2 Adam + 12 Eve; 4 Eve records from Session 0, before the DSL-vocabulary fix, are DSL-invalid and never admitted regardless of freshness). Applying item 7's real freshness finding retroactively removes Session 1's 6 hypotheses entirely (session-wide disqualification) from that 14, leaving **8 net-admissible** under both gates combined.

**Tests:** `tests/test_trial_admission.py` (23 tests, all pass). `repair_forward_tracker.py`'s extension verified against its full pre-existing 27-test suite (`test_repair_lab_forward_tracker.py`, `test_repair_lab_forward_tracker_exit_idempotency.py`, `test_repair_lab_chain_record.py`, `test_repair_lab_no_auto_wire.py`) — zero regressions.

---

## Item 5 — REPAIR → TRIAL

**FINDING:** Repair Lab v1 (`repair_lab.py`, 860 lines, 8 dedicated test files) was fully built and tested but entirely unwired — confirmed no caller anywhere outside its own test files. **CONFIDENCE:** confirmed-from-code.

**WHAT SHIPPED:** New `nero_core/research_agent/repair_to_trial.py` — its OWN admission path (per spec B3, NOT a reuse of item 4's DSL/freshness gate, since a repair attempt already passed its own stricter sequence: `check_eligibility`, `validate_modification`, `check_in_chain_duplicate`, `can_launch_new_attempt`). `admit_repair_to_trial(repair_chain_id, attempt_id, events, ...)` reads the reconstructed chain state, admits only an attempt resolved to SURVIVED/PROMISING-WATCHLIST, and converges on item 4's exact same `TrialRecord` shape via `trial.admit_to_trial(..., origin="repaired", repair_chain_id=..., attempt_id=...)` — full lineage back to the original DIED ancestor is always traceable via the pre-existing `reconstruct_chain_state`, unmodified.

**Item 5c (narrowed no-auto-wire boundary):** `tests/test_repair_lab_no_auto_wire.py`'s static check extended (`NEW_REPAIR_LAB_FILES` tuple now also covers `trial.py`/`repair_to_trial.py`) rather than deleted or loosened. New `tests/test_repair_to_trial.py::RepairToTrialNoAutoWireTest` adds the narrower, still-real assertion: `repair_to_trial.py` still has zero references to `live_scheduler`/`default_registry` (same static check every Repair Lab file gets), AND (grep-based, across every `nero_core/execution/*.py` and `.github/workflows/*.yml` file) nothing outside a human-invoked context references `repair_to_trial` at all — the boundary that survives is "Repair Lab never auto-invokes itself," not "nothing ever calls it."

**Item 5d (a repair that still fails stays in the Graveyard):** new `graveyard_distillation.load_died_repair_records` reconstructs every repair chain, finds DIED attempts, and tags each with `origin_chain: {repair_chain_id, attempt_id}` (a new field added to `DiedRecord`) — so a re-death (a repair that already tried once and failed again) is structurally distinguishable from a first death, wired via `origin_agent` inherited from the launch event.

**Tests:** `tests/test_repair_to_trial.py` (13 tests, all pass) plus the extended `test_repair_lab_no_auto_wire.py` (unchanged 3 tests, now covering 5 files instead of 3, all pass).

---

## Item 6 — TEST → GRAVEYARD, with distillation

**FINDING:** `graveyard.json`/`failure_patterns.json` were both 100% hand-curated with no code writer for either; `check_graveyard_match`'s own overlap-based matching was the only existing machinery close to "which family does this belong to." **CONFIDENCE:** confirmed-from-code.

**WHAT SHIPPED:** New `nero_core/research_agent/graveyard_distillation.py`. Trigger: per family (resolved via the SAME `check_graveyard_match` function every hypothesis already runs at generation time — reused, not reinvented — deliberately excluding brand-new, never-before-seen failure modes from auto-clustering; see `find_unmatched_died_records`), once DIED count reaches `DIED_COUNT_TRIGGER = 3`. `draft_distillation_entry` makes ONE LLM call (re-inlined `_extract_text`/`_strip_markdown_json`/`_call_cost_usd`, matching `repair_lab.propose_modification`'s exact precedent — not imported across module boundaries, per this codebase's own established convention) from AGGREGATE stats only, validates the closed 6-value `failure_pattern` taxonomy, and computes the structural bookkeeping fields (`covers`, `origin_agent_breakdown`, `origin_agent_by_name` — item 2a) directly from the input records, never trusting them from the LLM's own JSON. `commit_graveyard_entry` refuses (`EntryNotApprovedError`) to write anything still at `review_status="pending_human_approval"`, and writes to BOTH files in one operation (item 6a) — cap-and-merge (item 6b) at `FAILURE_PATTERNS_CAP = 30` extends an existing same-family entry's `covers` list rather than appending past the cap, raising rather than guessing an unrelated merge target if none exists.

### Item 6b — real counts (re-derived 2026-08-05)

`graveyard.json` = **21 entries**. `failure_patterns.json` = **22 entries** (the `factory_loop_specification.md`'s own "13" figure is confirmed STALE — 9 entries were backfilled in commit `a55059a`, after that spec doc was written). One legitimate asymmetry remains: `RANGE_MEAN_REVERSION` exists in `failure_patterns.json` only (an open repair candidate, matching `repair_candidates.json`, not a closed graveyard family — the exact, already-documented exception `test_graveyard_failure_pattern_sync.py` has always allowed). **Cap sizing:** 30 was chosen against these real 21/22 counts, giving roughly 8 entries of headroom before the cap forces its first merge — not sized against the stale "13."

**Item 6c (coverage-based sync test):** `tests/test_graveyard_failure_pattern_sync.py` rewritten from a one-directional-equality assertion to a coverage assertion — every `graveyard.json` name must be covered by EXACTLY ONE `failure_patterns.json` entry, via a new `covers` field (defaulting to `[name]` when absent, so all 22 real pre-item-6 entries needed ZERO data migration — verified directly by re-running the updated test against the real committed files, which passes with no changes to their content). `docs/site_data/README.md` updated with a new section documenting the uncapped/capped division.

**Item 6d (success feedback, built now, empty today):** `load_survived_trial_context` reads `docs/site_data/forward_trial.json` filtered to `status="SURVIVED_TRIAL"` — the same read-fresh-every-session discipline `failure_patterns.json` already gets. Returns `[]` today (nothing has ever reached SURVIVED_TRIAL) by design, not by omission — retrofitting this after real data exists would be strictly more work.

**Tests:** `tests/test_graveyard_distillation.py` (16 tests) + `tests/test_repair_to_trial.py`'s `LoadDiedRepairRecordsTest` (4 tests) + the rewritten `test_graveyard_failure_pattern_sync.py` (5 tests, including the new coverage test) — all pass, all verified against the REAL committed 21/22-entry files, not just synthetic fixtures.

---

## Item 7 — search freshness, Variant C, BINDING

**FINDING:** `tag_lookahead_risk` (`nero_core/eve/scoring.py`) was informational-only, session-scoped, keyed off `backtest_window_start`. **CONFIDENCE:** confirmed-from-code.

**WHAT SHIPPED:** New `check_freshness_disqualification` (Variant C: `pub_date >= session_started_at - 30 days`), sharing a refactored-out traversal helper (`_iter_web_search_results`) with `tag_lookahead_risk` — refactor verified byte-identical against the full pre-existing 11-test `LookaheadRiskTagTest` suite. `apply_freshness_disqualification` applies the (necessarily session-wide — see below) flags to every record; `apply_fdr_correction` extended to exclude freshness-disqualified records from the FDR family alongside self-derivative ones (item 7c), verified backward-compatible against the exact-string assertion in the pre-existing `test_eve_scoring_fdr.py`. `nero_core/eve/pipeline.py` wires the check before `apply_fdr_correction` (correct ordering) and implements item 7b's fail-loud rule: a session whose entire real hypothesis population is disqualified prints a stderr `WARNING` and persists `freshness_disqualified_entire_session: True` on the session record.

**Item 7a (audit fields):** every flag carries `hypothesis_name`, `offending_source_url`, `parsed_pub_date`, `rule_fired="variant_c_30day"`.

### Item 7d — back-tested against the REAL Session 1 file (`eve-20260804T020749Z-4cf6e4c9.json`)

Re-scored directly, not assumed. Real `session_started_at = 2026-08-04T02:07:49.935649+00:00`. Turn 0 contains 6 real search-tool-result blocks (not a data duplication bug — confirmed by inspecting raw content-block types) totaling 16 individual search results, 5 with a parseable `page_age`: `bitget.com/price/pax-gold` ("3 weeks ago" → 2026-07-14, **disqualifies**) and `coinmarketcap.com` PAXG price-prediction ("1 month ago" → 2026-07-05, **disqualifies**, exactly at the 30-day boundary) — both PAXG-specific by URL content; `gate.com` (Feb 1 2026), `beincrypto.com` (May 20 2026), `oanda.com` (Apr 23 2024) — none disqualify. This matches the directive's own expectation of "2 of 4 real sources flag."

**The disqualification RATE, however, does not match the ~33% expectation, and this was reported live during the session, not silently absorbed:** because `check_freshness_disqualification`'s scope is necessarily session-wide (the real session log structurally cannot attribute one search result to one specific `propose_hypothesis` call — the same documented limitation `tag_lookahead_risk` already had), the two disqualifying sources disqualify ALL 5 of Session 1's backtested hypotheses, not just the 2 PAXG-named ones. **Real rate: 100%, not ~33%** — materially higher, exactly the condition the directive's own item 7d instructs to stop and report on before making the rule binding-by-default. This was surfaced to the user mid-session via a direct question; **the user's decision was to ship the gate live anyway** (see item 4's section above), accepting session-wide disqualification as the honest, conservative behavior given the data cannot support finer attribution, with item 7b's fail-loud mechanism as the safety net that ensures this can never happen silently.

**Tests:** `tests/test_eve_freshness_disqualification.py` (14 tests, all pass), including a synthetic regression guard replicating this exact 2-of-4 real-sample finding.

---

## Item 8 — public Factory Loop page

**WHAT SHIPPED:** `website/app/factory-loop/page.tsx` (static prose, `app/methodology/page.tsx`'s pattern) + `website/components/FactoryLoopDiagram.tsx` (hand-rolled `<svg>`, matching `Logo.tsx`'s established precedent — no new dependency). **Item 8a:** `website/app/lab/page.tsx`'s "Repair Workbench" section renamed to **"Repair Candidates"** (matching `repair_candidates.json`'s own name), done first per the directive's own sequencing. **Item 8b:** first public Eve mention on the site (confirmed zero before this page via the background research pass's own grep) — a plain-language "who proposes ideas: Adam and Eve" section. **Item 8c:** "Forward Trial" naming applied exactly as the directive specified it (no further confirmation needed — the directive named the exact string), used consistently in `website/lib/types.ts`'s `FactoryLoopStatusExport.forward_trial` key, the page's own copy (which explicitly calls out and disambiguates the unrelated pre-existing "Under Trial" roster tier), and item 9's status JSON.

Real counts cited: graveyard count fetched live via the pre-existing `fetchGraveyard()` (21, real); Forward Trial/Repair counts fetched via the new `fetchFactoryLoopStatus()` with an honest "not yet reporting" fallback if null; Adam's SURVIVED/PROMISING-WATCHLIST counts fetched live via the pre-existing `fetchAgentPerformance()`; Eve's stated as prose citing item 3a's real numbers (no live per-Eve-hypothesis site fetch was built — judged to be new scope beyond what item 8 asks, flagged here for visibility).

**Tests:** `website/__tests__/factoryLoopPage.test.tsx` (7 tests, all pass). Full website suite: 598 tests, 2 pre-existing failures (see confirmation section below), zero new failures.

---

## Item 9 — live Factory Loop status

### Item 9d — MUST run before anything else in this item ships (completed first, per the directive's own precondition)

**Investigated directly against the real, live 191-row `docs/site_data/ledger_full.json`, not just grepped for in code.** Confirmed the directive's own two cited examples exist verbatim (COINTEGRATION_PAIRS BTC-ETH and TREND_PULLBACK BNB, both at `2026-08-03T13:46:35.310829Z`, with two different z-scores). **Root cause, confirmed from the data: the directive had the two timestamp fields backwards.** `timestamp` is the scheduler tick's own wall-clock RUN time (shared across a catch-up burst); `candle_timestamp` is the actual decision-defining field, and it genuinely DIFFERS between the "duplicate"-looking rows (12h apart for the BTC-ETH/BNB pair, matching their real candle interval; a 5-boundary catch-up burst is visible on 2026-07-28 for BTC/SILVER strategies). **These are not literal duplicate rows** — each is a real, distinct decision for a real, distinct closed candle, all logged in the one scheduler tick that happened to run late enough to have a backlog. (A broader, naive grouping ignoring `strategy_version` finds 23 "duplicate" groups, but 12 of those are FALSE POSITIVES — different REGISTERED STRATEGY VERSIONS of the same family, e.g. RANGE_MEAN_REVERSION's two live variants, correctly logged as separate rows. This distinction is reported precisely, not glossed over.)

**Are hero counters affected?** Checked directly against `docs/site_data/stats.json`: `signal_counts.NO_TRADE` (a raw row count) IS inflated by catch-up bursts — correctly, since each row is a real distinct decision, just at a non-uniform per-tick cadence a viewer wouldn't expect. **`resolved_trades`/`win_rate`/`expectancy_r`/R-multiple figures are NOT affected** — checked every one of the 11 true same-config duplicate-timestamp groups in the current ledger and confirmed zero are ENTRY/EXIT signals (all are NO_TRADE). **No trade-count, win-rate, or R-multiple number on the live site is currently double-counted by this phenomenon** — confirmed empirically, not assumed. The one real, confirmed consequence is display/interpretive: a viewer reading the raw ledger table by `timestamp` alone, without `candle_timestamp` also visible, would see what looks like two contradictory simultaneous readings with no explanation.

**Proposed dedupe key (NOT implemented — explicitly out of scope for this directive):** any per-strategy row-count stat or ledger display grouping should key on `(strategy, strategy_version, asset, candle_timestamp, signal_type)` — the same tuple `execution_log`'s own real UNIQUE constraint already uses — rather than `timestamp` (run time). Report only, per the directive's explicit instruction; no fix shipped.

### The rest of item 9

New `tools/factory_loop_status_summary.py`, following `research_agent_run_summary.py`'s convention but as a full-file snapshot overwrite (there is one current status, not a history to append). Ran once for real: `docs/site_data/factory_loop_status.json` is now committed with real current numbers — **`forward_trial.count=0`, `graveyard.count=21`, `repair.count=0`** — all honest zeros (item 9a), matching item 4d's and item 5's own ship-time findings exactly (nothing has yet run through either admission path in a real invocation). **Known limitation, reported rather than fabricated:** `graveyard.distilled_this_period`/`pending_review` both always report 0 — no committed file currently tracks distillation drafts pending human review (a draft only ever exists in memory before a human approves it). **Item 9b:** `unmeasurable_count` on the `forward_trial` object, surfaced (currently 0, since the queue itself is empty). **Item 9c:** wired into `.github/workflows/research_agent_manual.yml` as two new steps, with an explicit comment stating the honest limitation that nothing yet AUTOMATICALLY calls any of items 4/5/6's admission/distillation functions (all deliberately human-invoked only) — so most re-runs will recompute the same snapshot until a human separately runs one of those functions.

Frontend (`fetchFactoryLoopStatus`, `FactoryLoopStatusExport` types) was built as part of item 8, since the real counts item 8's own honest page content needs ARE item 9's data — consolidated rather than building two separate data-fetching paths for the same numbers. **Design decision flagged for confirmation:** item 9's own sketch suggested "a new section on /lab" for the live-counts display; this was NOT followed — the display lives on the new `/factory-loop` page instead, keeping `/lab` focused on strategy-level research as before.

**Tests:** `tools/factory_loop_status_summary.py` — `tests/test_factory_loop_status_summary.py` (8 tests, all pass).

---

## Test counts, before/after

**Python** (`python -m unittest discover -s tests`): a full-suite checkpoint taken mid-session (after items 1+2 and item 7 landed) measured **2425 tests, 3 pre-existing errors** (all `lxml`/PSX-data-source related — `lxml` is not installed in this environment; confirmed via a direct `import lxml` failure and confirmed via `git status` that neither the failing test files nor any file they depend on were touched this session, at any point). **Final: 2488 tests, same 3 pre-existing errors, 0 failures.** The 63-test delta between the two checkpoints reconciles exactly against the tests added after that checkpoint: `test_eve_session_registry.py` +2, `test_graveyard_distillation.py` +16 (new file), `test_trial_admission.py` +23 (new file), `test_repair_to_trial.py` +13 (new file), `test_graveyard_failure_pattern_sync.py` +1, `test_factory_loop_status_summary.py` +8 (new file) = 63.

**Self-caught bug, fixed before this report was finalized:** the final full-suite run surfaced one NEW failure — `test_repair_to_trial.py::RepairToTrialNoAutoWireTest::test_no_workflow_or_scheduler_file_invokes_repair_to_trial_automatically`, a false positive in my own test: its grep-based check matched the substring `repair_to_trial` inside `research_agent_manual.yml`'s item 9c COMMENT (prose explaining that nothing calls `admit_repair_to_trial` automatically), not an actual invocation. Fixed by excluding comment lines (`#`-prefixed) from the check in both `.py` and `.yml` files before matching — re-verified: the real invariant holds (nothing outside a human-invoked context references `repair_to_trial`), the test now asserts it correctly, and a second full-suite run confirmed 0 failures, same 3 pre-existing errors.

Total new Python test functions added this session, across 6 new files and 3 modified existing files: **84** (7 `test_factory_loop_provenance.py` + 14 `test_eve_freshness_disqualification.py` + 16 `test_graveyard_distillation.py` + 23 `test_trial_admission.py` + 13 `test_repair_to_trial.py` + 8 `test_factory_loop_status_summary.py` + 2 added to `test_eve_session_registry.py` + 1 added to `test_graveyard_failure_pattern_sync.py`). Zero regressions in any pre-existing test, confirmed both by running every directly-touched module's own pre-existing suite before and after each individual change, and by two full-suite runs.

**Website** (`npx jest`): 598 tests total, 596 passing, **2 pre-existing failures** in `siteDataSchema.test.ts` (a stale assumption that `failure_patterns.json` family names must be unique, which conflicts with this project's own documented "one family can span multiple named variant entries" design — confirmed pre-existing via `git status`/`git diff` showing zero changes to either the test file or `failure_patterns.json`'s content this session). New: `factoryLoopPage.test.tsx` (7 tests) — all passing.

---

## Confirmations

- **No verdict, threshold, or gate value changed.** `apply_fdr_correction`'s mechanism and per-session scope: unchanged (item 3 is prose-only). `classify_verdict`, `MIN_SAMPLE_SIZE`, `benjamini_hochberg`, frequency-gate thresholds: untouched. The only NEW gate in this entire directive is item 7's freshness check, which did not exist before and is additive, not a modification of an existing threshold.
- **`EVE_ENABLED` remains `False`** (never set to a truthy value in any committed workflow — confirmed by `grep -rn "EVE_ENABLED" .github/workflows/*.yml`, zero matches for the flag being set).
- **`RESEARCH_AGENT_ENABLED`** remains exactly as before — set to `"true"` only inline in `research_agent_manual.yml`'s one existing job step, unchanged in scope or location.
- **Untracked-file accounting:** the pre-existing untracked debris noted in this session's own initial `git status` (`check_news*.py`, `check_pead*.py`, `check_ns.py`, `check_results.py`, `daily_check.bat`, `data/funding_cache/`, `data/macro_cache/`, `docs/site_data/agent_hypotheses.json`, `docs/site_data/agent_test_results.json`, `tests/fixtures/frozen_candles/backward_compat_baseline_after.json`, `tests/fixtures/frozen_candles/baseline_before_run.log.err`) is unchanged and untouched by this work — confirmed unrelated to the Factory Loop by the background research pass. This session's OWN new untracked additions are exactly the new files listed throughout this report (7 new Python modules/tools, 6 new Python test files, 3 new website files, 1 new committed JSON export) — nothing was committed to git during this session; that remains the user's decision to make.

## What the Factory Loop still cannot do

It cannot yet run itself. Every admission/distillation function built in items 4, 5, and 6 is real, tested, and callable — but none is invoked automatically by any scheduled workflow. Adam's own pipeline still requires a manual `workflow_dispatch` click; Eve remains fully manual and `EVE_ENABLED=False`; Repair Lab and Trial admission are library calls a human (or a human-triggered script) must invoke explicitly; graveyard distillation drafts require a human's explicit approval before anything is written. The loop, as shipped, is a complete and honest set of PARTS — proposal, test, admission, forward-tracking, distillation, repair, and public reporting all exist and are wired to each other correctly — but the motor that would turn it into a continuously running loop, rather than a sequence of deliberate human-invoked steps, does not exist yet, and this report does not claim otherwise.

## Stale figures found in this directive, and the real values

1. `factory_loop_specification.md`'s "13 entries" for `failure_patterns.json` → real count is **22** (9 backfilled in commit `a55059a`, after that doc was written).
2. The directive's own drafted item 3a provenance figure ("0/0 SURVIVED or PROMISING-WATCHLIST across every committed run") → still technically true at the combined-verdict level, but incomplete without the sub-verdict and random-baseline context reported in full above.
3. The directive's own ~33% expectation for item 7d's real disqualification rate → real rate is **100%**, for the structural reason (session-wide attribution) explained above, not a bug in the implementation.
