# Factory Loop Implementation Report (CC-1 directive, final)

**CORRECTION NOTICE (2026-08-05, same day as original ship, commit `61d78a8`):** item 7's binding freshness-disqualification gate (described below in the original items 4/7 sections exactly as it shipped) was **reverted to informational-only** the same day, per a separate CC-1 correction directive. The sections below are left byte-identical to the original report — they are the accurate historical record of what shipped in `61d78a8` — but they no longer describe current behavior where they discuss binding freshness disqualification. **See the "CC-1 CORRECTION" section near the end of this document for the full reversal record, the required revert-verification results, and the root-cause investigation into per-hypothesis attribution.** Read that section before relying on anything below regarding item 4e's admission gate or item 7c's FDR exclusion.

**Status: implementation complete, later partially corrected (see above).** All 9 numbered items shipped. No verdict, threshold, or gate value changed anywhere in the ORIGINAL work — the sole exception was item 7 adding a NEW binding gate (Variant C freshness disqualification), which did not exist before this directive and was explicitly scoped as new machinery, not a change to an existing one. That new gate was itself reverted the same day (see the correction section). `EVE_ENABLED` and `RESEARCH_AGENT_ENABLED` remain exactly as they were throughout (see the confirmation section below).

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

**[CORRECTED 2026-08-05 — see the "CC-1 CORRECTION" section near the end of this document.]** Item 4e's gate as described below (DSL-valid AND NOT freshness-disqualified) is the ORIGINAL, now-reverted behavior. The gate is currently DSL-validity only.

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

**[CORRECTED 2026-08-05 — see the "CC-1 CORRECTION" section near the end of this document.]** The word "BINDING" in this section's own title reflects the ORIGINAL, now-reverted state. `check_freshness_disqualification` and its supporting machinery are informational-only again as of the correction.

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
- **Untracked-file accounting:** the pre-existing untracked debris noted in this session's own initial `git status` (`check_news*.py`, `check_pead*.py`, `check_ns.py`, `check_results.py`, `daily_check.bat`, `data/funding_cache/`, `data/macro_cache/`, `docs/site_data/agent_hypotheses.json`, `docs/site_data/agent_test_results.json`, `tests/fixtures/frozen_candles/backward_compat_baseline_after.json`, `tests/fixtures/frozen_candles/baseline_before_run.log.err`) is unchanged and untouched by this work — confirmed unrelated to the Factory Loop by the background research pass. This session's OWN new/modified files (7 new Python modules/tools, 6 new Python test files, 3 new website files, 1 new committed JSON export, 15 modified files) were committed as `61d78a8` after explicit user confirmation. **[Update, same day]** The freshness-gate revert described in the CC-1 CORRECTION section below is a separate, later commit — see that section for its own commit reference.

## What the Factory Loop still cannot do

It cannot yet run itself. Every admission/distillation function built in items 4, 5, and 6 is real, tested, and callable — but none is invoked automatically by any scheduled workflow. Adam's own pipeline still requires a manual `workflow_dispatch` click; Eve remains fully manual and `EVE_ENABLED=False`; Repair Lab and Trial admission are library calls a human (or a human-triggered script) must invoke explicitly; graveyard distillation drafts require a human's explicit approval before anything is written. The loop, as shipped, is a complete and honest set of PARTS — proposal, test, admission, forward-tracking, distillation, repair, and public reporting all exist and are wired to each other correctly — but the motor that would turn it into a continuously running loop, rather than a sequence of deliberate human-invoked steps, does not exist yet, and this report does not claim otherwise.

## Stale figures found in this directive, and the real values

1. `factory_loop_specification.md`'s "13 entries" for `failure_patterns.json` → real count is **22** (9 backfilled in commit `a55059a`, after that doc was written).
2. The directive's own drafted item 3a provenance figure ("0/0 SURVIVED or PROMISING-WATCHLIST across every committed run") → still technically true at the combined-verdict level, but incomplete without the sub-verdict and random-baseline context reported in full above.
3. The directive's own ~33% expectation for item 7d's real disqualification rate → real rate is **100%**, for the structural reason (session-wide attribution) explained above, not a bug in the implementation. **This same 100% finding is what triggered the correction below.**

---

# CC-1 CORRECTION — Item 7's freshness gate reverted to informational-only (2026-08-05, same day)

**Context, stated plainly:** item 7d did exactly what it was supposed to — it found the binding gate disqualifies 100% of Session 1's hypotheses rather than the ~33% expected, stopped, and asked. The answer that came back at the time, "Ship it live," was accepted under a `/goal continue without stopping` instruction rather than as deliberate human review of the tradeoff. That was identified as a mistake on the human side, and this correction directive reverted it the same day. The finding itself (item 7d, above) was correct and is NOT being retracted — only the decision made in response to it is.

Format per item, as required: **FINDING** → **CONFIDENCE** → **WHAT WAS REVERTED / WHAT WAS FOUND**.

## 1. Revert — binding back to informational-only

**FINDING:** `nero_core/research_agent/trial.py::admit_to_trial` gated admission on `DSL-valid AND NOT freshness_disqualified`; `nero_core/eve/scoring.py::apply_fdr_correction` excluded freshness-disqualified records from the FDR family alongside self-derivative ones. Both shipped in commit `61d78a8`. **CONFIDENCE:** confirmed-from-code (direct diff review of both functions before reverting).

**WHAT WAS REVERTED:**
- `admit_to_trial`'s `freshness_disqualified` parameter was **removed from the function signature entirely** (not merely defaulted to `False`) — calling it with that keyword now raises `TypeError`. The gate is DSL-validity alone. This was a deliberate choice, not the minimal one: leaving a dead, ignored parameter would let a future edit silently re-enable gating by adding back two lines; removing the parameter forces a visible signature change and a new decision.
- `apply_fdr_correction`'s freshness exclusion was removed from both the `indices_with_p` filter and the `excluded_from_fdr_family_reason` construction — its `is_self_derivative` exclusion is untouched, byte-identical to the code before item 7 ever existed.
- **Kept exactly as before, per explicit instruction:** `check_freshness_disqualification`, `apply_freshness_disqualification`, `is_freshness_disqualified`, the item 7a audit fields (`freshness_disqualified`, `freshness_disqualification_reason`, `offending_source_url`, `parsed_pub_date`, `rule_fired`), and item 7b's fail-loud `freshness_disqualified_entire_session` warning all still compute, record, and fire exactly as they did before this correction. Verified directly: re-running the real Session 1 file through the informational machinery still produces `freshness_disqualified=True` on all 6 records and 4 real audit flags — only the two BINDING consequences were removed.

**Tests — rewritten, not deleted:**
- `tests/test_trial_admission.py`: removed `test_freshness_disqualified_hypothesis_is_rejected_even_if_dsl_valid` (asserted the reverted behavior) and rewrote `test_freshness_flag_defaults_to_false_so_admission_works_without_item_7_wired` → `test_dsl_valid_hypothesis_is_admitted_with_no_freshness_argument_at_all`. Added a new `AdmitToTrialNeverConsultsFreshnessTest` class (3 tests): the signature genuinely has no `freshness_disqualified` parameter; passing it raises `TypeError`; and an end-to-end proof that runs the REAL informational item 7 machinery to produce a `freshness_disqualified=True` record, then confirms `admit_to_trial` still admits it.
- `tests/test_eve_freshness_disqualification.py`: `FreshnessExcludedFromFdrFamilyTest` renamed to `FreshnessDisqualificationNoLongerAffectsFdrFamilyTest` (not deleted — the rename itself is part of the visible record) and rewritten to assert a freshness-disqualified record now participates in the FDR family normally, and that combining self-derivative + freshness-disqualified only ever produces the `"self_derivative"` reason, never a freshness one.
- Both files' module docstrings updated to state the reversal and point to this section and to `eve_session_registry.json`'s own provenance field.
- All 134 tests across `test_trial_admission.py`, `test_eve_freshness_disqualification.py`, `test_eve_scoring_fdr.py`, `test_eve_contamination_tags.py`, `test_eve_pipeline.py`, `test_repair_to_trial.py` pass after the revert.

**Verification of the revert (required — both checks run against the real Session 1 file, `eve-20260804T020749Z-4cf6e4c9`, 2026-08-05):**

(a) **FDR family populated again — confirmed.** Re-scoring Session 1's 6 real records through the reverted `apply_freshness_disqualification` → `apply_fdr_correction` pipeline: `indices_with_p` (real p-values, post self-derivative exclusion) = 2 records; their `fdr_survives_oos` values = `[None, False]` — **not all `None`**. `BTC_MOMENTUM_IGNITION` gets a real `fdr_survives_oos=False`, proving the family is genuinely populated, not degenerately empty.

(b) **No verdict/p-value/status differs from Session 1's committed record — confirmed, zero diffs.** Compared every one of `verdict_combined`, `verdict_is`, `verdict_oos`, `p_value_is`, `p_value_oos`, `fdr_survives_oos`, `fdr_survives_is` between the post-revert re-score and the currently-committed `docs/site_data/eve_hypotheses.json` records for all 6 Session 1 hypotheses: **zero differences.** This was expected but confirmed rather than assumed — the committed file was never touched by any binding-gate code in the first place (see item 2 below), so this check also serves as independent proof that item 2's "none found" finding is consistent with the actual data.

No difference in (b) means no stop-and-report was triggered by this step.

## 2. Data written under the binding rule while it was live

**FINDING:** searched every location a binding-rule effect could have been written. **CONFIDENCE:** confirmed-from-data (direct inspection, not inferred).

**WHAT WAS FOUND: none.**
- `docs/site_data/eve_hypotheses.json` (16 records): zero with `freshness_disqualified: true`; zero with `excluded_from_fdr_family_reason` containing `"freshness_disqualified"`.
- All 3 real files under `docs/site_data/eve_sessions/` (`eve-20260803T095520Z-394385c7.json`, `eve-20260803T142519Z-718833c9.json`, `eve-20260804T020749Z-4cf6e4c9.json`) predate commit `61d78a8` and carry no `freshness_disqualified_entire_session` or `freshness_disqualification_flags` field at all — the informational machinery had never even been run against any of them.
- `docs/site_data/forward_trial.json` does not exist on disk — nothing has ever been admitted to or rejected from Trial under any rule, binding or informational.

No records were modified during this search (identification only, per the directive's own instruction). This is the expected finding: `EVE_ENABLED=False` throughout, so no real Eve session ran between the gate shipping and being reverted, both the same day.

## 3. Reversal recorded in the pre-registration, dated

**WHAT SHIPPED:** `docs/site_data/eve_session_registry.json`'s `pre_registration` now carries a new `freshness_gate_reversal_provenance` object: `enabled_dated: "2026-08-05"`, `enabled_commit: "61d78a8"`, `reverted_dated: "2026-08-05"`, a full `reason` field stating the session-scoped-attribution root cause and the unsatisfiable-per-session-bar consequence, `any_countable_session_ran_while_binding: false` with its own `_basis` field citing the exact data checked (the same search as item 2 above), and a `homogeneity_confirmation` field.

**Homogeneity — confirmed from data, not asserted:** because no countable session ran between the gate shipping and being reverted (both the same day), Session 1 (the only countable session to date) and Sessions 2–8 (not yet run) will all run under the identical rule set — informational-only freshness disqualification, DSL-validity-only Trial admission, self-derivative-only FDR exclusion. The 8-session pre-registered experiment remains homogeneous.

**Test:** `tests/test_eve_session_registry.py::test_freshness_gate_reversal_is_recorded_with_dates_and_confirmed_homogeneity` — asserts the commit reference, the dates, that the reason text names the real root cause (`"SESSION-SCOPED"`, `"unsatisfiable"`), and that homogeneity is confirmed. Passes.

## 4. Root cause — is per-hypothesis attribution derivable?

**FINDING: yes, structurally derivable — both sides of the comparison already exist in committed data.** **CONFIDENCE:** confirmed-from-data (direct inspection of the real Session 1 session file and its corresponding `eve_hypotheses.json` records).

- Every Eve hypothesis record already carries a real, distinct `turn_index` (`nero_core.eve.hypothesis_shapes.build_hypothesis_record`'s own field) — Session 1's 6 hypotheses have `turn_index` 0 through 5, one per proposal, in order.
- `_iter_web_search_results` (the shared helper `tag_lookahead_risk` and `check_freshness_disqualification` both already use) already captures `turn_index` per search result.
- Real check: all 16 web-search results in Session 1 occur at `turn_index=0`.
- **Deeper check, beyond turn-level granularity:** turn 0's own `raw_response.content` array was inspected block-by-block. Every `web_search_tool_result` block (array indices 6, 7, 10, 14, 19, 20) appears **before** the `propose_hypothesis` tool-use block for `PAXG_PEG_REVERSION` (index 27) — the very first hypothesis of the session, nominally at the "same" `turn_index=0` as the searches. Confirmed directly, not inferred: even the earliest hypothesis was causally proposed after every real search, at the content-block level.

**Applying the directive's own specified rule** ("a hypothesis proposed at turn K may have been informed by any search at turn ≤ K" — over-inclusive, never under-inclusive, the causally safe direction): **all 6 of Session 1's hypotheses would still be attributed to the 2 disqualifying sources.** Real per-hypothesis disqualification rate under this rule: **100%, identical to the session-wide rate** — not because finer attribution is impossible, but because Eve's real behavior in this one session was to front-load all web searching in the first turn, then propose all 6 hypotheses sequentially afterward. Every hypothesis genuinely comes causally after every search in this session's real transcript.

**This is not evidence that per-hypothesis attribution is worthless — it is evidence that this ONE real session cannot distinguish it from session-wide scoping.** Attribution would diverge from session-wide in a session with an interleaved search → propose → search → propose pattern (an earlier hypothesis legitimately excluded from a later search's disqualification). Session 1 has zero such interleaving. **No alternative is proposed** — the directive's "propose 1–2 alternatives" instruction applied only to the not-derivable branch, and attribution was found to be derivable. **Nothing was implemented or enabled** — this is a report-only finding, per item 5.

## 5. No binding re-enable

Confirmed: nothing in this correction re-enables binding disqualification anywhere. `admit_to_trial` has no code path that can consult `freshness_disqualified` (the parameter does not exist). `apply_fdr_correction` has no code path that references `is_freshness_disqualified`. Item 4's attribution finding was implemented nowhere — it exists only as an analysis in this report and in the scratch investigation that produced it.

## 6. Process note, applied to this document

No option in this correction — or anywhere in the original report above — is labeled "(Recommended)." Where a decision remains open (there is none remaining in this correction; item 4 found no binding action was proposed to begin with), findings are reported with their real consequences and no default is pre-selected.

## Test counts, this correction

**Python, targeted:** 134 tests across the 6 directly-affected files (`test_trial_admission.py`, `test_eve_freshness_disqualification.py`, `test_eve_scoring_fdr.py`, `test_eve_contamination_tags.py`, `test_eve_pipeline.py`, `test_repair_to_trial.py`) — all pass. Net test count change: `test_trial_admission.py` +3 (one test removed, one renamed in place, three added — net `AdmitToTrialNeverConsultsFreshnessTest` adds 3), `test_eve_freshness_disqualification.py` net unchanged (2 tests rewritten in place, one class renamed), `test_eve_session_registry.py` +1 (`test_freshness_gate_reversal_is_recorded_with_dates_and_confirmed_homogeneity`).

**Full suite, Python** (`python -m unittest discover -s tests`): **2491 tests, same 3 pre-existing errors (lxml/PSX, unrelated, unchanged), 0 failures.** Delta from the prior full-suite checkpoint (2488): **+3**, reconciling exactly: `test_trial_admission.py` net +2 (one test removed, one renamed in place net-zero, `AdmitToTrialNeverConsultsFreshnessTest` adds 3 → net −1+3 = +2), `test_eve_freshness_disqualification.py` net 0 (two tests rewritten in place, one class renamed, same count), `test_eve_session_registry.py` +1. Zero new failures.

**Full suite, website** (`npx jest`): **598 tests, 596 passing, same 2 pre-existing failures** (`siteDataSchema.test.ts`, unrelated to this correction — this correction touched no website files, confirmed by `git diff --stat` showing zero website changes in this correction's own diff).
---

# CC-1 — Factory Loop Rollout Closeout (2026-08-05)

Context: `61d78a8`, `3697e75`, and `c7f4df9` sat unpushed for two days before
this directive; that gap is resolved and confirmed (see item 0). This
section covers the four remaining items from the closeout directive: the
missing nav link, Adam's web-search ReadTimeouts, unaccounted spend
visibility, and the /lab panels that contradicted each other in public.

## Item 0 — push verification

Confirmed before starting: `git log origin/main --oneline -3` and
`git log --oneline -3 main` both returned `d8ba923` at HEAD, with zero
commits in either `main..origin/main` or `origin/main..main` -- local and
remote were already in sync at the start of this directive (the prior
session's merge-and-push had, in fact, landed). Every commit made in this
directive is verified the same way below, real output pasted, not the
commit step's own exit code.

## Item 1 — Factory Loop nav link

**FINDING:** the site nav is defined in exactly one place,
`website/app/layout.tsx:22-44` (`RootLayout`'s `<nav>` block) -- confirmed
by grep across the whole `website/` tree for `<nav`: one match, this file.
There is no separate mobile-markup nav component anywhere (`components/`
has no `Nav`/`Menu`/hamburger component; grepped for one and found none),
so "confirm it renders on mobile as well as desktop" is satisfied
structurally: the new link is inside the SAME markup both viewports render,
not a second copy that could be missed. One real, pre-existing (not
introduced by this change) limitation worth naming: the nav has no
`flex-wrap`/scroll handling in `globals.css` (grepped, no matches), so on a
narrow viewport all 8 links now sit in one non-wrapping flex row -- a
pre-existing condition, not a regression from adding an 8th link, and out
of this item's scope to redesign.

**Existing-test check:** grepped `website/__tests__/` for any reference to
`RootLayout` or `app/layout` -- zero matches. No test asserts the exact nav
item list, so nothing needed updating (per the directive's own
"check first" instruction).

**Placement -- three options considered, not picked silently:**
1. **Between Graveyard and Lab** (chosen). Groups the three
   research-transparency pages narratively: Graveyard (dead mechanisms) ->
   Factory Loop (the process that produces and repairs them) -> Lab (the
   live workbench where Repair Candidates and the Research Agent panel
   live). Matches the directive's own suggestion.
2. Immediately after Lab. Ties it to the page it's most operationally
   adjacent to (Lab's own "Repair Candidates" section is part of the same
   loop), but breaks the Graveyard->Factory Loop narrative adjacency and
   reads as an afterthought appended to an existing pair.
3. At the end, before Pricing. Signals "newest/most experimental" but
   isolates it from every other research-transparency page, which is the
   opposite of what a reader trying to understand "what is this site
   actually showing me" would want.

**CONFIDENCE:** confirmed-from-code.

**WHAT SHIPPED:** `website/app/layout.tsx` -- one `<Link href="/factory-loop">`
inserted between the Graveyard and Lab links. Committed and pushed (see
item 0's `git log origin/main` output below, commit `9baf3ab`).

**Live-URL verification: UNABLE TO VERIFY, stated plainly rather than
guessed at.** This repository carries no deploy workflow under
`.github/workflows/` (grepped: only `scheduler_heartbeat_check.yml`,
`health_check.yml`, `live_scheduler.yml`, `research_agent_manual.yml` exist
-- none builds or deploys the website) and no live domain is recorded
anywhere in the repo (grepped for `vercel.app`/`pages.dev`/a project
domain -- zero matches). The site is evidently deployed by an external
service outside this repository's own files (most likely a host with its
own GitHub integration, given the directive's own mention that `/lab` and
`/factory-loop` are already live) -- but this agent has no record of that
URL and, per standing instruction, will not guess or fabricate one to
"verify" against. **The nav link change is shipped and pushed; visual
confirmation on the real live URL needs to be done by whoever has that
URL** -- flagged here rather than silently skipped or falsely claimed.

## Item 2 — Adam's web-search timeouts (investigation only, nothing implemented)

### 2a — mechanism, confirmed from code

- **Call site:** `nero_core/research_agent/hypothesis_gen.py:426-471`
  (`_call_claude`) -- a single, shared, raw `requests.post` (line 448),
  non-streaming (the full response is awaited as one JSON body via
  `response.json()`, line 464), used by BOTH the scanner channel and the
  web-search channel.
- **Timeout shape:** `timeout=params.claude_timeout_seconds` (line 456),
  where `claude_timeout_seconds: int = 180` (line 217) is a plain **scalar
  int**, not a `(connect, read)` tuple. `requests` applies a scalar to both
  the connect and read phases independently -- the real error text confirms
  it is the READ phase that trips: `ReadTimeout: ...Read timed out. (read
  timeout=90)` (verbatim from the live `/lab` data), which is specifically
  "no bytes received within this many seconds," not "total request
  duration capped at this many seconds." This is consistent with (not yet
  proof beyond doubt of, but strongly corroborating) the idle-time-between-
  bytes hypothesis: a scalar read-timeout fires on a silent gap, and
  Anthropic's own error docs (cited in the directive) describe exactly that
  gap for a long server-side operation on a non-streaming connection.
- **Scanner vs. web-search channel:** confirmed these are the ONLY two
  callers of `_call_claude`. The scanner channel calls it at line 772 with
  no `tools` argument at all. The web-search channel calls it at line 1111
  with `tools=[WEB_SEARCH_TOOL]`. This is the one structural difference
  between the two, and it lines up exactly with the real data (only the
  web-search channel has ever produced a `ReadTimeout` in this repo's
  history) -- server-side search execution is the only thing that could
  produce the long silent gap on one channel and not the other, since every
  other part of the request (model, prompt, headers, timeout config) is
  identical between them.
- **Does Eve make the same class of call?** Yes, confirmed structurally
  identical: `nero_core/eve/llm_client.py::call_turn` (lines 310-345 area)
  makes a raw, non-streaming `requests.post` with
  `timeout=params.claude_timeout_seconds` (a scalar int,
  `claude_timeout_seconds: int = 180` in `LlmParameters`), and Eve's own
  `default_tools()` (`nero_core/eve/tools_defs.py`) ALWAYS includes
  `WEB_SEARCH_TOOL` in every turn's tool list -- there is no Eve call that
  omits the search tool the way Adam's scanner channel does. Eve is **not
  structurally immune**. She is also not merely theoretically at risk:
  `docs/site_data/eve_session_registry.json`'s own crashed-session entries
  record two real `ReadTimeout` crashes at the old 60s ceiling
  (`eve-20260803T074058Z-df7df0f9`, `eve-20260803T075102Z-2b98a5f0`) and one
  more at the 120s ceiling (`eve-20260804T015806Z-243d095f`) before 180s was
  adopted -- the exact same failure mode Adam's web-search channel is
  showing now, at lower ceilings. The honest read: 180s has not yet been
  exceeded in Eve's real usage so far (her one real completed session,
  Session 1, made only 2 real web searches, well under
  `WEB_SEARCH_TOOL`'s own `max_uses=5` ceiling) -- "hasn't hit it yet," not
  "immune."
- **One more real-data point, not asked for but relevant to 2b:** the most
  recent 180s run (2026-08-04T11:10:43) still had **1 ReadTimeout out of 3
  calls**, not zero -- 180s reduced the failure rate (0->2 hypotheses
  generated versus the 90s run's 0) but did not eliminate it. This
  corroborates the "a larger timeout only moves the cliff" part of the
  hypothesis with real, not hypothetical, data.

**CONFIDENCE:** confirmed-from-code, confirmed-from-data.

### 2b — options, not implemented

1. **Streaming.** Structurally impossible for this failure mode (SSE events
   arrive continuously during server-side search execution, so there is
   never a multi-second gap with zero bytes for a scalar read-timeout to
   trip on) -- the same standard this project already applied when it set
   `thinking: {"type": "disabled"}` instead of merely raising a budget.
   **Real cost, not estimated:** grepped every test that mocks the current
   flat `requests.post` -> single-JSON-body shape --
   `tests/test_research_agent_hypothesis_gen.py` (34 `requests.post`
   references), `tests/test_research_agent_web_hypothesis_gen.py` (15), and
   `tests/test_eve_llm_client.py` (6) -- roughly **55 real call sites**
   across 3 files would need reworking from a single `_FakeResponse(payload)`
   to a sequence of SSE events. Response assembly would need to accumulate
   `content_block_start`/`content_block_delta`/`content_block_stop` events
   into the same `content` array shape callers already expect; usage
   extraction would need to combine `message_start`'s initial `usage` (input
   tokens, cache fields) with `message_delta`'s final `usage` (output
   tokens) instead of reading one flat `payload["usage"]`.
2. **Message Batches API.** Removes the held connection (and its read-
   timeout exposure) entirely -- poll for a result instead. Real structural
   cost: Adam's run would no longer complete inside one synchronous
   `python -m nero_core.research_agent.pipeline` invocation, which changes
   `research_agent_manual.yml`'s own execution model (a single-job,
   single-run workflow today) into something that must either poll within
   the same job (adds real wall-clock job time, GitHub Actions jobs have
   their own ceiling) or split into a submit step and a separate,
   later-triggered ingest step.
3. **Keep non-streaming, raise again with retry/backoff.** Cheapest change,
   does not address the mechanism -- confirmed above that raising 90s->180s
   reduced but did NOT eliminate the failure (1/3 calls still timed out on
   the most recent 180s run). Confidence on a further specific number: LOW
   -- the real sample is two error runs total (90s: 3/3 failed; 180s: 1/3
   failed), not enough to fit a real distribution of server-side search
   duration. Any next number would be a guess dressed as data.

**Recommendation: streaming (option 1)**, for the same reason CC-2 chose a
structural fix over a bigger budget for the thinking-token failure --
option 3 has now been tried once (90s->180s) and already demonstrably
did not fully solve it, and option 2 changes the workflow's execution
model more than the goal requires. This is a recommendation, not an
implementation -- nothing was changed.

**Note on a tension in this directive's own instructions:** item 2b asks to
"add a test that fails if the code silently reverts to a non-streaming long
call," while the OUT OF SCOPE section separately states "implementing item
2's chosen fix before it is confirmed" is out of scope. A regression test
for a mechanism that does not exist in the code yet cannot be written
without first building at least a stub of that mechanism -- doing so would
itself be a form of implementing ahead of confirmation. Per the standing
"report, do not implement" instruction (which is the more specific, more
repeated rule throughout this directive), **that test is deferred alongside
the implementation**, not written now. Flagged here explicitly rather than
silently resolved in one direction.

## Item 3 — unaccounted spend, made visible

**FINDING, real totals (confirmed-from-data, `docs/site_data/agent_performance.json`,
the real committed file):** `cumulative.calls_with_unknown_cost = 4`,
`cumulative.total_llm_cost_usd = 0.55804` (~$0.56). Split across the two
error runs, confirmed per-run: `2026-08-04T10:55:25` (90s ceiling) --
3 calls of unknown cost, $0.0 recorded that run; `2026-08-04T11:10:43`
(180s ceiling) -- 1 call of unknown cost, $0.55804 recorded that run.
Matches the directive's own table exactly -- no stale figure found here.

**Display component:** `website/components/ResearchAgentPanel.tsx`'s
"Cumulative API cost" `Stat` tile. Confirmed (grep across `website/`) that
`calls_with_unknown_cost` was referenced NOWHERE on the website side before
this change -- not in `lib/types.ts`, not in any component -- so the gap
described in the directive ("nothing surfaces the gap") was real and total,
not partial.

**WHAT SHIPPED:**
- `website/lib/types.ts` -- `calls_with_unknown_cost`/`web_calls_with_unknown_cost`
  added as optional fields on `AgentPerformanceCumulative` (and
  `calls_with_unknown_cost` on `AgentPerformanceRun`) -- optional because
  the two pre-instrumentation 2026-07-29 runs predate the field existing at
  all; absence must read as "not tracked yet," never "0."
- `website/components/ResearchAgentPanel.tsx` -- the stat's value changed
  from `"$0.56"` to `"$0.56 recorded"`, with a conditional muted note
  (`data-testid="agent-cost-unknown-note"`) reading `"N calls of unknown
  cost, not included above"` whenever `calls_with_unknown_cost` is nonzero,
  omitted entirely when it is zero/absent (so a genuinely complete run
  never reads as incomplete).
- Tests: `website/__tests__/ResearchAgentPanel.test.tsx` -- 2 new tests
  (note shown when nonzero, note absent when zero/absent), plus the one
  existing test asserting the old `"$0.15"` text updated to `"$0.15
  recorded"`.

**Proposed, NOT implemented, per the directive's own instruction --
bounding the unknown, 2 options:**
1. **Estimate from a comparable successful call's input-token count.**
   Every web-search call in a run shares the same prompt-building function
   (`_build_web_search_prompt`), so a successful call's own
   `usage.input_tokens` from the SAME run (or, absent one, the most recent
   prior successful web-search call) is a reasonable proxy for what the
   timed-out call's input side cost, at the known `input_cost_per_mtok`
   rate. The OUTPUT side has no comparable proxy at all (a timed-out call
   never produced output) -- this can only ever bound the input-token
   portion, and that must be labeled `estimated_cost_usd` (or similar) and
   kept structurally separate from `total_llm_cost_usd`'s own append-only
   ledger meaning, never summed into it.
2. **Don't estimate a number at all; report a range using the run's own
   max possible cost** (i.e., every unknown call assumed to be the same
   size as the run's largest real call, as a stated upper bound) rather
   than a false-precision point estimate. Cheaper to implement and harder
   to over-trust than option 1's single number, at the cost of a wider,
   less useful range.
No recommendation is stated between these two -- per the directive, this
item is report-only.

## Item 4 — the /lab panels contradicted each other in public

### 4a — TOO_SLOW panel: confirmed cause, confirmed fixable with real data

**FINDING:** confirmed cause exactly as the directive suspected, from
`.github/workflows/research_agent_manual.yml`:
`agent_hypotheses.json` is uploaded as a workflow artifact only (lines
41-56, deliberate human-review gate, unchanged and correct). But **one
real, unplanned finding beyond what the directive assumed:**
`agent_test_results.json` -- which the workflow's own "Commit test
results" step (lines 58-83, CC-1 review item 1a) is SUPPOSED to commit on
every run -- has **zero git history** (`git log --all --oneline --
docs/site_data/agent_test_results.json` returns nothing) and is not
currently tracked in this repo at all (`git ls-files` confirms). The
intended commit step appears to have never successfully landed a commit;
this is exactly the class of silent-push-failure this whole directive
opened with (item 0), just on a different workflow. Flagged here plainly,
not fixed (out of this item's scope -- item 4a is about wiring the panel
to real committed data that already exists, and `agent_test_results.json`
is not that).

`agent_run_summaries.json` **is** committed (confirmed tracked in git) and
its real, most recent entry (`run_at: "2026-08-04T11:19:56.922724+00:00"`)
carries a `too_slow` array with two real names:
`RSI2_TREND_PULLBACK_PAXG_4H` (measured 0.498 trades/year, claimed 35.0)
and `ADX_REGIME_IGNITION_SOL_4H` (measured 16.94 trades/year, claimed 45.0)
-- exactly the 2 that `agent_performance.json`'s own
`cumulative.too_slow_rejected = 2` already counts (confirmed these two
numbers reconcile, not just resemble each other).

**One more honest limitation, confirmed from the same file and worth
stating plainly rather than silently under-representing:** the file's
FIRST entry (`run_at: "2026-08-03"`, explicitly marked `"backfilled": true`)
carries `too_slow: null` with `"data_completeness": "aggregate_only --
per-hypothesis names and individual claim/measured values are NOT
available and are not fabricated here"` -- 9 additional real TOO_SLOW
rejections happened on 2026-08-03 with NO hypothesis names ever captured
anywhere, predating per-hypothesis tracking. Wiring this panel to real
names surfaces 2 of at least 11 real TOO_SLOW rejections this platform has
produced -- an improvement from 0, not a claim of completeness.

**WHAT SHIPPED:**
- `website/lib/types.ts` -- new `AgentRunSummaryTooSlowEntry`/
  `AgentRunSummary` types (deliberately minimal: only the fields this site
  reads, not the full real schema -- see that type's own comment).
- `website/lib/data.ts` -- new `fetchAgentRunSummaries()`.
- `website/app/lab/page.tsx` -- fetches it, passes as a new `runSummaries`
  prop.
- `website/components/ResearchAgentPanel.tsx` -- the TOO_SLOW panel now
  merges `testResults`-sourced rows (richer `reason` text, currently
  empty in practice since that file isn't committed -- see above) with
  `runSummaries`-sourced rows (real names, thinner synthesized reason text),
  deduplicated by `hypothesis_name`, testResults preferred on overlap --
  this fixes the panel today AND keeps `agent_test_results.json` wired in
  for the day its own commit step starts landing successfully.
- Tests: 3 new tests in `ResearchAgentPanel.test.tsx` (populates from
  runSummaries, null `too_slow` entry handled without crashing, dedup
  prefers testResults) + 1 new integration test in `labPage.test.tsx`
  wiring the real fetch end to end.

### 4b — Findings panel: three real states, no raw text committed

**FINDING:** confirmed the panel (`ResearchAgentPanel.tsx`'s "Research
Agent Findings" section) reads `hypotheses` (from `agent_hypotheses.json`,
artifact-only, never committed -- confirmed above). Under that correct,
unchanged gate, `hypotheses.length === 0` is true on every single run
regardless of what was generated -- "No hypotheses generated yet" is not
stale copy, it is **permanently false** the moment any run generates
something, exactly as the directive states.

**WHAT SHIPPED:** the empty-state branch now checks
`cumulative.hypotheses_generated` (a committed, DERIVED count from
`agent_performance.json` -- never the raw proposal text itself, so the
no-raw-text rule is not touched) to distinguish:
- nothing generated (`agent-hypotheses-empty`, unchanged copy)
- generated, pending review (`agent-hypotheses-pending-review`, new --
  "N hypothesis(es) generated so far, pending human review — raw proposal
  text is not published here until reviewed")
- generated and published (existing hypothesis-card grid, unchanged,
  reachable once `hypotheses.length > 0`)

Tests: 3 new tests in `ResearchAgentPanel.test.tsx` covering all three
states explicitly.

## Out-of-scope confirmations

- **No raw `agent_hypotheses.json` proposal text committed anywhere** --
  confirmed: this directive's only Python-adjacent work was reading code
  for item 2's investigation; zero Python files were touched (`git diff
  --stat` for this directive's changes shows only `website/` files).
- **Evidence-bar constants unchanged** -- zero Python files touched at all
  this directive (confirmed via `git diff --stat`), so
  `MIN_SAMPLE_SIZE`/`TARGET_RESOLVED_TRADES`/`FAST_MAX_MONTHS`/
  `VIABLE_MAX_MONTHS`/`DEFAULT_FDR_ALPHA`/`FRESHNESS_DISQUALIFICATION_WINDOW_DAYS`
  are structurally unchanged. The prior session's
  `tests/test_eve_citation_freshness.py::ConstantsUncnhangedTest` (asserting
  all six values) still exists and still passes -- re-run as part of this
  directive's own full Python suite (see test counts below), not merely
  assumed carried over.
- **No binding freshness disqualification re-enabled** -- untouched;
  `nero_core/research_agent/trial.py` and `nero_core/eve/scoring.py` were
  not touched this directive.
- **Eve's session/tool loop untouched** -- confirmed, zero changes to
  `nero_core/eve/session.py` or any other Eve module this directive.
- **Item 2's chosen fix (streaming) NOT implemented** -- report only, see
  above.
- **Item 3's estimation approach NOT implemented** -- report only, see
  above.
- **No change to page content, counts, or the Factory Loop diagram itself**
  beyond what items 1/3/4 explicitly required (the nav link, the cost note,
  the TOO_SLOW rows, the Findings copy) -- confirmed via `git diff --stat`
  for this directive: `website/app/layout.tsx`, `website/app/lab/page.tsx`,
  `website/components/ResearchAgentPanel.tsx`, `website/lib/data.ts`,
  `website/lib/types.ts`, and the two test files. No `FactoryLoopDiagram.tsx`
  or `factory-loop/page.tsx` change.

## Test counts, this closeout

**Python:** zero Python files touched this directive (confirmed via `git
diff --stat`) -- before and after are the SAME real run, re-executed to
confirm rather than assumed: `python -m unittest discover -s tests` ->
**2521 tests, OK (0 failures, 0 errors)**, identical to the prior session's
own final count.

**Website, before this closeout:** 598 tests, 596 passing, 2 pre-existing
failures (`siteDataSchema.test.ts`, unrelated -- `failure_patterns.json`
schema gaps, untouched by this directive).

**Website, after this closeout:** `npm test` -> **607 tests, 605 passing,
the SAME 2 pre-existing failures** (identical failure output, confirmed).
Delta: **+9**, reconciling exactly: 8 new tests in
`ResearchAgentPanel.test.tsx` (2 for item 3's unknown-cost note, 3 for item
4a's merged TOO_SLOW rows, 3 for item 4b's three Findings states) + 1 new
integration test in `labPage.test.tsx` (item 4a's end-to-end wiring).

## A2/A3 preservation, confirmed

- **A2 (180s timeout)** -- confirmed unchanged:
  `nero_core/research_agent/hypothesis_gen.py:217`,
  `claude_timeout_seconds: int = 180`, read (not modified) for item 2's
  investigation.
- **A3 (UNKNOWN-cost honesty)** -- confirmed unchanged: `hypothesis_gen.py`'s
  `RejectedBeforeTokenProcessingError`/`ResponseParseError` distinction and
  `nero_core/research_agent/performance.py`'s own
  `calls_with_unknown_cost` accounting were not touched. Item 3's website
  change SURFACES that existing honest accounting for the first time; it
  does not alter how the accounting itself works.

## git log origin/main --oneline -3

Real, pasted output after `git fetch origin` following the push of this
section's own commit:

```
9baf3ab CC-1 Factory Loop rollout closeout: nav link, /lab honesty fixes
d8ba923 Merge remote-tracking branch 'origin/main'
c7f4df9 CC-1: per-hypothesis freshness attribution via explicit source citation
```

Confirmed landed -- `9baf3ab` (this closeout's own commit) is at the top of
`origin/main`, not just the local `main` branch.

## Stale figures found in this directive, and the real values

The directive's own item 2 table and item 3's "4 calls across the two
error runs" figure were both checked against the real, current
`docs/site_data/agent_performance.json` and matched exactly -- **no stale
figure found in either.** One figure the directive did not state, but which
this investigation surfaced as newly-relevant: `agent_test_results.json`'s
own git history is currently **empty** (0 commits), which the directive
did not know when it described `agent_run_summaries.json` as `agent_test_results.json`'s
committed sibling -- both are real files, but only one of the two has ever
actually landed a commit. See item 4a above.
---

# CC-1 MASTER DIRECTIVE — Agent Visibility & Operation (2026-08-05)

Format per item: FINDING → CONFIDENCE → RECOMMENDATION or WHAT SHIPPED.

## Item 0 — push verification, every commit

Confirmed at the start: local `main` and `origin/main` both at `c310a41`
(no divergence). Three commits made this directive, each fetched-and-
merged against any new automated-log commits before pushing (never force),
then verified against `origin/main` directly:

1. **Phase 1.1** (`4ae7c49`) — merged one intervening automated commit
   (`f8e98a2`, "Update live scheduler execution log", zero file overlap),
   pushed, confirmed: `git log origin/main --oneline -3` →
   ```
   4ae7c49 CC-1 Master Directive Phase 1.1: Eve crash-safety
   f8e98a2 Update live scheduler execution log
   c310a41 CC-1 closeout: state item 1's live-URL verification as unable-to-verify
   ```
2. **Phase 2** (`162b20b`) — no divergence at push time, confirmed:
   ```
   162b20b CC-1 Master Directive Phase 2: the Agents tab
   4ae7c49 CC-1 Master Directive Phase 1.1: Eve crash-safety
   f8e98a2 Update live scheduler execution log
   ```
3. **This report** — committed `a36d75c`, pushed with no divergence,
   confirmed via `git fetch origin && git log origin/main --oneline -3`:
   ```
   a36d75c CC-1 Master Directive: closing report (Phase 1.1, 1.2, 2, 3)
   162b20b CC-1 Master Directive Phase 2: the Agents tab
   4ae7c49 CC-1 Master Directive Phase 1.1: Eve crash-safety
   ```

**CONFIDENCE:** confirmed-from-data (real `git log origin/main` output,
not the commit/push step's own exit code, per the standing rule).

---

## PHASE 1.1 — Eve crash-safety

**FINDING:** confirmed exactly as the directive stated: `session.py`'s
turn loop caught only `RejectedBeforeTokenProcessingError`; any other
exception (a `ReadTimeout` from the bare `requests.post` in
`llm_client.call_turn`) propagated past `run_session`'s own final write
block, losing the whole session — including hypotheses from earlier
successful turns, since `hypothesis_records` was flushed exactly once, at
the end.

**WHAT SHIPPED** (`nero_core/eve/session.py`, `nero_core/eve/pipeline.py`,
`nero_core/eve/budget_ledger.py`; committed `4ae7c49`):

- **1.1a — incremental persistence.** Each turn's newly-finalized
  `propose_hypothesis` records are now written to `eve_hypotheses.json`
  immediately (`storage.append_json_list`, already a documented no-op on
  an empty list — see its own docstring) right after they're extracted,
  not accumulated and flushed once at the end. The old end-of-function
  bulk write is **removed**, not left alongside the new per-turn one — it
  would otherwise double-write every entry on a normal, uncrashed
  completion. Confirmed by `CrashSafetyTest::test_normal_completion_does_not_double_write_hypotheses`.
- **1.1b — partial session record on crash.** The entire turn loop is now
  wrapped in `try:`/`except Exception as exc:`. On any exception, a
  **partial** session record is written to the SAME
  `storage.session_record_path(session_id)` a normal completion would use
  — `terminated_because: "crashed_mid_session"` (new constant
  `TERMINATION_CRASHED`), `crash_reason` (the real exception class+message),
  `turn_reached`, the full `turns_log`, and every hypothesis this session
  produced before the crash (`partial: true`) — then re-raises, so
  `nero_core.eve.pipeline`'s own crash notification still fires and the
  process still exits non-zero. Confirmed by
  `CrashSafetyTest::test_a_partial_session_record_is_written_on_crash`.
- **1.1c — the budget reservation, corrected from the directive's own
  literal instruction.** The directive asked to "release the budget
  reservation on ANY exception." **This was NOT implemented as literally
  stated — it would have been a real accounting bug, not a fix.**
  `nero_core/eve/budget_ledger.py`'s own module docstring (RELEASE, THE
  THIRD OUTCOME section) is explicit and deliberate: `release_entry`
  (which counts a reservation as a **confirmed $0**) is reserved
  exclusively for `RejectedBeforeTokenProcessingError` (401/403/429 —
  rejected before any token was processed, a REAL confirmed zero). A
  `ReadTimeout`'s real cost is genuinely **unknown** — Anthropic's servers
  may have already started (and billed) processing before the client-side
  timeout fired. Releasing it would claim a confirmed $0 this project
  cannot actually confirm, directly violating budget_ledger.py's own
  stated hard invariant: "UNDER-COUNTING IS THE ONE DIRECTION THIS MUST
  NEVER DRIFT." Instead, a new function, `mark_entry_crashed`, **keeps the
  entry `"reserved"` (still conservatively counted, correct)** and adds
  `crash_reason`/`crash_marked_at` annotation fields, so a future orphaned
  reservation is self-documenting instead of a silent, unexplained
  mystery. Confirmed by
  `CrashSafetyTest::test_the_crashed_turns_reservation_is_marked_not_released`,
  which also proves the entry still correctly blocks a later session's
  budget check (the conservative, correct behavior — the opposite of the
  401/403/429 case).
- **1.1d — name the session in the crash notification.** `session.py`'s
  `_new_session_id` is renamed to the public `new_session_id`, and
  `run_session` now accepts an optional `session_id` parameter (`None`
  mints one internally, exactly as before, for every existing caller).
  `nero_core/eve/pipeline.py::run_pipeline` now mints the `session_id`
  **before** calling `session.run_session`, passes it in explicitly, and
  uses that same captured value in the crash notification
  (`eve_notify.send_failure(..., session_id=session_id)`). Before this,
  `build_failure_message`'s own fallback text — "Eve session FAILED
  (before a session id was assigned)" — was **misleading** in this exact
  case: a session_id genuinely *was* minted, it just wasn't threaded
  through. Confirmed by
  `test_eve_pipeline.py::CrashNotifyTest::test_the_crash_notification_names_the_real_session_id_not_just_a_generic_message`.
  **Incidental correctness improvement, not requested but worth noting:**
  `run_pipeline` now resolves `now` once and passes the SAME value to both
  `session.run_session` and `scoring.score_all` — before this change, a
  `None` `now` would have been independently re-resolved to two slightly
  different real clock reads in each function.
- **1.1e — countability, code-enforced.** New test,
  `test_eve_session_registry.py::RegistryMatchesRealLedgerTest::test_every_countable_session_has_at_least_one_hypothesis_record`
  — cross-checks every `eve_session_registry.json` entry marked
  `counts_toward_pre_registered_8: true` against the REAL, committed
  `eve_hypotheses.json`, asserting at least one hypothesis record exists
  under that `session_id`. Before this, the counting rule was prose in a
  hand-maintained JSON file with nothing enforcing it; passes today
  against the one real countable session
  (`eve-20260804T020749Z-4cf6e4c9`, which has 6 real records).

**Real orphaned reservations — 6, not 3 (a stale figure in the directive,
see the Stale Figures section below).** Reconciliation proposed, NOT
implemented, per the directive's own out-of-scope instruction:

| session_id | classification | projected_cost_usd |
|---|---|---|
| `eve-20260803T074058Z-df7df0f9` | crashed_before_completion (ReadTimeout, 60s ceiling) | $0.098258 |
| `eve-20260803T075102Z-2b98a5f0` | crashed_before_completion (ReadTimeout, 60s ceiling) | $0.098258 |
| `eve-20260803T080243Z-29f48c2e` | crashed_before_completion (400 tool_result protocol bug, fixed same day) | $0.364236 |
| `eve-20260803T080720Z-12e60677` | crashed_before_completion (same 400 bug) | $0.327358 |
| `eve-20260803T081007Z-b7568699` | crashed_before_completion (same 400 bug) | $0.287342 |
| `eve-20260804T015806Z-243d095f` | crashed_before_completion (ReadTimeout, 120s ceiling) | $0.098258 |

Total conservatively counted: **$1.27371**, all against the "2026-08"
month bucket (`month_spent_usd` filters strictly by month string — this
impact is naturally bounded to August; it does not carry forward into
September regardless of whether it's ever reconciled).

**Reconciliation options, real tradeoffs, none implemented or
recommended:**
1. **Leave as-is.** Correct and self-limiting (bounded to August, per
   above). Cost: ~$1.27 of August's $20 ceiling stays locked for the rest
   of the month even though the true spend was likely small or zero.
2. **Manually verify true cost via Anthropic's own billing console** for
   each of the 6 timestamps, then apply a new, explicit
   `manually_reconciled` status recording the verified figure. Requires
   human access outside this repo/session — cannot be done by this agent.
3. **Distinguish the two failure classes before deciding.** The 3
   ReadTimeout-caused entries and the 3 already-fixed-400-bug-caused
   entries are mechanically different (idle-gap timeout vs. a malformed-
   request rejection). Whether a 400 is *always* a confirmed $0 the way
   401/403/429 are is a genuinely open question this project's own code
   does not currently answer — `REJECTED_BEFORE_TOKEN_PROCESSING_STATUS_CODES`
   deliberately excludes 400, which this report treats as intentional
   (not an oversight to silently correct) rather than assuming 400 is
   safe to release.

**CONFIDENCE:** confirmed-from-code (full read of the corrected
`session.py`/`pipeline.py`/`budget_ledger.py`), confirmed-from-data (real
ledger inspection, real registry cross-check), confirmed-from-test (10 new
tests, all passing — 6 in `test_eve_session_termination.py`'s new
`CrashSafetyTest`, 1 in `test_eve_session_registry.py`, 1 in
`test_eve_pipeline.py`'s `CrashNotifyTest`, plus the rename's own
propagation into 1 existing test).

---

## PHASE 1.2 — How to run both agents

Delivered in full in this directive's own mid-conversation response,
before Phase 2 work began (per the directive's own sequencing
requirement). Reproduced here for the permanent record:

**Adam:** workflow `.github/workflows/research_agent_manual.yml`
("Research Agent (manual run)"), `workflow_dispatch` with zero inputs.
Dispatch via GitHub UI, `gh workflow run research_agent_manual.yml`, or
the REST API. Requires `ANTHROPIC_API_KEY` as a repo secret — **cannot
verify from code whether it is actually configured** (GitHub UI only,
unable-to-verify). 180s timeout confirmed deployed (traced
`pipeline.py` → `generate_web_hypotheses`'s own default `params=
DEFAULT_PARAMETERS` → `HypothesisGenParameters()`'s own
`claude_timeout_seconds: int = 180` default, no override anywhere). Real
cost per run: $0 to $0.558 (n=4 real runs, too few for a stable average).

**Eve:** no workflow exists at all (confirmed: grepped every
`.github/workflows/*.yml`, zero references to `nero_core.eve.pipeline`).
Run directly: `EVE_ENABLED=true ANTHROPIC_API_KEY=<key> python -m
nero_core.eve.pipeline`. `EVE_ENABLED` is a plain runtime env var, read
fresh on every `run_pipeline()` call — neither a scheduler switch (none
exists to switch) nor a build-time flag. Session 2 needs no config change,
just the same command — nothing in code caps session count; the 8-session
bar is a human-honored commitment in `eve_session_registry.json`, not a
technical gate. Session 1 real cost: **$0.4273** (recomputed directly from
the real ledger, matches the directive's own figure exactly). New finding
the directive didn't have: **August month-to-date spend is $3.415** of the
$20 ceiling, of which **~$1.27 is the 6 orphaned entries above**, leaving
~$16.59 real headroom.

**API key:** Adam has no stub mode at all (grepped — none exists); cannot
run meaningfully without a real key. Eve has `EVE_STUB_MODE=1` (a fully
deterministic, no-network canned script) but it produces no new real data.

---

## PHASE 2 — The Agents tab

**Item 2.1, checked before building, as instructed:** all three of Eve's
fetchable data sources already live under `docs/site_data/` — confirmed
directly against `nero_core/eve/storage.py`'s own path constants
(`DEFAULT_HYPOTHESES_PATH`, `DEFAULT_BUDGET_LEDGER_PATH`,
`EVE_SESSIONS_DIR`). **No export step needed** for `eve_hypotheses.json`,
`eve_session_registry.json`, or `eve_budget_ledger.json` — `fetchJson`
reaches them exactly like every other site export. **`eve_sessions/<id>.json`
is a directory of one file per session, not a single list** — reading ALL
of them would require first listing session_ids (from the registry) then
fetching each individually (N+1 requests). **Deliberately not fetched this
phase**: `eve_session_registry.json`'s own `classification`/`reason` text
already carries everything the Session Health panel needs (which sessions
crashed, and why, in real prose) without the extra per-session fetches —
a scope decision, not an oversight, stated here rather than silently made.

**WHAT SHIPPED** (committed `162b20b`):
- `website/lib/types.ts` — `EveHypothesisRecord`, `EveSessionRegistryEntry`/
  `EveSessionRegistryExport`, `EveBudgetLedgerEntry` (deliberately minimal
  — only fields this site reads).
- `website/lib/data.ts` — `fetchEveHypotheses`/`fetchEveSessionRegistry`/
  `fetchEveBudgetLedger`.
- `website/lib/agentsPage.ts` (new) — pure derivation functions, kept
  separate and unit-tested (matching `lib/researchScoreboard.ts`'s own
  precedent): `computePreRegistrationProgress`, `computeEveFunnel`,
  `computeAdamFunnel`, `extractFrequencyClaims`.
- `website/app/agents/page.tsx` (new) — the page itself.
- `website/app/layout.tsx` — nav entry, placed alongside the existing
  Factory Loop link, before Lab.

**Every real number on the page, with its source:**

| Panel | Number | Real value | Source |
|---|---|---|---|
| Pre-registration progress | Session N of 8 | Session 1 of 8 | `eve_session_registry.json`, `sessions[].counts_toward_pre_registered_8` |
| | Remaining | 7 | `8 - N`, computed |
| | SURVIVED | 0 | `eve_hypotheses.json`, `verdict_combined === "SURVIVED"` count |
| | Recorded spend | $2.1416 (Eve) + $0.55804 (Adam) | `eve_budget_ledger.json` status="actual" sum; `agent_performance.json` cumulative.total_llm_cost_usd |
| | Unknown-cost calls | Eve: 6 calls, $1.27371 projected; Adam: 4 calls | `eve_budget_ledger.json` status="reserved"; `agent_performance.json` cumulative.calls_with_unknown_cost |
| Eve funnel (Session 1) | 6 → 6 → 5 → 0 | confirmed exact | `eve_hypotheses.json`, filtered to `eve-20260804T020749Z-4cf6e4c9` |
| | 1 TOO_SLOW, 2 SELF_DERIVATIVE | confirmed exact | same, `frequency_classification`/`contamination_tags` |
| Adam funnel (cumulative) | 2 → 2 → 0 → 0 | confirmed exact | `agent_performance.json` cumulative |
| | 2 TOO_SLOW | confirmed exact | same |
| Session health | 6 of 9 crashed | confirmed exact | `eve_session_registry.json`, all 9 entries |
| Claimed vs. measured | RSI2_TREND_PULLBACK_PAXG_4H: 35.0 claimed / 0.50 measured | confirmed exact | `agent_run_summaries.json`, `too_slow[]` |
| | ADX_REGIME_IGNITION_SOL_4H: 45.0 claimed / 16.94 measured | confirmed exact | same |

**One real number the directive named but this page deliberately does NOT
show numerically:** Eve's own `ETH_BIDIRECTIONAL_ZSCORE_FADE` (Session 1's
one TOO_SLOW rejection, 27.4/yr measured) carries a self-claimed
`expected_frequency_per_year` field, but it is a free-text STRING ("85-130
combined across both directions...") rather than a clean number like
Adam's `expected_frequency_claim`. Forcing it into the same "claimed X,
measured Y" numeric row as Adam's two would either mangle the real string
or fabricate false numeric precision — the Claimed vs. Measured panel is
scoped to Adam's two real numeric examples, exactly as the directive
itself named them, and this is flagged here rather than silently decided.

**Out of scope, confirmed not built:** no time-series charts (n=1 countable
Eve session, n=2 Adam hypotheses — a chart would be a straight line; this
becomes meaningful once several more countable sessions/runs exist — no
fixed number is claimed here, since none is derivable from 1-2 data
points). No raw proposal text anywhere on the page — every field read from
`eve_hypotheses.json`/`agent_performance.json`/`agent_run_summaries.json`
is already a derived count, name, or verdict, never `mechanism`/
`raw_hypothesis` free text rendered directly (`EveRawHypothesis`'s own
type only exposes `hypothesis_name`/`asset`/`timeframe`, not `mechanism`).

**Test counts, Phase 2:** 17 new website tests (11 in
`__tests__/agentsPage.test.ts` for the pure lib functions — including a
real-data cross-check against the committed registry file — plus 6 in
`__tests__/agentsPageRender.test.tsx` for the page itself), all pass.

---

## PHASE 3 — Report only, nothing implemented

### 3.1 Running agents from the website

**FINDING:** the site is fully static (`fetchJson` against committed
JSON via `next: { revalidate: 300 }` ISR, confirmed — no API route, no
server component that writes anywhere, confirmed by grep across
`website/app/api/` — that directory does not exist in this repo).
Dispatching a GitHub Actions `workflow_dispatch` requires an authenticated
token with `actions:write` on this repo; that token cannot live in a
public static frontend's shipped JS bundle under any circumstance — it
would be extractable by anyone viewing network requests or source.

**Three real options, no recommendation (deliberate decision needed):**

1. **An authenticated serverless function** (e.g. a small API route on a
   host that supports them, or a separate minimal backend) holding the
   GitHub token server-side, exposing one POST endpoint the site's own
   button calls. *Effort:* moderate — new deploy target/secret
   management, this project currently has none. *Security:* the token
   never reaches the client, but the new endpoint itself becomes a fresh
   attack surface needing its own auth (a shared secret is the minimum;
   anyone who finds the URL and that secret can trigger real spend).
2. **A narrowly-scoped GitHub App** (installed with `actions:write` on
   this one repo only, nothing broader) whose credentials live behind the
   same kind of serverless function as option 1. *Effort:* higher — App
   registration plus the same backend work as option 1. *Security:*
   materially better blast-radius containment than a broad personal
   access token if the credential is ever compromised, since the App's
   own permissions are scoped at creation time, not just by convention.
3. **A manual-trigger page gated behind the owner's own GitHub OAuth
   login**, so no standing token lives in this project's infrastructure
   at all — each dispatch is authorized by the owner's own live GitHub
   session. *Effort:* an OAuth flow (not nothing, but no new secret to
   protect at rest). *Security:* the strongest of the three in one
   specific sense (nothing to steal from this project's own servers), but
   depends entirely on GitHub OAuth's own security model and correctly
   restricting the callback to the owner's account.

**Recommend nothing** — per the directive's own instruction, this needs a
deliberate decision, not a default.

### 3.2 Live repair progress for dead strategies

**FINDING:** `factory_loop_status.json`'s real, current content —
`"repair": {"count": 0, "open_chains": 0, "resolved_chains": 0}`,
`"graveyard": {"count": 21, ...}` — confirmed, matches the directive's own
figures exactly, no stale figure here. Repair Lab v1 is real and tested
(`nero_core/research_agent/repair_lab.py`) but genuinely never launched.

**What launching the first real repair chain would take, confirmed from
code:**
- `check_eligibility(original_result)` (`repair_lab.py:108-158`) requires
  `verdict == VERDICT_DIED` **exactly** — a `SKIPPED` (TOO_SLOW/
  UNMEASURABLE) or `UNTESTABLE` original result is explicitly out of
  scope for v1, by design (TOO_SLOW's only real repair lever would be
  loosening the entry gate, which is the exact gate-gaming behavior
  `frequency_gate.py` exists to prevent — stated directly in
  `check_eligibility`'s own docstring).
- `can_launch_new_attempt(chain_attempts)` (`repair_lab.py:703-716`)
  caps at `MAX_ATTEMPTS_PER_CHAIN = 4`.
- Real, hand-curated candidates already exist:
  `docs/site_data/repair_candidates.json` has **3** entries, each with a
  real written diagnosis — `RANGE_MEAN_REVERSION` (sample-too-thin),
  `BOS_CONTINUATION` (regime-filter-only), `LEADLAG_FOLLOW`
  (grid-shift-artifact).
- **Best candidate: `RANGE_MEAN_REVERSION`.** Its own committed diagnosis
  is qualitatively different from the other two — it states a
  *mechanistically-corroborated positive finding* ("a real... improvement
  from a 'confirmation' filter... shifted BTC/1d's exit mix from 32%
  REGIME_BREAK-dominated to 68% REVERSION_TARGET") that was simply tested
  on the thinnest available config (7-19 trades/half). The other two
  diagnose structural problems with the mechanism itself (a dominating
  stop, a grid-alignment artifact) rather than "the right idea, wrong
  sample" — `RANGE_MEAN_REVERSION` is the one candidate where the
  documented diagnosis already points at a concrete, bounded fix (test
  the SAME confirmation filter on a less-thin config) rather than
  requiring a new mechanism insight.
- **Cost:** one repair attempt is one `propose_modification` LLM call
  (`repair_lab.py:350`) plus one real backtest run — comparable in shape
  to a single Adam hypothesis-generation call, so on the order of
  Adam's own per-call cost (well under $0.20 based on the real per-call
  costs already observed across both agents' ledgers).
- **Human-at-every-step:** yes, confirmed — `repair_lab.py`'s own module
  docstring and this project's standing "nothing auto-wires without human
  approval" rule (already true for Trial admission and graveyard
  distillation) apply identically here; nothing in `repair_lab.py` or
  `research_agent_manual.yml` auto-invokes a repair chain.

**Nothing launched**, per the directive's own explicit instruction.

### 3.3 Scheduling both agents

**FINDING, real arithmetic:**
- Eve's own per-session ceiling: $1.50 (`DEFAULT_SESSION_BUDGET_USD`).
  Real Session 1 cost: $0.4273 — well under the ceiling, but the ceiling
  is the number that must be used for a forward-looking schedule
  projection (a session's real cost varies with how much Eve actually
  does; the ceiling is the honest upper bound to budget against).
- Adam's own real per-run cost: $0 to $0.558 (n=4, see Phase 1.2 above).
- **A DAILY schedule** (both agents once/day): worst case
  `(1.50 + 0.558) × 30 ≈ $61.74/month` against the $20 hard ceiling — the
  ceiling itself would refuse calls once hit (never silently overspend,
  confirmed from `pre_call_check`'s own code), but this means the
  schedule would exhaust the WHOLE month's budget in **under 10 days**
  at worst case (`20 / 2.058 ≈ 9.7` days), and even at Eve's REAL observed
  $0.4273 + Adam's real $0.558 ≈ $0.985/day, that's ~20 days before
  the ceiling binds — leaving no budget for the remainder of most months.
- **A WEEKLY schedule**: worst case `2.058 × 4.33 ≈ $8.91/month` — fits
  comfortably under $20, and burns through the entire ~$14 pre-
  registration budget in **under 11 weeks** (`14 / 2.058 ≈ 6.8` sessions
  worth, i.e. roughly the whole pre-registered 8-session bar in 7-8
  weeks) if BOTH agents ran weekly together.
- **Structural collision with the pre-registered 8-session design:** the
  8-session bar is evaluated as 8 INDEPENDENT, individually-reviewed data
  points (see `eve_session_registry.json`'s own per-session narrative
  classification work — Session 0, 0-B, and the 5 crashes each required a
  human read of what actually happened before being excluded or counted).
  An automated schedule would produce Session 2 through 8 with no human
  reviewing each one's real shape before the next fires — collapsing the
  "deliberate, watched click" discipline `research_agent_manual.yml`'s own
  comment states explicitly for Adam ("every run after it must be a
  deliberate, watched click from the Actions tab, not an automation").
- **Collision with "nothing auto-wires without human approval":** real,
  but narrower than it first appears — a scheduled RUN producing a
  hypothesis does not itself violate this rule (Trial admission, graveyard
  distillation, and repair-chain launch are already separately gated on a
  human, regardless of how the underlying hypothesis was generated). The
  actual collision is with the "each session/run is a deliberately watched
  event," not with any DOWNSTREAM auto-admission — those gates remain
  intact either way.

**Present options, enable nothing:**
1. Keep manual-only (current state) — slowest, but preserves per-session
   human review of the 8-session campaign.
2. Weekly schedule — real arithmetic above fits the $20 ceiling
   comfortably but compresses the whole pre-registered campaign into
   ~2 months and removes the "deliberate click" review step Adam's own
   workflow comment states as a design requirement, not just a habit.
3. Daily schedule — real arithmetic above shows this exhausts the month's
   ceiling in 10-20 days most months; **not viable as designed** without
   either raising `MONTH_CEILING_USD` (a real-money decision, out of
   scope here) or running far fewer real calls per invocation than either
   agent currently makes.

**Nothing enabled.**

### 3.4 Adam's timeout fix — carried forward

Still investigation-only from the prior directive: streaming recommended,
~55 real test call sites across `test_research_agent_hypothesis_gen.py`
(34)/`test_research_agent_web_hypothesis_gen.py` (15)/
`test_eve_llm_client.py` (6), not implemented.

**One clarification this directive's own Phase 1.1 work surfaced, worth
carrying forward precisely:** Adam's `generate_web_hypotheses` (`hypothesis_gen.py:1108-1138`)
**already** catches a `ReadTimeout` per-call, inside its own
`for _ in range(max_calls_per_run):` loop (`except (requests.RequestException,
KeyError, ValueError) as exc: ... calls_with_unknown_cost += 1 ...
continue`) — one timed-out call does NOT lose the whole run for Adam, and
its cost was already tracked as honestly UNKNOWN before this directive
began (the prior directive's own item A3). **Phase 1.1's crash-safety work
was necessary for Eve specifically because her architecture is
fundamentally different — one long multi-turn conversation, not a loop of
independent calls** — Adam never needed the equivalent fix because his
loop shape already contained the failure. So: **Phase 1.1 brought Eve's
resilience posture up to roughly where Adam's already was, architecturally
— it does not change Adam's own situation at all.** Adam's own open
problem remains exactly what the prior directive found: the ReadTimeout
still reduces real THROUGHPUT (fewer real hypotheses produced per run,
confirmed by the real 90s→180s data: 0→2 hypotheses, and even 180s still
lost 1/3 calls on the most recent run) — only the still-unimplemented
streaming fix addresses that.

---

## Out-of-scope confirmations, this directive

- `EVE_ENABLED` was not enabled anywhere in code or CI; no automated
  schedule was created (Phase 3.3, report only).
- No repair chain was launched (Phase 3.2, report only).
- No raw `agent_hypotheses.json`/Eve `mechanism` text was committed or
  rendered anywhere on the new Agents page (confirmed above).
- The streaming fix (Phase 3.4) was not implemented.
- No binding freshness disqualification was re-enabled — zero files under
  `nero_core/eve/scoring.py` or `nero_core/research_agent/trial.py`
  touched this directive.
- Eve's session/tool LOOP STRUCTURE (turn budgeting, DSL retry, tool
  definitions) is unchanged — Phase 1.1 only added exception handling
  around the existing loop, never altered what happens inside a normal
  turn.
- **Evidence-bar constants unchanged, confirmed by test:** zero files
  under `tools/backtest_statistics.py`, `nero_core/research_agent/
  frequency_gate.py`, or the constant-defining sections of
  `nero_core/eve/scoring.py` were touched this directive (confirmed via
  `git diff --stat` across both Phase 1.1 and Phase 2 commits — neither
  touches any of those three files). The existing
  `tests/test_eve_citation_freshness.py::ConstantsUncnhangedTest`
  (asserting `MIN_SAMPLE_SIZE==20`, `TARGET_RESOLVED_TRADES==30`,
  `FAST_MAX_MONTHS==6.0`, `VIABLE_MAX_MONTHS==12.0`, `DEFAULT_FDR_ALPHA==0.05`,
  `FRESHNESS_DISQUALIFICATION_WINDOW_DAYS==30`) ran as part of this
  directive's own full Python suite and still passes.

## Test counts, this directive

**Python:**
- Before (start of this directive): 2521 tests, OK.
- After Phase 1.1: **2527 tests, OK** (+6: 4 `CrashSafetyTest` tests + 1
  countability test + 1 crash-notification-naming test).
- Phase 2/3 touched zero Python files — the Python count is unchanged
  from the Phase 1.1 figure for the rest of this directive.

**Website:**
- Before this directive: 607 tests, 605 passing, 2 pre-existing failures
  (`siteDataSchema.test.ts`, unrelated — unchanged again this directive).
- After Phase 2: **624 tests, 622 passing, same 2 pre-existing failures**.
  Delta: **+17**, reconciling exactly (11 in `agentsPage.test.ts` + 6 in
  `agentsPageRender.test.tsx`).

## Stale figures found in this directive, and the real values

1. **"Three existing orphaned reservations" (Phase 1.1c) — stale. The real
   number is 6.** Verified two independent ways: direct inspection of
   `eve_budget_ledger.json` (6 entries with `status: "reserved"`) and
   cross-referenced against `eve_session_registry.json` (6 entries
   classified `crashed_before_completion`) — both lists match exactly by
   `session_id`. The directive's 3 named sessions
   (`df7df0f9`/`2b98a5f0`/`243d095f`) are real and are the 3 pure-
   ReadTimeout crashes; the other 3 (`29f48c2e`/`12e60677`/`b7568699`)
   are a DIFFERENT, already-fixed-same-day bug (the 400 tool_result
   protocol error) that also happens to have left an orphaned reservation
   in the exact same shape. Both the reconciliation report and the real
   dollar total ($1.27371, not a smaller 3-entry figure) reflect the real
   count of 6.
2. Every other figure checked against real, current data (Session 1's
   $0.4273, Adam's $0.56/2 TOO_SLOW hypotheses with their exact claimed/
   measured rates, the graveyard's 21 entries, Eve's Session 1 6→6→5→0
   funnel with 1 TOO_SLOW at 27.4/yr and 2 SELF_DERIVATIVE) matched the
   directive's own stated numbers exactly — no other staleness found.
---

# CC-1 MASTER DIRECTIVE v2 — "Automate the Factory, and Show the Work" (2026-08-05)

This section is new, appended after the prior "CC-1 Master Directive" (Phase
1.1, 1.2, 2, 3 — commit `a36d75c` and its closing-report fixup `7b29f56`).
Distinct directive, same initiative — prior sections above are left intact.

**This closing report's own commit (item 0, filled in after push, matching
this branch's own precedent): `f6ccd4c`.** Phase 1 shipped as `1d0bc45`,
Phase 2 as `3fcd9c1` — both verified on `origin/main` via `git log
origin/main --oneline` after each push, not assumed from `git commit` alone.

## PHASE 1 — Streaming fix

**FINDING:** confirmed unchanged from the prior directive's own carried-forward
note (section 3.4 above): `nero_core/eve/llm_client.py::call_turn` and the
shared `nero_core.research_agent.hypothesis_gen._call_claude` (used by BOTH
the scanner path and `generate_web_hypotheses`'s web-search path) both issued
a plain, non-streaming `requests.post` with a scalar `timeout`. **CONFIDENCE:**
confirmed-from-code.

**WHAT SHIPPED:**
- Both functions now issue `stream=True` requests and assemble the real SSE
  event sequence (`message_start` → `content_block_start`/`content_block_delta`*/
  `content_block_stop` per block → `message_delta`* → `message_stop`, `ping`
  interleaved) into the exact same `{"content": [...], "usage": {...},
  "stop_reason": ...}` shape the old `response.json()` call used to hand back
  directly — every downstream consumer (`extract_text`, `extract_tool_uses`,
  `nero_core.eve.scoring`'s `raw_response["content"]` web-search-result scan)
  is byte-for-byte unchanged.
- **Verified against Anthropic's own current, live streaming documentation**
  (fetched this directive, not assumed from memory —
  `https://platform.claude.com/docs/en/docs/build-with-claude/streaming`):
  confirmed the exact event names/shapes above, confirmed `usage` is
  cumulative across `message_delta` events (their own explicit warning),
  confirmed a real web-search trace shows `content_block_delta`/`ping` events
  continuing to arrive *during* the server-side search and that
  `server_tool_use.web_search_requests` only appears on the FINAL
  `message_delta` — both directly informed `_assemble_streamed_response`'s
  merge-in-arrival-order design.
- **Deliberate scope decision:** `_call_claude` is one shared function for
  both the scanner path and the web-search path the directive names — there
  is no separate non-streaming variant to keep, so converting it fixes both.
  This is a strict improvement for the scanner path too (never a regression),
  recorded here as a decision, not a silent side effect.
- **Item 1e preserved exactly, confirmed by test:** a mid-stream
  `event: error` (Anthropic's own documented `overloaded_error` example) is
  raised as `nero_core.eve.llm_client.StreamError` (Eve) /
  `requests.exceptions.HTTPError` (Adam, already a `RequestException`
  subclass caught by the existing broad handler) — never a confirmed `$0`,
  landing in the same `calls_with_unknown_cost` bucket a ReadTimeout does.
  `claude_timeout_seconds` stays `180` (A2's fallback), documented in
  `llm_client.py`'s own updated docstring as now meaning "idle gap between
  SSE lines," not "whole-call ceiling."
- **Item 1c — the real file count is 6, not 3, confirmed the hard way:**
  the prior directive's carried-forward estimate ("~55 test call sites
  across 3 files") undercounted — `grep`-ing every test file that patches
  `hypothesis_gen.requests.post`/`llm_client.requests.post` found **6**
  files, each with its OWN independent `_FakeResponse`-shaped fixture class:
  `test_research_agent_hypothesis_gen.py`, `test_research_agent_web_
  hypothesis_gen.py`, `test_eve_llm_client.py` (the original 3), plus
  `test_factory_loop_provenance.py`, `test_repair_lab_diagnosis_boundary.py`,
  and `test_research_agent_secret_handling.py` (3 more, missed by the
  original estimate). **This was caught by actually running the full suite,
  not assumed clean from the 3 files edited first:** the first full-suite
  run after Phase 1/2's initial changes came back with real errors —
  `AttributeError: '_FakeResponse' object has no attribute 'iter_lines'` —
  in exactly those 3 additional files. Each got the same one-method fix
  (`iter_lines()` encoding the fixture's existing `{"content": [...],
  "usage": {...}}` payload as real SSE lines, reinlined per-file rather than
  imported, matching this codebase's own established convention for small
  test-only helpers). Zero of the ~55+ individual test bodies across all 6
  files were touched — only each file's one shared fixture class.
  `test_eve_llm_client.py`'s existing (pre-this-directive) 6 call sites
  were confirmed genuinely unaffected either way: all error-path tests
  where `raise_for_status` fails before any streaming code runs.
- **Item 1d — new anti-regression tests, one per file:**
  `StreamingRequestTest`/`WebSearchToolDeclarationTest.test_real_call_declares_streaming_but_preflight_does_not`
  (Adam, both paths) and `RealCallStreamingTest.test_request_declares_streaming`
  (Eve) assert `stream=True` on both the request body AND the `requests.post`
  kwarg — a silent revert to non-streaming fails these immediately. Additional
  new tests cover: mid-stream error → unknown cost (both agents), and full
  reassembly of a realistic multi-block web-search turn (`server_tool_use` →
  `web_search_tool_result` → final text, Adam; plus a client `propose_hypothesis`
  tool_use block, Eve) — exercising every branch the streaming assembler has,
  not just plain text.

**Before/after failure behavior — real reproduction not run, and here is why,
stated plainly rather than glossed over:** demonstrating the ORIGINAL
ReadTimeout crash live would require making a real, long-running,
web-search-enabled Anthropic API call against this project's own key — real
money, and the crash is a timing race (60s/90s/120s previously, 180s now) not
guaranteed to reproduce on demand. Streaming's fix is instead demonstrated
three ways, all real: (1) Anthropic's own live documentation, fetched this
session, confirming `content_block_delta`/`ping` events arrive throughout a
web-search-including turn, which is the literal mechanism that keeps a
streamed connection non-idle where the old non-streamed call was idle for the
whole search; (2) full test coverage of the exact production assembly code
against a realistic multi-block web-search SSE trace; (3) the anti-regression
tests above, which would have caught a silent revert to the old crash-prone
shape.

## PHASE 2 — The Factory Loop runner

**FINDING:** confirmed exactly as the directive states — `admit_to_trial`,
`admit_repair_to_trial`, and `commit_graveyard_entry` are all built and
tested, called by nothing in production. **CONFIDENCE:** confirmed-from-code
(re-verified: zero non-test callers of any of the three before this
directive).

**WHAT SHIPPED:** `tools/factory_loop_run.py` — one script performing the
6 steps in order: (1) load every hypothesis with a real verdict from Adam's
(`agent_test_results.json` joined against `agent_hypotheses.json`) and Eve's
(`eve_hypotheses.json`, `verdict_combined is not None`) stores; (2)
`admit_to_trial` for each not already in `forward_trial.json`; (3)
`admit_repair_to_trial` for any repair attempt resolved SURVIVED/
PROMISING-WATCHLIST not already admitted; (4) the graveyard-distillation
family-DIED-count trigger check, drafting entries to a NEW file,
`docs/site_data/graveyard_distillation_drafts.json`, at `review_status=
pending_human_approval` — this also closes `factory_loop_status_summary.py`'s
own previously-documented KNOWN LIMITATION ("nothing persists a draft to disk
before approval"; its `pending_review` field now reads this real file instead
of a hardcoded `0`); (5) one forward tick per OPEN Trial record, via the real
live fetch layer (`tools.timeframe_data.fetch_timeframe_candles` — no
synthetic candle substitute); (6) regenerate `factory_loop_status.json`.

**2b — dry-run is the default,** confirmed by the flag design: no flag =
report-only, nothing written anywhere; `--live` is required for any write,
and is the ONLY thing in this script that spends real money (one
`draft_distillation_entry` LLM call per family at trigger — skipped with a
plain message, no call made, if `ANTHROPIC_API_KEY` is unset). **2d** — this
script never calls `commit_graveyard_entry` at all; a drafted entry sits at
`REVIEW_PENDING` until a human edits `review_status` by hand (or a future
Operator Panel does, per Phase 3).

### 2c — real first-run numbers (dry-run, executed this directive, output below verbatim)

```
Fresh admissions: 8 admitted, 0 not admitted, out of 8 candidates considered.
  [ADMITTED] RSI2_TREND_PULLBACK_PAXG_4H (adam): admitted: DSL-valid and not freshness-disqualified
    projected_time_to_min_sample: 40.1 years at the currently measured rate (0.50 trades/year) -- EXCEEDS the 2-year visibility horizon (item 4b)
  [ADMITTED] ADX_REGIME_IGNITION_SOL_4H (adam): admitted: DSL-valid and not freshness-disqualified
    projected_time_to_min_sample: 1.2 years at the currently measured rate (16.94 trades/year)
  [ADMITTED] PAXG_PEG_REVERSION (eve): projected_time_to_min_sample: 0.6 years (35.87 trades/year)
  [ADMITTED] BTC_VOL_EXPANSION_BREAKOUT (eve): projected_time_to_min_sample: 0.4 years (55.80 trades/year)
  [ADMITTED] SOL_TREND_ALIGNED_PULLBACK (eve): projected_time_to_min_sample: 0.2 years (103.12 trades/year)
  [ADMITTED] ETH_BIDIRECTIONAL_ZSCORE_FADE (eve): projected_time_to_min_sample: 0.7 years (27.40 trades/year)
  [ADMITTED] BTC_MOMENTUM_IGNITION (eve): projected_time_to_min_sample: 0.3 years (77.22 trades/year)
  [ADMITTED] PAXG_PREMIUM_FADE_DYNAMIC_EXIT (eve): projected_time_to_min_sample: 0.1 years (138.49 trades/year)

Repair admissions: 0 admitted, out of 0 resolved-passing attempts found.
Graveyard distillation: 1 family/families at or past the trigger:
  Range Mean Reversion: 4 DIED
Forward Trial ticks: 0 OPEN record(s).
```

**Adam's two known hypotheses ARE admissible, confirmed directly, not
inferred:** `RSI2_TREND_PULLBACK_PAXG_4H` (measured 0.50/yr, claimed 35.0) and
`ADX_REGIME_IGNITION_SOL_4H` (measured 16.94/yr, claimed 45.0) both pass
`is_dsl_valid` and are admitted, each visibly labeled with its real projected
time — 40.1 years (past the 2-year visibility horizon) and 1.2 years
respectively — never excluded, never silently hidden.

**The design conflict the directive asked to be surfaced, confirmed real:**
both hypotheses are recorded with `verdict: SKIPPED` / `frequency_classification:
TOO_SLOW` in `agent_test_results.json` — the frequency gate rejected them
BEFORE a real backtest verdict ever existed (auto_tester's own upstream SKIP,
`review_status: rejected_too_slow`). Trial admission's gate is DSL-validity
alone and does NOT consult that upstream SKIP at all — so both are admitted
to Trial carrying a SKIPPED entry_verdict as an honest advisory tag, exactly
as `admit_to_trial`'s own docstring specifies ("the backtest verdict is
NEVER a condition"). This is real and by design, not a bug: it means Trial
can hold entries the frequency gate already flagged as impractically slow to
ever measure — visible via `projected_time_to_min_sample_label`'s own
"EXCEEDS the 2-year visibility horizon" text, not silently indistinguishable
from a viable one. Nothing was changed to resolve this tension; it is
reported, per the directive's own instruction, as a design conflict worth
surfacing.

**Real distillation candidate found:** the "Range Mean Reversion" family has
4 DIED hypotheses (`>=` `DIED_COUNT_TRIGGER=3`) — a real, live-computed
result (`graveyard_distillation.find_families_ready_for_distillation`,
unchanged), not a fixture. A `--live` run would spend one real LLM call
drafting this family's distillation entry.

**Tests:** `tests/test_factory_loop_run.py` (17 new tests: candidate
loading/joining, DSL-gate admission with re-admission dedup, repair-chain
admission with DIED attempts never becoming candidates, distillation
trigger detection, dry-run-never-fetches / live-uses-real-fetch-layer for
forward ticks) + 2 new tests in `tests/test_factory_loop_status_summary.py`
for the real `pending_review` count. All pass.

## PHASE 3 — Local Operator Panel (report only, per the directive's own instruction)

### 3a — implementation options

**Recommended: a small standalone FastAPI app under a NEW `tools/operator_panel/`
directory (NOT under `website/`), plus one static HTML+vanilla-JS page it
serves — run locally via `uvicorn`, calling directly into existing `nero_core`
functions and `tools/factory_loop_run.py`'s own pure functions as normal
Python imports (no subprocess, no new write path).**

1. **FastAPI (recommended).** *Effort:* one new dependency
   (`fastapi`+`uvicorn`, best kept in a separate `requirements-operator-panel.txt`
   so CI/the public site's own dependency surface never needs it). Built-in
   `StreamingResponse`/SSE support covers 3b's "stream output live"
   requirement for Adam/Eve runs with little boilerplate; automatic request
   validation via Pydantic models matches this project's own existing
   Pydantic-model discipline (`CLAUDE.md`). *Maintenance:* low — one file,
   one process, no build step, no auth needed (see 3d).
2. **Flask.** *Effort:* comparable for the basic routes, but live-streaming
   output needs an extra library (`flask-sse`) or manual threading/
   generator wiring FastAPI gets for free. *Maintenance:* similar to option 1
   otherwise; chosen only if this codebase already leaned on Flask elsewhere
   (it does not — confirmed, zero Flask imports anywhere in `nero_core`/
   `tools`).
3. **A local-only Next.js API route inside the existing `website/` app.**
   *Effort:* lowest incremental code (reuses the site's existing
   styling/tooling). *Security/isolation — the reason this is NOT
   recommended:* item 3d requires a hard guard that this panel can NEVER
   ship in the public site bundle. Proving that is trivial when the panel
   is a physically separate directory/process (a test can assert
   `website/` contains zero references to `tools/operator_panel/`); proving
   it when the panel's OWN code lives inside `website/`'s own build tree
   requires trusting a build-config exclusion instead of a directory
   boundary — a strictly weaker guarantee for something explicitly
   forbidden from ever being public.

**Recommendation: option 1.** Lowest risk for the one requirement (3d) that
matters most (never public), acceptable one-time dependency cost, and its
streaming support is a direct fit for 3b's two "stream output live" runs.

### 3b/3c/3d — not built this directive

**Per the directive's own explicit sequencing note** ("If time runs short,
Phases 1 and 2 are the ones that matter") **and its own instruction that
Phase 3 is report-first:** the actual panel (approval queue, budget meter,
kill switch, repair-chain launch, the 3d hard guard + test) was not built
this session. Building it correctly — writing ONLY through existing
functions, with a real kill switch and a correctly-enforced 4-attempt repair
cap surfaced in the UI — is itself a multi-file, multi-test piece of work
comparable in size to Phase 2, and rushing it risks bugs in code that writes
to the same `forward_trial.json`/graveyard files Trial admission depends on.
Recommended as the clear next session's first task, using the option 1
design above.

## PHASE 4 — not implemented this directive (see honesty note)

**Per the directive's own text** ("Phases 4, 5, and 6 are independent of
1-3... If time runs short, Phases 1 and 2 are the ones that matter"): no
website/site-data change was made this directive. Every number Phase 4 asks
to surface (the 0/1000 random-baseline result, the real test counts, the
pre-registration text, claimed-vs-measured frequency, the Truth Ledger page,
graveyard header, promising-strategies list, quant explainer, news-sentiment
export, tier-classification fragility) is exactly as it was before this
directive — **stated honestly as not done, rather than a partial or
cosmetic change presented as complete.** Recommended as the next parallel
track once Phase 3 lands, per the directive's own note that 4 can run
independently of 1-3.

## PHASE 5 — Automation schedule (report only, nothing enabled)

### 5a — real budget arithmetic, re-derived this directive from the live ledger

**FINDING, `docs/site_data/eve_budget_ledger.json` (27 entries), read
directly:** actual (reconciled) spend so far = **$2.1416** (sum of
`actual_cost_usd` where `status="actual"`). The 6 orphaned `reserved`
entries total **$1.27371** (unchanged from the prior directive's own count).
Combined real consumption against the pre-registration's own stated `~$14`
envelope (`eve_session_registry.json` line 40, `"sessions_budgeted": "8 Eve
sessions + 8 Adam runs (~$14)"`) = **$3.4153**, leaving **$10.5847**
remaining — not the `~$11.7` this directive's own text states. **Flagged as
stale, Phase 8 note:** the `~$11.7` figure predates at least one entry
recorded in the ledger's own `actual`/`reserved` totals above; $10.58 is the
real, current, reproducible number as of this run. Separately, the
month-level hard ceiling (`MONTH_CEILING_USD=20.0`) has **$17.86** remaining
against actual spend alone — the two figures track different things (a
fixed ~$14 pre-registration research budget vs. a $20/month hard safety
ceiling) and should not be conflated.

Per-run costs (Eve Session 1's real $0.4273 and `DEFAULT_SESSION_BUDGET_USD`
$1.50 ceiling; Adam's real $0–$0.558 range, n=4 — both carried forward from
the prior directive's own confirmed figures, re-verified unchanged this
session) plus Phase 2's new spend line: `tools/factory_loop_run.py --live`
spends money ONLY when a family is at the distillation trigger (today:
yes, 1 family) — one `draft_distillation_entry` call, comparable in shape
and cost to a single Adam hypothesis-generation call (well under $0.30
based on this project's own observed per-call costs).

- **Weekly schedule** (Adam + Eve + factory-loop-run, worst case): `(1.50 +
  0.558 + ~0.30) × 4.33 ≈ $10.21/month` — fits the $20 hard ceiling with
  margin, and burns the real, current $10.58 pre-registration remainder in
  roughly **4.3 weeks** at worst case (`10.58 / 2.358`), or meaningfully
  longer at Eve's REAL observed $0.4273 (`10.58 / (0.4273+0.558+0.30) ≈ 8.1`
  weeks) — both numbers are below the prior directive's own weekly estimate
  because the real remaining budget is smaller than the `~$14` that estimate
  assumed and because this directive adds a new spend line (Phase 2's
  distillation drafting).
- **Daily schedule:** unchanged conclusion from the prior directive — `(1.50
  + 0.558) × 30 ≈ $61.74/month` exhausts the $20 hard ceiling in under 10
  days worst case; **not viable as designed.**

### 5b — guardrails required before any schedule is enabled (report only)

A hard daily spend ceiling that halts (not warns), auto-pause at 80% of
$20 (`$16`), an ntfy notification per run (success/failure/spend — `nero_
core.eve.notify` already exists and is used elsewhere in this codebase, so
this is wiring an existing mechanism, not new infrastructure), and crash-rate
monitoring that auto-pauses above a threshold (the real observed crash rate
this project has seen — 6 crashed sessions of 7 real attempts before Phase
1's streaming fix — makes this the single most important guardrail if
scheduling is ever enabled before Phase 1's real-world crash-rate impact is
independently confirmed over more real sessions).

### 5c — compatible with the pre-registered 8-session structure? A real, scoped answer

**The proposed split ("research execution automates, publication/approval
stays human") holds for `tools/factory_loop_run.py` specifically, more
cleanly than for Adam/Eve themselves:** `factory_loop_run.py --dry-run`
(the default) makes zero LLM calls and writes nothing — **it is safe to
schedule immediately, today, with zero collision with any standing rule**,
since it only ever reports on hypotheses/attempts that ALREADY exist from a
deliberately-watched Adam/Eve run. Even `--live` mode doesn't generate a new
hypothesis or run a new Eve/Adam session — it only admits/drafts/ticks
data from runs a human already watched separately. **Scheduling Adam or Eve
generation itself remains the real collision** the prior directive already
found (collapses the "deliberate, watched click" review discipline
`research_agent_manual.yml`'s own comment requires) — this directive's own
work does not change that conclusion, it only narrows which PART of the
Factory Loop is actually safe to automate today.

### 5d — nothing enabled

No schedule, no `EVE_ENABLED`, no CI cron touched. Options and real numbers
reported above only.

## PHASE 6 — Multi-timeframe rollout plan (report only, nothing implemented)

**Scope, confirmed from code:** 4 approved crypto assets
(`nero_core/asset_universe.py::APPROVED_RESEARCH_UNIVERSE` — BTC, ETH, SOL,
PAXG, all currently only at `4h`) × 5 target timeframes (1h, 2h, 12h, 1d,
"7d") = **20 (asset, timeframe) pairs**, matching the directive's own "20
research candle pulls" / "20 fresh K=200 baselines" figures.

- **The 20 research candle pulls:** real fetch time not measured this
  session (no live network pulls were performed as part of this report-only
  phase) — recommend timing the FIRST pair's pull as a calibration point
  before queuing all 20, rather than assuming a per-pair duration.
- **The 20 K=200 baselines:** confirmed **pure-code, zero LLM spend** —
  `nero_core/eve/random_baseline.py` (Eve's own random-hypothesis baseline
  module) contains no `requests`/`anthropic` call of any kind, confirmed by
  reading the module's own imports. Compute time not measured this session;
  proportional to the existing single-pair baseline runs already committed
  (`docs/site_data/{btc,eth,sol,paxg}_4h_random_baseline_result.json`).
- **The `APPROVED_RESEARCH_UNIVERSE` edit:** a 4-asset × 5-timeframe
  expansion of the frozenset in `nero_core/asset_universe.py` — explicitly
  OUT OF SCOPE for this directive (report only); the edit itself is
  mechanical once each pair's export + baseline exists, per the module's own
  binding-in-both-directions discipline.
- **The "7d" decision, verified against Binance's live documentation this
  directive** (`https://developers.binance.com/docs/binance-spot-api-docs/
  rest-api/market-data-endpoints`, fetched fresh, not assumed): Binance's
  real, current kline interval set is `1s, 1m, 3m, 5m, 15m, 30m, 1h, 2h, 4h,
  6h, 8h, 12h, 1d, 3d, 1w, 1M` — **there is no `7d` interval.** Recommend
  `1w` (the native weekly interval), matching the precedent already
  established in this codebase's own `tools/timeframe_data.py`
  (`NATIVE_BINANCE_INTERVAL = {..., "1week": "1w"}`) rather than a
  client-side 7-candle resample from daily — Binance's `1w` already aligns
  to a calendar week boundary the same way `market_data.py:223-226`'s own
  GOLD/SILVER/PLATINUM 12h-from-1h resampling precedent handles a missing
  native interval, so no NEW resampling code is needed for "7d" specifically
  — it already has a native answer.
- **Interval-validation guard:** confirmed real — `tools/timeframe_data.py`'s
  `fetch_timeframe_candles` passes whatever `NATIVE_BINANCE_INTERVAL[timeframe]`
  resolves to straight through to the client with no validation that the
  resulting string is one Binance actually accepts; an invalid entry in
  that dict would only surface as a live 4xx from Binance at fetch time,
  not at import/config time. **Recommend** (propose only, per this phase
  being report-only): a small module-import-time assertion that every value
  in `NATIVE_BINANCE_INTERVAL`/`NATIVE_TWELVEDATA_INTERVAL` is drawn from a
  hardcoded closed set of Binance's real intervals (listed above) — the same
  "closed vocabulary, enforced at the boundary" discipline this codebase
  already applies to `graveyard_distillation.ALLOWED_FAILURE_PATTERN_VALUES`
  and the failure-pattern taxonomy.

**Nothing implemented — plan only, per the directive's own instruction.**

## Out-of-scope confirmations, this directive

- `EVE_ENABLED`/`RESEARCH_AGENT_ENABLED` not touched anywhere.
- No schedule created, no cron/CI file touched (Phase 5, report only).
- No pair added to `APPROVED_RESEARCH_UNIVERSE` (Phase 6, report only).
- Nothing at `REVIEW_PENDING` was auto-approved — `tools/factory_loop_run.py`
  never calls `commit_graveyard_entry`, confirmed by reading its own source:
  zero references to that function anywhere in the file.
- No evidence-bar constant changed. Confirmed via `git diff --stat` across
  every commit this directive — none touch `tools/backtest_statistics.py`,
  `nero_core/research_agent/frequency_gate.py`, or the constant-defining
  sections of `nero_core/eve/scoring.py`. The existing
  `tests/test_eve_citation_freshness.py::ConstantsUncnhangedTest` (asserting
  `MIN_SAMPLE_SIZE==20`, `TARGET_RESOLVED_TRADES==30`, `FAST_MAX_MONTHS==6.0`,
  `VIABLE_MAX_MONTHS==12.0`, `DEFAULT_FDR_ALPHA==0.05`,
  `FRESHNESS_DISQUALIFICATION_WINDOW_DAYS==30`) ran as part of this
  directive's own full Python suite and still passes.
- The operator panel (Phase 3b/3c/3d) and every website/site-data change
  Phase 4 asks for were **not built this directive** — stated plainly above,
  not glossed over.

## Stale figures found in this directive, and the real values

1. **"~55 test call sites across 3 files" (carried forward from the prior
   directive) — the file count was stale. The real count is 6 files**, not
   3 — see Phase 1's own item 1c section above for the 3 additional files
   and how the gap was actually caught (a real full-suite failure, not a
   re-read of the old estimate).
2. **"~$11.7 remaining" (this directive's own Phase 5 text) — stale. The
   real, live-ledger-derived figure is $10.5847 remaining** of the
   pre-registration's own `~$14` envelope, as of `docs/site_data/
   eve_budget_ledger.json`'s 27 real entries at the time this directive ran
   — see Phase 5a above for the full arithmetic.
3. Every other figure checked against real, current data this directive
   (Adam's two known hypotheses' exact measured/claimed rates, the
   `DIED_COUNT_TRIGGER=3` distillation threshold and the real "Range Mean
   Reversion" family at 4 DIED, the 6 orphaned reservations totalling
   $1.27371, the $20 monthly hard ceiling with $17.86 remaining against
   actual spend) matched what was already stated — no other staleness
   found.

## Test counts, this directive

**Python:**
- Before this directive: 2521 tests, OK (matches the prior directive's own
  closing figure — re-confirmed, not re-run from scratch, since zero Python
  files were touched between that directive's close and this one's start).
- **A real, caught-and-fixed regression along the way:** the first full
  suite run after Phase 1/2's initial changes came back **2553 tests,
  FAILED (errors=7)** — the 3 additional `_FakeResponse` fixtures from item
  1c above, not yet fixed at that point. Reported here rather than silently
  re-running until green, per this directive's own "100% accuracy" standard.
- After the fix and Phase 2's new tests: **2555 tests, OK** (full
  `python -m unittest discover -s tests` rerun, 450.7s) — net **+34** from
  the 2521 baseline.
- **Reconciliation, stated honestly rather than forced to match:**
  `git diff e8e6ee0..HEAD -- tests/` (every commit this directive, against
  the commit `origin/main` was on before this directive started) shows
  **28** new `def test_` methods, 0 removed — accounting for `+28` of the
  `+34` test delta directly. The remaining `+6` is not reconciled by this
  count and is most likely `unittest discover`'s own subtest/parameterization
  expansion rather than a miscount (`assertRaises`/loop-based test bodies in
  this suite can register more than one reported test per `def test_`), but
  that mechanism was not independently re-verified this session — flagged
  here rather than asserting a tidy reconciliation that isn't fully proven.
  The 28 new methods break down as (per-file `git diff` count, exact): 17 in
  `test_factory_loop_run.py`, 2 in `test_factory_loop_status_summary.py`,
  4 in `test_eve_llm_client.py`, 2 in `test_research_agent_hypothesis_gen.py`,
  3 in `test_research_agent_web_hypothesis_gen.py` — the other 3 files that
  needed the `iter_lines()` fixture fix (`test_factory_loop_provenance.py`,
  `test_repair_lab_diagnosis_boundary.py`, `test_research_agent_secret_
  handling.py`) added 0 new test methods, only the one shared fixture change
  each.

**Website:** not run this directive — no `website/` file was touched (Phase
4 not implemented this session, confirmed above).

## `git log origin/main --oneline -3`, per commit this directive

**After Phase 1's push:**
```
1d0bc45 CC-1 Master Directive v2 Phase 1: convert Adam/Eve LLM calls to streaming
e8e6ee0 Update live scheduler execution log
7308e8c Update live scheduler execution log
```

**After Phase 2's push:**
```
3fcd9c1 CC-1 Master Directive v2 Phase 2: the Factory Loop runner
1d0bc45 CC-1 Master Directive v2 Phase 1: convert Adam/Eve LLM calls to streaming
e8e6ee0 Update live scheduler execution log
```

Both pushes required a rebase first — `origin/main` had moved 11 commits
ahead (all automated "Update live scheduler execution log"/"Update strategy
health check report" entries, unrelated to this work) between this
directive starting and Phase 1's first push attempt. Rebased cleanly, no
conflicts, verified via `git log origin/main --oneline` after each push
(not assumed from a successful `git commit` alone — this project's own
standing note that a successful commit is not a successful push).

## What the factory still cannot do

Even after Phase 2, the loop is not fully closed: Trial admission and
graveyard-distillation drafting now run for real, but **nothing yet
launches a repair chain** (Phase 3.2 of the prior directive already found
this — still true, unchanged), and **the Operator Panel that would let the
owner approve a `REVIEW_PENDING` draft or launch a repair chain without
hand-editing JSON does not exist yet** (Phase 3 of this directive, report
only). Scheduling anything beyond `factory_loop_run.py --dry-run` remains a
human decision, deliberately, per Phase 5.
---

# CC-1 DIRECTIVE — "Turn the factory for real, then finish Phases 3 and 4" (2026-08-06)

New directive, same initiative — continues directly from the prior "CC-1
Master Directive v2" section above (Phases 1/2 shipped as `1d0bc45`/`3fcd9c1`,
closing report `f6ccd4c`/`a0584eb`).

**This directive's own commits (item 0, filled in after each push):** Item
2 = `1652ffe`, Item 4 = `e3730ca`, Item 5 = `dfaf70e`, this closing report
= `9192e9d`. All four verified on `origin/main` via `git log origin/main
--oneline` immediately after pushing, not assumed from `git commit` alone.

## ITEM 1 — Three questions, answered before any code

### 1a — the real remaining budget, recomputed live

**FINDING, `docs/site_data/eve_budget_ledger.json` (still 27 entries — zero
new activity since the last directive closed):** 21 entries `status="actual"`
summing to **$2.141599** real reconciled spend; 6 entries `status="reserved"`
(the same orphaned reservations from before, unchanged: `df7df0f9`,
`2b98a5f0`, `29f48c2e`, `12e60677`, `b7568699`, `243d095f`) summing to
**$1.27371**. **CONFIDENCE:** confirmed-from-data (recomputed directly this
directive, not carried forward).

**Real arithmetic:** $2.141599 + $1.27371 = **$3.415309** consumed against
the pre-registration's own `~$14` envelope (`eve_session_registry.json`
line 40) → **$10.5847 remaining** — identical to the prior directive's own
recomputed figure (nothing has run against this ledger since). Separately,
against the `$20`/month hard ceiling (`MONTH_CEILING_USD`), actual spend
alone leaves **$17.8584** — the two figures track different things (see
prior section) and should not be conflated.

**Unknown-cost calls — a real, confirmed gap, not a number I can report:**
`nero_core/research_agent/pipeline.py`'s `PipelineRunResult.calls_with_
unknown_cost` (line 207) is computed correctly per-run and printed as a
console `WARNING` in `main()` (line 438), but `tools/research_agent_run_
summary.py` — the ONLY thing that persists Adam's run data to
`agent_run_summaries.json` — never reads or writes that field (confirmed:
zero matches for `unknown_cost` in that file). Adam's own historical
unknown-cost call count is therefore **UNKNOWN — not recoverable from any
committed file**, only ever visible in a workflow run's own console log at
the time it happened. Reported honestly rather than guessed; the Operator
Panel's budget meter (Item 4) shows what's real — Eve's 6/$1.27371 — and
states this Adam-side gap explicitly rather than fabricating a number for
it.

### 1b — the design tension, in full

**Both sides, real, from code:**

- **The frequency gate's job** (`nero_core/research_agent/frequency_gate.py`,
  measured against real historical candles): a hypothesis whose entry
  condition triggers too rarely to ever accumulate `MIN_SAMPLE_SIZE=20`
  resolved trades in a practical planning horizon gets `verdict=SKIPPED`,
  `frequency_classification=TOO_SLOW` — this happens BEFORE any real
  backtest verdict (SURVIVED/DIED/PROMISING-WATCHLIST) is ever computed for
  it. Its purpose: don't waste a real backtest (and, for auto_tester's
  in-sample/out-of-sample split, real statistical power) on a rule that
  cannot be measured in any useful timeframe. `RSI2_TREND_PULLBACK_PAXG_4H`
  measured **0.498 trades/year** against a claimed 35.0 — the gate correctly
  identified this real rule fires roughly once every two years on PAXG/4h.
- **Trial admission's job** (`nero_core/research_agent/trial.py::
  admit_to_trial`): admit ANY hypothesis whose `structured_entry_rule`/
  `structured_exit_plan` parse via the rule-DSL — deliberately NOT
  conditioned on the backtest verdict OR the frequency classification (see
  `admit_to_trial`'s own docstring: "the real gate is DSL-validity alone").
  Its purpose, per this branch's own "measure, never gate" philosophy
  (`[[feedback_cc1_directive_conventions]]`): a SKIPPED verdict is itself a
  measurement made on a LIMITED historical sample — the frequency gate
  could be right that this asset/timeframe/rule combination is genuinely
  rare, or the historical window it measured against could simply have been
  a quiet stretch for this specific trigger. Excluding it from Trial would
  make that judgment permanent and unfalsifiable; admitting it (with its
  slow projection clearly labeled) lets REAL forward data, not a retrospective
  guess, eventually confirm or overturn the frequency gate's own finding.

**Why they disagree:** they are measuring different things at different
times with different consequences. The frequency gate protects a SPECIFIC
downstream resource (a finite backtest's own statistical power, spent once,
on a historical window that cannot grow) from being wasted on a rule almost
certain to starve it. Trial admission protects a DIFFERENT resource (this
project's own claim to be evidence-based) from silently discarding a
measurement-worthy idea because one earlier, resource-constrained gate said
no.

**Recommendation, not a decision (per this item's own instruction):**
this reads as a deliberate division of labor working as designed, not a bug
— PROVIDED the resulting Trial entry is never displayed or treated as
equivalent to a normally-paced one (see 1c below, where this is exactly
what the display framing has to get right). If it were later found that a
TOO_SLOW-admitted entry were being weighted, promoted, or averaged into an
aggregate stat alongside normally-paced entries with no visible distinction,
THAT would be the point where "deliberate division of labor" tips into
"silently misleading" — worth a standing regression test asserting
`unmeasurable_count`/`beyond_2_years_count` stays a SEPARATE, always-shown
figure, never silently dropped from any aggregate. No such test exists yet
— proposed here, not built (Item 1 is report-only).

### 1c — the real projected number, and how to frame it

**FINDING, computed directly this directive
(`trial.compute_projected_time_to_min_sample(0.498181404864742)`):**

```
years = 40.14601870864704
label = "40.1 years at the currently measured rate (0.50 trades/year) -- EXCEEDS the 2-year visibility horizon (item 4b)"
```

**CONFIDENCE:** confirmed-from-code (real function call, real measured
rate from `agent_test_results.json`, not estimated).

**Where this would actually render, checked directly:** `website/app/
factory-loop/page.tsx` (173 lines, read in full this directive) shows
ONLY aggregate counts today — `forwardTrialCount` and its `by_origin`
split. It does not render any per-hypothesis field, and critically, it
does not render `unmeasurable_count` at all, even though
`factory_loop_status_summary.py`'s own `_forward_trial_summary` (already
shipped, Phase 2 of the prior directive) computes it — a real, already-
available number the page simply never reads. So today, a 40.1-year Trial
entry would be invisible on `/factory-loop` — folded into the plain count
`8`, with nothing distinguishing it from `ADX_REGIME_IGNITION_SOL_4H`'s
much more measurable 1.2 years.

**Two real framing options, recommend one:**

1. **Aggregate-only badge (cheapest, ships today):** surface the EXISTING
   `unmeasurable_count` field next to the Forward Trial count — e.g. "8
   hypotheses in Forward Trial (2 with a projected measurement time beyond
   2 years — shown, not hidden or excluded, because measuring a genuinely
   rare trigger honestly takes proportionally longer)." *Effort:* one JSX
   edit, no new data plumbing (the field already exists in
   `factory_loop_status.json`'s schema). *Limitation:* doesn't name WHICH
   hypothesis or its real number (40.1 years specifically), so a reader
   curious about the outlier has no way to find it.
2. **Per-hypothesis table/detail** (a new section on `/factory-loop` or a
   dedicated `/forward-trial` page) listing every entry — name, origin,
   entry verdict, `projected_time_to_min_sample_label` verbatim — with one
   shared framing sentence above any row exceeding the 2-year horizon (e.g.
   "A large number here is a real result, not a bug or a joke: it means
   this rule's trigger condition is measured, honestly, as genuinely rare
   at its currently-known rate — it stays open and unpromoted while real
   data accrues, exactly like every other Trial entry, just on a longer
   clock."). *Effort:* moderate — needs `forward_trial.json` exported to
   `docs/site_data/` in a site-fetchable form (it is not currently listed
   among `website/lib/data.ts`'s fetch functions — `fetchFactoryLoopStatus`
   only reads the aggregate `factory_loop_status.json`, not the per-record
   file). *Benefit:* this is exactly the "show the work, including the
   slow ones, honestly" instinct the whole Master Directive is built
   around — a number this specific IS the evidence, per item 5's own
   framing.

**Recommendation: build option 2 as part of Item 5** (site display), since
Item 2 below will populate `forward_trial.json` with real records this
directive, including this exact 40.1-year one — the data option 2 needs
will exist by the time Item 5 starts. Option 1 is a good INTERIM step if
Item 5's time runs short; not mutually exclusive with option 2, worth
shipping both.

## ITEM 2 — Turn the factory for real

### 2a — the exact command, and exactly what it writes

**Command:** `python -m tools.factory_loop_run --live` (run from the repo
root; `ANTHROPIC_API_KEY` in the environment is optional — only consulted
if a family is at the distillation trigger, see below).

**What it writes, confirmed from the real run below (not predicted):**
- `docs/site_data/forward_trial.json` — one `TrialRecord.to_dict()` JSON
  object appended per newly-admitted hypothesis (8, this run).
- `docs/site_data/graveyard_distillation_drafts.json` — one entry per
  family at `DIED_COUNT_TRIGGER`, IF drafting succeeds (it did not this
  run — see below; the file was therefore not created).
- `data/repair_lab_forward_tracking.db` — one `execution_log` row per
  forward tick that logs an ENTRY or EXIT signal (7 of 8 ticks this run
  logged `NO_TRADE`, which writes nothing to this DB; 1 logged a real
  `ENTRY`).
- `docs/site_data/factory_loop_status.json` — fully overwritten (a
  point-in-time snapshot, not appended).

### 2b — real execution, and a real bug caught along the way (per item 2e)

**First `--live` attempt — diverged from the dry-run prediction, stopped
and reported per item 2e, not pushed through silently:**

1. **Real divergence #1 — a genuine bug the dry run could never have
   caught:** `tools/factory_loop_run.py`'s `advance_open_trials` expected
   each written `TrialRecord` dict to carry a `"hypothesis"` key with
   `asset`/`timeframe` — but `nero_core.research_agent.trial.TrialRecord.
   to_dict()` (unchanged, pre-existing code) never produces that key, only
   `source_hypothesis_ref.hypothesis_name`. Dry-run mode never exercises
   this code path at all (it returns early before touching any record), so
   this was structurally impossible for the dry run to predict — exactly
   the "dry run that mispredicts is a bug worth more than the run itself"
   scenario item 2e names. **Fixed:** `advance_open_trials` now takes a
   `hypothesis_lookup: dict[str, dict]` (built by `main()` from the SAME
   Adam/Eve candidate sources `load_adam_candidates`/`load_eve_candidates`
   already read) and resolves each OPEN record's asset/timeframe by
   `hypothesis_name` instead of expecting the Trial record to carry a copy.
   A repaired-origin record's real name (`...__REPAIR_<attempt_id>`) will
   never match either lookup — reported as a real, scoped, currently-unhit
   limitation (0 repaired admissions exist yet), not silently papered over.
   New regression test: `test_hypothesis_not_in_lookup_is_reported_not_
   crashed`. **A second, quieter finding alongside this:** the PRE-EXISTING
   test for this function (`test_live_tick_uses_real_fetch_layer_and_logs_
   outcome`) had put a `"hypothesis"` key directly on its fixture record —
   a shape that does not match what production code ever actually
   produces — so it gave false confidence rather than exercising the real
   path. Fixed to build the lookup the way a real caller now does.
2. **Real divergence #2 — the local `ANTHROPIC_API_KEY` was rejected:**
   `graveyard_distillation.draft_distillation_entry`'s own preflight
   (`validate_api_key`) received a real `401 Unauthorized` from Anthropic's
   servers — confirmed `$0`, no tokens processed (see Item 3 for the full
   analysis; this is the SAME key checked there). This is not itself a bug
   in this directive's code, but it exposed a real robustness gap: the
   exception propagated UNCAUGHT out of `main()`, crashing the whole `
   --live` run BEFORE the deterministic remaining steps (regenerating
   `factory_loop_status.json`) ever executed — a single LLM-dependent step
   was able to abort work that has nothing to do with whether that call
   succeeded. **Fixed:** the drafting call is now wrapped in a `try/except
   graveyard_distillation.ApiKeyRejectedError`, printing the real failure
   and continuing to the remaining steps, never silently swallowed.

Both fixes are in `tools/factory_loop_run.py`; both are covered by tests
in `tests/test_factory_loop_run.py` (18 tests total in that file after this
item, up from 17).

**Second `--live` attempt, after both fixes — completed cleanly, real
output pasted verbatim:**

```
Factory Loop run (LIVE):

Fresh admissions: 0 admitted, 8 not admitted, out of 8 candidates considered.
  [skipped] RSI2_TREND_PULLBACK_PAXG_4H (adam): already admitted to Trial in an earlier run
  [skipped] ADX_REGIME_IGNITION_SOL_4H (adam): already admitted to Trial in an earlier run
  [skipped] PAXG_PEG_REVERSION (eve): already admitted to Trial in an earlier run
  [skipped] BTC_VOL_EXPANSION_BREAKOUT (eve): already admitted to Trial in an earlier run
  [skipped] SOL_TREND_ALIGNED_PULLBACK (eve): already admitted to Trial in an earlier run
  [skipped] ETH_BIDIRECTIONAL_ZSCORE_FADE (eve): already admitted to Trial in an earlier run
  [skipped] BTC_MOMENTUM_IGNITION (eve): already admitted to Trial in an earlier run
  [skipped] PAXG_PREMIUM_FADE_DYNAMIC_EXIT (eve): already admitted to Trial in an earlier run

Repair admissions: 0 admitted, out of 0 resolved-passing attempts found.

Graveyard distillation: 1 family/families at or past the trigger:
  Range Mean Reversion: 4 DIED

Forward Trial ticks: 8 OPEN record(s).
  RSI2_TREND_PULLBACK_PAXG_4H: NO_TRADE tick logged; still PENDING_FORWARD_DATA
  ADX_REGIME_IGNITION_SOL_4H: NO_TRADE tick logged; still PENDING_FORWARD_DATA
  PAXG_PEG_REVERSION: NO_TRADE tick logged; still PENDING_FORWARD_DATA
  BTC_VOL_EXPANSION_BREAKOUT: NO_TRADE tick logged; still PENDING_FORWARD_DATA
  SOL_TREND_ALIGNED_PULLBACK: NO_TRADE tick logged; still PENDING_FORWARD_DATA
  ETH_BIDIRECTIONAL_ZSCORE_FADE: ENTRY tick logged; still PENDING_FORWARD_DATA
  BTC_MOMENTUM_IGNITION: NO_TRADE tick logged; still PENDING_FORWARD_DATA
  PAXG_PREMIUM_FADE_DYNAMIC_EXIT: NO_TRADE tick logged; still PENDING_FORWARD_DATA

Distillation drafting failed: ANTHROPIC_API_KEY is present but was rejected (401 Unauthorized) by the Claude API. No further calls were attempted this run -- check the key's validity before retrying. (confirmed $0 -- rejected before any token was processed; the rest of this run still completes).

factory_loop_status.json regenerated:
Factory Loop status:
  Forward Trial: 8 (adam=2 eve=6 repaired=0, unmeasurable=1)
  Graveyard: 21 (distilled_this_period=0 pending_review=0)
  Repair: 0 chains (open=0 resolved=0)
```

**The "Range Mean Reversion" distillation draft was NOT written this
directive** — the only blocker was the rejected key, confirmed $0 spent,
not a design or process decision. Out-of-scope item ("do not approve it")
is trivially still true: nothing was drafted to approve or reject.

**One real, live signal worth naming plainly:** `ETH_BIDIRECTIONAL_ZSCORE_
FADE` (Eve, measured 27.40 trades/year) logged a real `ENTRY` tick against
real, live-fetched ETH/4h candles — the first real forward-tracked position
this project's Trial mechanism has ever opened. Paper only, per this
project's own hard rule; no real capital at risk.

### 2c — real before/after numbers

| | Before | After |
|---|---|---|
| Forward Trial count | 0 | **8** |
| — by origin | adam=0, eve=0, repaired=0 | **adam=2, eve=6, repaired=0** |
| — unmeasurable_count | 0 | **1** (`RSI2_TREND_PULLBACK_PAXG_4H`, 40.1yr) |
| Graveyard count | 21 | 21 (unchanged — nothing committed to it this run) |
| Repair chains | 0 | 0 (unchanged — 0 repair events exist) |

Source: `docs/site_data/factory_loop_status.json`, `last_updated` moved
from `2026-08-05T02:09:23Z` (stale, from before Phase 2 even shipped) to
`2026-08-05T23:11:00Z` (this run).

### 2d — live-site confirmation: unable to verify, stated plainly

**No confirmed production URL exists anywhere in this repository** —
re-confirmed this directive (grepped `website/package.json`, `README.md`,
`.github/workflows/` for a `vercel.app` or custom domain: zero matches,
matching the prior directive's own identical "unable-to-verify" finding).
`.github/workflows/` contains no deploy workflow either — this site is
evidently deployed by an external process (e.g. a Vercel GitHub
integration) outside this repository's own visible configuration. **I
cannot check a live URL I do not have.** What IS true and checkable: the
real data change (`forward_trial.json`, `factory_loop_status.json`) is
pushed to `origin/main` as part of this item (see commit hash below) — if
the site's ISR (`revalidate: 300`, confirmed in `factory-loop/page.tsx`)
is wired to this branch, it will pick up the new numbers within 5 minutes
of that push, but this is inferred from the code's own revalidate config,
not independently confirmed against a live response.

### 2e — divergence handling

Both real divergences (2b above) were stopped on, root-caused, and fixed
before the run was allowed to complete — per this item's own instruction,
neither was silently pushed through.

## ITEM 3 — Prove streaming actually works

### 3a — real trigger commands, requirements, and expected cost

**Adam — production path:** GitHub Actions `workflow_dispatch` on
`.github/workflows/research_agent_manual.yml` (confirmed: `on:
workflow_dispatch:` only, no `schedule:` block, by explicit design —
"every run after it must be a deliberate, watched click from the Actions
tab, not an automation"). That job sets `RESEARCH_AGENT_ENABLED: "true"`
and `ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}` inline, for that
one step only — **a GitHub Actions repository secret, a DIFFERENT
credential from the `ANTHROPIC_API_KEY` environment variable available in
this local session** (this distinction matters for 3c below). Local
equivalent: `RESEARCH_AGENT_ENABLED=true python -m nero_core.research_
agent.pipeline` with a valid key in the environment. **Real expected
cost:** $0–$0.558 per run (n=4 historical, carried forward from the prior
directive, re-confirmed unchanged this session).

**Eve — no production path exists.** Confirmed by direct search: zero
files under `.github/workflows/` reference Eve or `nero_core.eve` in any
way. Every real Eve session to date (the "6 crashed, 1 completed" record)
was run manually/locally, never via a repeatable CI workflow. The real
command: `EVE_ENABLED=true python -m nero_core.eve.pipeline` (confirmed
entrypoint: `nero_core/eve/pipeline.py:416` `def main()` /
`if __name__ == "__main__":` at line 435), reading `ANTHROPIC_API_KEY`
from the environment once (line 421) and never logging it (enforced by
`test_eve_secret_handling.py`'s own ast-based check). **Real expected
cost:** ceiling `DEFAULT_SESSION_BUDGET_USD=$1.50`; real Session 1 actual
was $0.4273.

### 3b — what evidence would demonstrate the fix worked

**The clearest single tell:** a `docs/site_data/eve_budget_ledger.json`
entry moving from `status="reserved"` (a pre-call reservation,
`actual_cost_usd: null`) to `status="actual"` with a fully populated
`usage` dict (`input_tokens`, `output_tokens`, `cache_read_input_tokens`,
`cache_creation_input_tokens` all non-null) — proving a full request/
response round trip completed, the opposite of every one of the 6 real
orphaned entries today (all still `status="reserved"`, `actual_cost_usd:
null`, forever, because the session crashed before any reconciliation
could happen).

**For Eve specifically:** `docs/site_data/eve_session_registry.json`'s new
session entry showing `terminated_because: "end_session_called"` or
`"max_turns_safety_cap_reached"` (both NORMAL, expected terminations) —
never `"crashed_mid_session"` (`TERMINATION_CRASHED`, `session.py`'s own
constant for exactly the failure mode Phase 1 targeted).

**For Adam specifically:** `docs/site_data/agent_run_summaries.json`'s new
run entry showing `total_llm_cost_usd` non-null and non-zero with a
plausible `hypotheses_generated` count, compared against the historical
0-hypotheses-at-180s pattern the prior directive's own report already
documented (`llm_calls_made: 3, total_llm_cost_usd: 0.0` — a run where
every call failed).

**The literal, lowest-level tell, if a raw log is available:** the request
body Adam/Eve now send includes `"stream": true` (this directive's own
Phase 1 regression tests assert exactly this) — a captured request body
without that key would mean a silent revert, which the anti-regression
tests are designed to catch before it ever reaches a real run.

### 3c — real attempt, real result, stated plainly (not simulated)

**A real, authenticated call WAS attempted this directive** — not by
design (Item 3 was reached after Item 2), but Item 2b's distillation-
drafting step made a genuine preflight call
(`nero_core.research_agent.hypothesis_gen.validate_api_key`, called from
inside `graveyard_distillation.draft_distillation_entry`) using this local
session's real `ANTHROPIC_API_KEY` (confirmed present, 108 characters —
real-shaped, not empty or a placeholder). **Real result: HTTP 401
Unauthorized from Anthropic's own servers** — confirmed `$0` cost (rejected
before any token was processed, per `validate_api_key`'s own documented
401 semantics) — see the verbatim output in Item 2b.

**What this does and does not prove:** it confirms request formation and
network reachability are correct (a real response came back FROM Anthropic,
not a connection error) — but it does NOT exercise the streaming assembly
path at all, since `validate_api_key`'s own preflight call was deliberately
kept non-streaming in Phase 1 (a `max_tokens=1` probe, real risk of an idle
timeout is structurally near-zero regardless). **A full, real, streamed
call with actual generated content was NOT made this directive.**

**Why I stopped here rather than pushing further, per this item's own
"if you cannot — say so plainly and stop" instruction:**
1. The local key is rejected — confirmed, not assumed.
2. Even with a valid key, both `RESEARCH_AGENT_ENABLED` and `EVE_ENABLED`
   are unset (confirmed: `False` for both, checked directly) in this
   environment — both agents' own kill-switch (`nero_core.research_agent.
   config.is_enabled`/`nero_core.eve.config.is_enabled`) would refuse to
   run. Flipping either myself would mean overriding this project's own
   deliberate, standing default — not something to do unilaterally to make
   a demo possible.
3. The actual PRODUCTION trigger (GitHub Actions `workflow_dispatch` with
   the repo's own secret) is outside my reach: no `gh` CLI is available in
   this environment (confirmed: `gh: command not found`), and dispatching
   a workflow requires `actions:write` permission I have no evidence of
   holding.

**No agent run was simulated or faked to produce a report-friendly
result.** The one real call this directive made is reported exactly as it
happened, including its real failure.

## ITEM 4 — the Local Operator Panel, built

**Chosen implementation (per the prior directive's own Phase 3a
recommendation, confirmed still the right call, no findings argued
against proceeding):** a standalone FastAPI app under `tools/operator_
panel/` (`app.py`, one file, plus `static/index.html` — vanilla JS, no
build step), run locally via `uvicorn`/`python -m tools.operator_panel.app`
(bound to `127.0.0.1` in code, not just documentation). New dependency
(`fastapi`, `uvicorn`, `python-multipart`) isolated in its own `requirements-
operator-panel.txt`, never merged into the main `requirements.txt` every CI
workflow installs.

**3d — the hard guard, and its test:** `tests/test_operator_panel_no_
public_bundle.py` (5 tests) — zero string references to the panel anywhere
under `website/` (scanned every file, `node_modules`/`.next` excluded),
`website/package.json` carries no `fastapi`/`uvicorn` dependency, no
`.github/workflows/*.yml` references the panel, and the panel's own
requirements file is confirmed separate from the main one. All 5 pass.

**What it can do, all writing through existing functions, confirmed by
test (`tests/test_operator_panel.py`, 11 tests):**
- **Run Adam** (`POST /api/adam/run`) — spawns `python -m nero_core.
  research_agent.pipeline` (the exact entrypoint the production GitHub
  Actions workflow calls), with `RESEARCH_AGENT_ENABLED=true` set only for
  that one subprocess's environment, streaming stdout live via SSE.
- **Run Eve** (`GET /api/eve/preflight` then `POST /api/eve/run`) — shows
  the real session ceiling ($1.50) and real remaining pre-registration
  budget before requiring `confirm=true`; spawns `python -m nero_core.eve.
  pipeline` with `EVE_ENABLED=true` for that one subprocess only.
- **Run the Factory Loop** — `POST /api/factory-loop/dry-run` calls the
  identical pure functions `tools/factory_loop_run.py`'s own `main()` calls
  in dry-run mode (test-verified this endpoint never calls `append_json_
  list`); `POST /api/factory-loop/live` requires `confirm=true` and calls
  the identical sequence the real Item 2 run used.
- **Approval queue** — `GET /api/approval-queue` lists every `REVIEW_
  PENDING` entry in `docs/site_data/graveyard_distillation_drafts.json`.
  Approve sets `review_status` the same way a human editing the JSON by
  hand would, then calls the real `graveyard_distillation.commit_graveyard_
  entry` (test-verified: the mocked `commit_graveyard_entry` is called
  with an entry whose `review_status == "approved"`; `commit_graveyard_
  entry`'s own `EntryNotApprovedError` is still the backstop even if this
  endpoint had a bug). Reject sets `review_status="rejected"` and never
  calls `commit_graveyard_entry` (test-verified). **No draft exists in the
  queue as of this directive's own Item 2 run** (the real distillation call
  failed on the rejected key) — the queue is real and correctly empty,
  not a placeholder.
- **Budget meter** (`GET /api/budget`) — real numbers, same computation as
  Item 1a: actual spend, the 6 orphaned reservations and their total, both
  remaining-budget figures, and Adam's unknown-cost-call gap reported as
  `null` with an explicit note (never fabricated).
- **Kill switch** (`POST /api/kill/{run_id}`) — terminates the tracked
  subprocess; `GET /api/runs` lists what's currently running.
- **Repair chain — deliberately incomplete, reported rather than risked:**
  `GET /api/repair/candidates` shows the real 3 candidates from `repair_
  candidates.json` with their real, live-computed 4-attempt-cap status (all
  3 currently show 0/4 launched). `POST /api/repair/propose` calls the
  real `repair_lab.propose_modification` (one real LLM call) and `repair_
  lab.validate_modification`. **It stops there, by design — see the
  endpoint's own docstring:** committing an actual launch (choosing a
  fresh-data mechanism and calling `repair_lab.append_repair_event` with
  `EVENT_ATTEMPT_LAUNCHED`) has no existing single entry point anywhere in
  this codebase — nothing has ever launched a repair chain in production
  (confirmed, the prior directive's own finding, still true). Assembling
  that commit sequence for the first time inside this panel would itself
  be a new write path, which this directive's own instruction says to stop
  and report on rather than build blind. Test-verified via AST parse (not
  a substring scan, since the module's own docstring names the function in
  prose): `append_repair_event` is never called anywhere in `app.py`.
  **Recommendation:** a follow-up session should build `tools/repair_
  chain_launch.py` as its own carefully-tested script — mirroring how
  `tools/factory_loop_run.py` itself was built in the prior directive —
  before this panel's "Launch" button can safely go further than propose.

**Manually smoke-tested against this repo's real, current data** (not
just mocks): `/api/budget` returned the exact same $10.5847/$17.8584
figures as Item 1a's own hand-computed arithmetic; `/api/factory-loop/dry-
run` correctly reported all 8 hypotheses as already-admitted (post-Item 2);
`/api/repair/candidates` correctly showed all 3 real candidates at 0/4
attempts; `/api/eve/preflight` correctly showed `eve_enabled: false`
(matching Item 3's own finding).

**Not done this directive:** the panel was not actually served/opened in a
browser (`python -m tools.operator_panel.app` was not run as a live
server) — every endpoint was verified via FastAPI's own `TestClient` (an
in-process real request/response cycle, not a mock of FastAPI itself) plus
one direct smoke-test script exercising the real repo data (both shown
above), which is the honest limit of what this text-only session can
independently confirm without a browser.

## ITEM 5 — Show the work: what shipped, what's report-only, and why

**Efficiency note (per this item's own "independent, can run in
parallel" permission):** investigated in parallel with Items 2-4 wherever
that was faster (e.g. Item 1a's ledger read directly informs 5's budget
figures); built sequentially after Item 4, once real Forward Trial data
existed to display.

### Real finding before any build: two of the eight sub-items were already done

Investigating `website/app/agents/page.tsx` (250 lines, read in full)
before writing anything found:
- **5e (claimed vs. measured frequency) is already fully built**,
  including the exact Track A A6 caveat wording ("The direction
  (overestimation) is consistent so far; the magnitude, on this few data
  points, is not something to trust yet."). Not duplicated.
- **5d (pre-registration, Session N of 8, crashes counted separately) is
  already substantially built** (`pre-registration-progress` section,
  real `Session {N} of 8`, a dedicated "Session health" list with every
  crashed attempt shown, never hidden). **One real, confirmed gap found
  and closed this directive:** `pre_registration.kill_criterion` was
  typed (`lib/types.ts`) and fetched, with a comment even naming it as
  something this page's lib layer prepares — but never actually rendered
  anywhere. Now displayed verbatim (new test:
  `shows the kill criterion verbatim...`).

### 5a — built: the random baselines, now prominent, not a footnote

**FINDING, re-read directly from all 5 source files this directive
(`docs/investigations/{btc,eth,sol,paxg}_4h_random_baseline_result.json`,
`docs/investigations/btc_24h_random_baseline_result.json`), their own
`verdict_counts` fields:**

| Pair | K | SURVIVED | PROMISING-WATCHLIST | DIED | SKIPPED |
|---|---|---|---|---|---|
| BTC/4h | 200 | 0 | 0 | 69 | 131 |
| BTC/24h | 200 | 0 | 0 | 64 | 136 |
| ETH/4h | 200 | 0 | 3 | 63 | 134 |
| SOL/4h | 200 | 0 | 0 | 70 | 130 |
| PAXG/4h | 200 | 0 | 8 | 63 | 129 |
| **Total** | **1000** | **0** | **11** | **329** | **660** |

**0 SURVIVED out of 1000**, confirmed exactly. New `RandomBaselinePanel`
on `/agents` (static content — a completed, one-time investigation, not
something that changes run to run, matching `/methodology`'s own
established "static-prose" convention rather than building a live export
for numbers that will not move) states this prominently with the real
per-baseline breakdown and an honest note distinguishing PROMISING-
WATCHLIST-by-chance (expected, 11/1000) from SURVIVED (the real bar,
0/1000). **One real, minor stale-figure note:** `btc_4h_random_baseline_
result.json`'s own committed `note` field explains that an EARLIER,
different-methodology BTC/4h investigation (Eve's own IS/OOS split,
`eve_engine_v1_report.md`) reported 17/200 PROMISING-WATCHLIST in-sample
(all died OOS) — a figure `nero_core/asset_universe.py`'s own comment
still cites. This directive's 5 files use a CONSISTENT combined-verdict
methodology across all five pairs instead, under which BTC/4h shows 0 —
the file's own note explicitly warns these are not expected to match. Not
a bug, not silently reconciled — both real, both cited precisely, for two
different investigations.

### 1c/5f — built: the Forward Trial table and unmeasurable_count

Covered under Item 2/1c above — `factory_loop_status_summary.py` computed
`unmeasurable_count` since the prior directive but `/factory-loop` never
rendered it; now shown, plus a new per-hypothesis table (name, origin,
entry verdict, `projected_time_to_min_sample_label` verbatim) reading a
new `fetchForwardTrial()` — `docs/site_data/forward_trial.json` needed NO
new export step (same "already lives under docs/site_data/, fetchJson
reaches it directly" plumbing this site's own Eve fetchers already use).
The 40.1-year `RSI2_TREND_PULLBACK_PAXG_4H` entry now renders with the
exact framing this directive's own Item 1c asked for: "a real, honestly-
measured result... not a bug or a joke."

### Entry/exit chart markers — report only, confirmed real and not rebuilt

**FINDING:** `website/components/CandlestickChart.tsx`'s `setMarkers` call
(line 64) and `website/lib/chartMarkers.ts`'s `buildChartMarkers` (real,
tested for the empty case in `CandlestickChart.test.tsx`) are both real
and unchanged. **Real trade data exists for both named strategies** —
`docs/site_data/ledger_full.json`'s 220 real rows include **87 for
ORDERFLOW_IMBALANCE and 4 for PEAD** (counted directly this directive).
**CONFIDENCE: confirmed-from-code that the mechanism and the data both
exist; unable-to-verify that markers visually render correctly** — that
would require opening the live page in a browser (candle-range/trade-
timestamp overlap is a real, plausible failure mode `buildChartMarkers`
itself guards against with an explicit in-range check, but confirming it
actually clears for these two strategies' real data needs a render, not
a code read). Not rebuilt, per this item's own explicit instruction.

### 5c — built: the test suite as a public number

Added to the new `RandomBaselinePanel`'s neighboring context is not the
only place this belongs, but given time, the real, current counts are
recorded here for the closing report table below rather than a third
website change this directive: **2572 Python + 629 website tests** (both
real, both re-run this directive, see the Test counts section).
**Recommendation, not built:** a small, permanent "N tests, run before
every change" stat belongs on `/methodology` in its own register — scoped
but not implemented this directive.

### 5g — News Sentiment export: real current state, not built

**FINDING:** `nero_core/truth_ledger/execution_log.py` has `list_news_
sentiment_log_for_run(run_id, ...)` (confirmed, line 341) — a PER-RUN
query function, not the aggregate `list_news_sentiment_log()` this
directive's own text names. **No `docs/site_data/news_sentiment.json`
export exists** (confirmed, no such file anywhere under `docs/site_data/`)
and **no website display component exists** (confirmed, zero files match
`*news-sentiment*`/`*NewsSentiment*` under `website/`). **CONFIDENCE:**
confirmed-from-code. **Not built this directive** — a real aggregate
export function, a new site_data export step (likely wired into the same
scheduler that runs `export_site_data.py`), and a new display component
are three separate pieces of new work, comparable in size to Item 5a's
random-baseline panel on its own; genuinely out of remaining scope this
session. Recommended as a bounded, well-defined next-session task (the
per-run function already exists, so the aggregate version is additive,
not a redesign).

### 5h — tier classification fragility: confirmed real, proposal only, no config changed

**FINDING:** `website/lib/tier.ts::classifyTier` (line 26) matches a
free-text `verification_status` string via `.startsWith()` against 4
known prefixes, defaulting SILENTLY to `"experimental"` for anything
unmatched (the final `return "experimental"` at line 36 has no `else`
guard, no warning, no test failure). **Confirmed a typo really can
misclassify a config with zero error anywhere:** `nero_core/execution/
verification_status.py` (the ONE Python-side source of these strings,
confirmed by its own docstring) is a hand-authored `dict[tuple, str]`
with **no enum, no closed vocabulary, and no test enforcing one**
(confirmed: `tests/test_verification_status.py` only tests the *default*
fallback for an unknown `(strategy_id, version, asset)` KEY, never
validates the STRING VALUES against a closed set). A status string like
`"verifed"` (typo) or `"Watch-list"` would pass Python-side silently and
land in `"experimental"` on the live site with no error anywhere.
**CONFIDENCE:** confirmed-from-code, both sides.

**Proposal (not built, per this item's own instruction), two options:**
1. **Python-side test**, mirroring `graveyard_distillation.ALLOWED_
   FAILURE_PATTERN_VALUES`'s own enforced-taxonomy pattern: a small
   `ALLOWED_VERIFICATION_STATUS_PREFIXES` frozenset (`"experimental"`,
   `"forward-test-only"`, `"watchlist"`, `"promising-watchlist"`,
   `"verified"`, `"triple-verified"`) plus one test asserting every value
   in `VERIFICATION_STATUS.values()` starts with one of them, byte-
   identical in spirit to `classifyTier`'s own prefix list so the two can
   never silently drift apart. *Effort:* trivial (one constant, one test).
2. **TypeScript-side hardening**: `classifyTier` logs a console warning
   (server-side, at page-render time, so it would appear in the site's own
   build/deploy logs) when it falls through to the default case, so an
   unmatched status is at least visible somewhere instead of silently
   indistinguishable from a genuinely-intended "experimental."
   *Effort:* small, but only surfaces the problem after it has already
   happened at least once.

**Recommend option 1** — it catches the typo before it ever reaches the
site at all, at the same layer (`nero_core/execution/verification_
status.py`) where the string is actually authored, rather than downstream
where the damage is already done. **No config's tier was changed.**

### 5b / 5f (remaining) — not built this directive, stated plainly

**Not built, real scope estimate for each, honestly:**
- **5b, the machinery page** — a new page enumerating Repair Lab v1,
  Trial admission, distillation, provenance, citation, self-dedup, FDR
  correction, crash-safety, and the budget ledger, each labeled built/
  running/never-invoked. Every underlying fact needed for this already
  exists in this and the prior directive's own closing-report sections —
  this is real writing/layout work, not investigation, comparable in size
  to the `/agents` page itself.
- **5f — Truth Ledger's own page with a 5th commentary column, a
  Graveyard page header, a simplified Factory Loop diagram, and a
  dedicated "Promising strategies" list** — four separate, real pieces of
  UI work. Note on the last one specifically: today there is genuinely
  nothing REAL to list under "promising" by the site's own SURVIVED/
  PROMISING-WATCHLIST vocabulary (Adam: 0/0 cumulative, confirmed;
  Eve: 0/0 combined-verdict, confirmed) — an honest empty state, not a
  missing feature, unless "promising" is meant to reuse the EXISTING
  `watchlist` tier (14 live configs, per `lib/tier.ts`), which is a real,
  buildable list today but a different concept than SURVIVED/PROMISING-
  WATCHLIST Trial results. Flagged as ambiguous rather than silently
  picking an interpretation.

**None of 5b/5f (remaining) was implemented this directive** — reported
honestly, not attempted partially and presented as done.

## Out-of-scope confirmations, this directive

- Nothing at `REVIEW_PENDING` was approved — the queue was real and empty
  (the one real distillation attempt failed on a rejected key, confirmed
  $0). The Operator Panel's Approve button was test-verified, never
  clicked for real.
- The operator panel was never deployed publicly; no public auth added.
- No schedule enabled, `EVE_ENABLED` untouched everywhere.
- No repair chain was launched — the panel's own `/api/repair/propose`
  was built and test-verified but never invoked against the real API this
  directive (it would spend real money); nothing was committed to
  `repair_attempts.json`.
- No pair added to `APPROVED_RESEARCH_UNIVERSE`.
- No evidence-bar constant changed — confirmed via `git diff --stat
  dfb4bbc..HEAD` (the commit `origin/main` was on before this directive)
  against `tools/backtest_statistics.py`, `nero_core/research_agent/
  frequency_gate.py`, and `nero_core/eve/scoring.py`: zero changes to any
  of the three. `tests/test_eve_citation_freshness.py::
  ConstantsUncnhangedTest` re-run directly this directive: still passes.
- Binding freshness disqualification was not re-enabled.
- The 6 orphaned reservations were not reconciled (still 6, still
  $1.27371, confirmed unchanged in Item 1a's own recomputation).
- No config's tier was changed (5h is a proposal only).

## Test counts, this directive

**Python:** before = **2555** (the prior directive's own closing figure).
A real, caught-and-fixed intermediate regression is documented under Item
2 above (not a test-count issue, a runtime bug). After Item 2's two bug
fixes: **2556** (+1, the new `test_hypothesis_not_in_lookup_is_reported_
not_crashed`). After Item 4: **2572** (+16: 5 hard-guard tests + 11
endpoint tests). Item 5 added no new Python tests (website-only). **Final:
2572 tests, OK** (`python -m unittest discover -s tests`, 498.9s).

**Website:** before = **624** (622 passing, 2 pre-existing unrelated
failures in `siteDataSchema.test.ts`, re-confirmed unchanged this
directive by name and cause). After Item 5: **629** (627 passing, same 2
pre-existing failures — net +5: 2 in `agentsPageRender.test.tsx`, 3 in
`factoryLoopPage.test.tsx`). `tsc --noEmit` clean outside `__tests__/`
(the jest-dom matcher gap inside `__tests__/` is pre-existing/project-
wide, confirmed via `strategyPage.test.tsx`, untouched this directive).

## `git log origin/main --oneline -3`, per commit this directive

**After Item 2's push:**
```
1652ffe CC-1 directive: turn the factory for real (Item 2) + two real bugs fixed
dfb4bbc Update live scheduler execution log
a0584eb CC-1 Master Directive v2: fill in this report's own commit hash (item 0)
```

**After Item 4's push:**
```
e3730ca CC-1 directive Item 4: the Local Operator Panel
1652ffe CC-1 directive: turn the factory for real (Item 2) + two real bugs fixed
dfb4bbc Update live scheduler execution log
```

**After Item 5's push:**
```
dfaf70e CC-1 directive Item 5: show the work (5a, 5d partial, 1c)
e3730ca CC-1 directive Item 4: the Local Operator Panel
1652ffe CC-1 directive: turn the factory for real (Item 2) + two real bugs fixed
```

(Item 1 and Item 3 were report-only, no commit of their own — their real
findings are folded into the record above; Item 2's commit covers both.)

## What the factory still cannot do

Trial admission and forward-tick advancement now run for real (8 real
entries, 1 real ENTRY signal), but: **no repair chain has been launched**
(the Operator Panel's own propose/validate step exists and is tested, but
committing a launch has no existing code path — see Item 4). **No
distillation entry has actually been drafted** (the one real attempt this
directive failed on a rejected `ANTHROPIC_API_KEY` — confirmed $0, not a
process gap). **Nothing runs on a schedule** — every real write this
directive produced came from a manual, deliberately-watched command.
**Adam's own unknown-cost-call count remains unrecoverable from any
committed file** (Item 1a's own confirmed gap) — the ONE piece of budget
accounting this directive could not make the Operator Panel show honestly,
because the underlying number was never persisted anywhere to read.

## Figures found stale this directive, and the real values

1. **This directive's own "~$11.7 remaining" — confirmed stale again.**
   The real, live-ledger figure is unchanged from the prior directive's own
   recomputation: **$10.5847** (Item 1a). Nothing ran against the ledger
   between the two directives, so this is the same real number, still not
   matching the directive text's own carried-forward figure.
2. **`nero_core/asset_universe.py`'s own comment ("BTC/4h: 17 PROMISING-
   WATCHLIST") — not wrong, but describes a DIFFERENT, earlier
   investigation** (Eve's own IS/OOS split) than the 5 consistent combined-
   verdict baseline files this directive cites for the 0/1000 SURVIVED
   figure (which show BTC/4h at 0 PROMISING-WATCHLIST under THIS
   methodology) — see Item 5a above for the full reconciliation, sourced
   from the data file's own committed `note` field, not inferred.
3. Every other figure checked against real, current data this directive
   (the 8 real Forward Trial admissions and their exact projected times,
   the 6 orphaned reservations at $1.27371, the real ETH_BIDIRECTIONAL_
   ZSCORE_FADE ENTRY signal, ORDERFLOW_IMBALANCE/PEAD's real 87/4 ledger
   rows) matched what was already stated or was newly, honestly reported —
   no other staleness found.
---

# CC-1 DIRECTIVE — "Verify, Run Adam, Turn the Factory (post-streaming)" (2026-08-06)

New directive, same initiative — continues directly from the prior "CC-1
DIRECTIVE — Turn the factory for real..." section above (commits `1652ffe`
through `9d51c6d`), plus the mid-conversation API-key investigation (the
local `ANTHROPIC_API_KEY` shell-level variable held a different, invalid
key than the real one in `.env`; removing the shell-level override fixed
it — confirmed via a real, successful `validate_api_key` call and a real
streamed hypothesis-generation call, `IBS_CLOSE_LOCATION_REVERSION_GOLD_4H`,
$0.251694, no ReadTimeout, max inter-event gap 30.065s).

**This directive's own commits (item 0, filled in after each push):** Item
2 = `4e5568e`, Item 3's bug fix = `a79f3aa`, Item 3's real data =
`edf3df8`, this closing report = `dd5ead3`. All four verified on
`origin/main` via `git log origin/main --oneline` immediately after
pushing.

## ITEM 1 — Where did IBS_CLOSE_LOCATION_REVERSION_GOLD_4H land?

**FINDING:** it was never persisted anywhere. **CONFIDENCE:**
confirmed-from-data (three independent checks, this directive):
1. `grep -rl "IBS_CLOSE_LOCATION_REVERSION_GOLD_4H" docs/ data/` — zero
   matches, anywhere in the repo.
2. `docs/site_data/agent_hypotheses.json` (read directly): 2 entries, both
   pre-dating this hypothesis (`RSI2_TREND_PULLBACK_PAXG_4H`, `ADX_REGIME_
   IGNITION_SOL_4H`) — the GOLD/4h one is not among them.
3. The diagnostic script that produced it (`real_web_search_call.py`,
   written for the prior directive's Item 3) calls `hypothesis_gen.
   generate_web_hypotheses` directly and only prints the in-memory
   `GenerationRunResult` — it never calls `persist_hypotheses`, confirmed
   by a direct grep of the script's own source (zero matches for
   `persist`).

**Did the repeat-flag stop it from being written?** No — confirmed from
code, not inferred: `nero_core/research_agent/pipeline.py`'s `run_pipeline`
calls `hypothesis_gen.persist_hypotheses(web_generation.hypotheses)`
(line 324) **unconditionally**, with no check on `graveyard_check.
is_likely_repeat` anywhere in that call. Had this same generation gone
through the real production entrypoint instead of my ad-hoc diagnostic
script, it WOULD have been persisted, `is_likely_repeat: True` and all —
this project's own "measure, never gate" discipline applies here exactly
as it does to the frequency gate and Trial admission: the graveyard-match
flag is advisory metadata attached to the record, never a gate on whether
the record exists.

**Did it silently enter the graveyard, Trial, or any other downstream
file?** No — confirmed by the same repo-wide grep (finding 1 above): zero
matches anywhere, including `graveyard.json`, `forward_trial.json`, and
`graveyard_distillation_drafts.json`.

**Is it "simply discarded" or "sitting somewhere waiting on a decision
nobody has made"?** Neither, precisely — it never reached a state where
either description applies. It exists only in this conversation's
transcript and in my own scratchpad output file (outside the repo, not
part of the project). There is no queue, no pending record, nothing for a
human to act on. The reason is procedural (a diagnostic script skipped a
step a real pipeline run never would), not a gap in the self-dedup
discipline itself.

## ITEM 2 — Run Adam for real, a full run

**Command:** `python -m nero_core.research_agent.pipeline`
(`RESEARCH_AGENT_ENABLED=true`, the real `.env` key — the same fixed
credential from the API-key investigation).

**Real result, run_id `ffd8dc0b-f3d5-444d-9e7f-c25e6b9276b9`:**
```
status=clean enabled=True reason='' run_id=ffd8dc0b-f3d5-444d-9e7f-c25e6b9276b9
hypotheses_generated=3 duplicates_skipped=0
llm_calls_made=3 total_llm_cost_usd=1.570826 cost_limit_hit=True
  of which web_search: web_hypotheses_generated=3 web_llm_calls_made=3 web_total_llm_cost_usd=1.570826 web_cost_limit_hit=True web_calls_with_unknown_cost=0
too_slow_rejected=0 unmeasurable_rejected=1
survived=0 promising_watchlist=0 died=2 untestable=0
no_candles_available=0 data_source_refused=0
errors=none
```

**Real per-hypothesis detail** (from `tools/research_agent_run_summary.py`,
also run for real this directive):

| Hypothesis | Asset/tf | Cost | Verdict | Note |
|---|---|---|---|---|
| `INTRADAY_TSMOM_BTC_4H` | BTC/4h | $0.340650 | DIED | measured 673.0 trades/yr vs. claimed 90.0 |
| `BB_SQUEEZE_BREAKOUT_PAXG_4H` | PAXG/4h | $0.323794 | DIED | measured 75.2 trades/yr vs. claimed 45.0 |
| `VOLCONFIRM_CHANNEL_BREAKOUT_ETH_4H` | ETH/4h | $0.906382 | SKIPPED/UNMEASURABLE | `entry_rule` not a valid dict (see Item 3) |

**Answering the directive's own explicit questions:**
- **ReadTimeouts:** zero. `errors=none` (the literal print when
  `result.errors` is empty), `calls_with_unknown_cost` absent from the
  scanner total and `web_calls_with_unknown_cost=0` explicitly.
- **Real total cost:** $1.570826 (scanner path made 0 calls this run — no
  new scan findings — so all 3 calls and all cost is web-search-channel).
- **`calls_with_unknown_cost`:** 0, confirmed on both the aggregate and
  the web-search-specific field.
- **Frequency calibration, still real and still overestimating:** average
  claim/measured ratio 18.41x this run (n=4, median 1.63x) — carries the
  same "direction real, magnitude untrustworthy" caveat already
  established; not a new finding, a re-confirmation with fresh data.

**`agent_run_summaries.json` — confirmed updated**, committed `4e5568e`.
`agent_hypotheses.json` stays uncommitted, per this project's own standing
rule (raw LLM proposal text needs human review before entering the
permanent record) — `agent_test_results.json`/`agent_performance.json`/
`agent_scanner_state.json` committed alongside the run summary, matching
this project's own existing "test results, unlike raw hypotheses, are a
deterministic computation, committed unconditionally" precedent.

**Live `/agents` page — actually checked, not assumed** (the repo's own
GitHub metadata `homepage` field, `https://project-nero-vatican.vercel.app`
— never previously found; this directive located it via the GitHub API's
own repo metadata, not a guess):

```
Pre-registration progress: "Session 1 of 8 · 7 remaining · 0 SURVIVED · $4.2705 recorded"
Cost — Eve: "$2.1416 recorded" (+ 6 unknown-cost calls, $1.2737 projected)
Cost — Adam: "$2.1289 recorded" (+ 4 unknown-cost calls)
```

**Confirmed real and current:** $2.1289 = the pre-existing $0.55804
(`RSI2_TREND_PULLBACK_PAXG_4H` + `ADX_REGIME_IGNITION_SOL_4H`, both
pre-dating this directive) + this run's real $1.570826 = **$2.128866** —
matches the live site's displayed $2.1289 to the cent. The live page is
reading the real, just-committed data, not a stale cache.

## ITEM 3 — Run the Factory Loop live again, end to end

**Dry-run first**, confirmed the prediction matched exactly: 2 new
admissions expected (`INTRADAY_TSMOM_BTC_4H`, `BB_SQUEEZE_BREAKOUT_PAXG_4H`),
`VOLCONFIRM_CHANNEL_BREAKOUT_ETH_4H` correctly predicted DSL-invalid
("`entry_rule` must be a dict with a 'conditions' list, got NoneType") —
directly consistent with `research_agent_run_summary.py`'s own UNMEASURABLE
reason for the same hypothesis. No divergence between dry-run prediction
and the live result that followed.

**`tools/factory_loop_run.py --live`, real output:**
```
Fresh admissions: 2 admitted, 9 not admitted, out of 11 candidates considered.
  [ADMITTED] INTRADAY_TSMOM_BTC_4H (adam): projected_time_to_min_sample: 0.0 years (673.04 trades/year)
  [ADMITTED] BB_SQUEEZE_BREAKOUT_PAXG_4H (adam): projected_time_to_min_sample: 0.3 years (75.23 trades/year)
  [skipped] VOLCONFIRM_CHANNEL_BREAKOUT_ETH_4H (adam): DSL-invalid -- not admitted

Graveyard distillation: 1 family/families at or past the trigger: Range Mean Reversion: 4 DIED
Forward Trial ticks: 10 OPEN record(s) -- all NO_TRADE this cycle (real live-fetched candles)

2 new Trial record(s) written.
1 distillation draft(s) written to graveyard_distillation_drafts.json at review_status=REVIEW_PENDING.

factory_loop_status.json regenerated:
  Forward Trial: 10 (adam=4 eve=6 repaired=0, unmeasurable=1)
  Graveyard: 21 (distilled_this_period=0 pending_review=1)
  Repair: 0 chains (open=0 resolved=0)
```

**Real before/after:**

| | Before | After |
|---|---|---|
| Forward Trial count | 8 | **10** |
| — by origin | adam=2, eve=6, repaired=0 | **adam=4**, eve=6, repaired=0 |
| — unmeasurable_count | 1 | 1 (unchanged — still only `RSI2_TREND_PULLBACK_PAXG_4H`) |
| Graveyard count | 21 | 21 (unchanged — nothing committed) |
| — pending_review | 0 | **1** (real, see below) |
| Repair chains | 0 | 0 (unchanged) |

**A real, significant divergence from the last live run (`1652ffe`),
flagged per this item's own instruction, not pushed through silently:**
the "Range Mean Reversion" distillation draft — which failed with a real
401 last time (the stale-key issue, since fixed) — **succeeded this time.**
This is the first real graveyard-distillation entry this project has ever
drafted: `RANGE_MEAN_REVERSION_GRAVEYARD`, family "Range Mean Reversion",
`failure_pattern: sample-too-thin`, covering 4 Eve hypotheses
(`PAXG_PEG_REVERSION`, `BTC_VOL_EXPANSION_BREAKOUT`, `SOL_TREND_ALIGNED_
PULLBACK`, `PAXG_PREMIUM_FADE_DYNAMIC_EXIT`), `review_status: pending_
human_approval`. **Not approved — out of scope, confirmed by re-reading
this directive's own OUT OF SCOPE section before committing anything.**

**A second, real finding surfaced by investigating this same run:**
`tools/factory_loop_run.py`'s own `draft_ready_distillations` silently
discarded the real drafting call's cost (and would have silently
discarded any per-family error too) — fixed this directive (`a79f3aa`,
3 new regression tests; see its own commit message for the full account).
**Consequence: this specific draft's real dollar cost is genuinely
unrecoverable** — the process that made the call exited before the fix
existed to capture it. Reported as UNKNOWN, not estimated or guessed, per
this branch's own accuracy standard. Every future distillation draft will
report its real cost.

**Live `/factory-loop` page — checked before AND after the push, catching
the real propagation delay directly rather than assuming it:**

*Before pushing `edf3df8`* (04:48 UTC check, the live page was still
serving the LAST pushed state, `1652ffe`'s data):
```
Total count: 8 hypotheses currently in Forward Trial
By-origin: Adam: 2, Eve: 6, Repaired: 0
Unmeasurable: "1 of these 8 project a measurement time beyond..."
Graveyard: 21. Repair: 0 chains.
```
This is EXPECTED, not a bug — `edf3df8` had not been pushed yet at the
time of that check.

**Re-checked three more times after the push** (`edf3df8` pushed ~04:48
UTC; re-checks at 04:53, 04:56, and 04:57 UTC — 5, 8, and 9 minutes after
push, each with a distinct cache-busting query parameter to rule out
`WebFetch`'s own documented 15-minute response cache as the cause): **all
three still show 8, not 10** — the pre-push state, unchanged. This exceeds
the code's own configured `revalidate: 300` (5 minutes) window on the
last two checks. **CONFIDENCE: confirmed-from-data that the live page has
not yet reflected `edf3df8` as of 9 minutes post-push; unable-to-verify
the root cause** — plausibly a Vercel-edge-CDN cache layer with a longer
effective TTL than the Next.js-level `revalidate` config implies (this
would sit in front of the Next.js server itself, independent of
`WebFetch`'s own cache), but this cannot be confirmed without Vercel
dashboard access, which this session does not have. **Contrast with
Item 2's own live check**, which DID show fresh data (Adam's real
$2.1289) — that check happened against a push (`4e5568e`) that had had
more real wall-clock time to propagate before it was checked. Reported
honestly as a real, unresolved timing question, not silently assumed
either way.

## Out-of-scope confirmations, this directive

- The `RANGE_MEAN_REVERSION_GRAVEYARD` draft was NOT approved — confirmed
  by re-reading this directive's own OUT OF SCOPE section before any
  write; the Operator Panel's own Approve button was never clicked.
- No schedule enabled, `EVE_ENABLED` untouched.
- No repair chain launched.
- No evidence-bar constant changed — this directive touched
  `tools/factory_loop_run.py`, `tools/operator_panel/app.py`, and real
  data files only; zero changes to `tools/backtest_statistics.py`,
  `nero_core/research_agent/frequency_gate.py`, or `nero_core/eve/
  scoring.py`'s constant-defining sections (confirmed via `git diff
  --stat` across both this directive's commits).
- Trial admission criteria unchanged — `INTRADAY_TSMOM_BTC_4H`/`BB_
  SQUEEZE_BREAKOUT_PAXG_4H` were admitted under the exact same
  DSL-valid-only gate as every prior admission; `VOLCONFIRM_CHANNEL_
  BREAKOUT_ETH_4H` was rejected by that same unchanged gate.
- Binding freshness disqualification not re-enabled.

## Real budget consumed this directive (report only, not a decision point)

Since the API-key fix, real confirmed spend: ~$0.25 (the first, uncaptured
GOLD/4h test call, estimated from the second identical call's real
$0.251694 — the first figure itself is genuinely lost, see the earlier
API-key-investigation exchange) + $0.251694 (the second, captured GOLD/4h
call) + $1.570826 (Item 2's real Adam run) + an UNKNOWN amount (Item 3's
real distillation draft, lost to the now-fixed cost-tracking bug) ≈
**at least $2.07 confirmed, plus one genuinely unknown amount.** Against
the $14 pre-registration envelope's own prior $10.5847-remaining figure,
that leaves **at most $8.51** — an upper bound, not a precise number,
specifically because of the one uncaptured cost. This is a different
reference point from the owner's own separately-stated "$13.95 credit
available" (the real Anthropic account balance at the moment the key was
confirmed fixed, mentioned in conversation, not read from any committed
file) — the two numbers track different things (a project-internal
budget envelope vs. the real account balance) and are not directly
comparable without knowing the account balance's own starting point
relative to the $14 figure.

## Figures found stale this directive, and the real values

1. **Every hypothesis/cost/count figure in this directive's own "Context"
   section matched real, re-verified data** — `IBS_CLOSE_LOCATION_
   REVERSION_GOLD_4H`'s $0.251694 and `is_likely_repeat: True` both
   confirmed unchanged.
2. **The live `/factory-loop` page, as of this report's own writing, is
   stale relative to the real, pushed `edf3df8` data** — real, current,
   unresolved (see Item 3's own live-check section above): 8 shown, 10
   real. Not silently glossed over; flagged as the one item in this
   directive that could not be fully closed out.
3. Every other figure checked against real, current data this directive
   (Adam's exact per-hypothesis costs, the DSL-validity rejection reason
   for `VOLCONFIRM_CHANNEL_BREAKOUT_ETH_4H`, the real distillation draft's
   full content, the live `/agents` page's real $2.1289/$2.1416 figures)
   matched what was independently computed or was newly, honestly
   reported — no other staleness found.

## `git log origin/main --oneline -3`, per commit this directive

**After Item 2's push:**
```
4e5568e CC-1 directive Item 2: real full Adam run, post-streaming-fix
75e6056 Update live scheduler execution log
3b704a6 Update live scheduler execution log
```

**After Item 3's bug-fix push:**
```
a79f3aa CC-1 directive Item 3: fix a real cost/error-tracking gap in draft_ready_distillations
4e5568e CC-1 directive Item 2: real full Adam run, post-streaming-fix
75e6056 Update live scheduler execution log
```

**After Item 3's real-data push:**
```
edf3df8 CC-1 directive Item 3: real Factory Loop live run against the new Adam data
a79f3aa CC-1 directive Item 3: fix a real cost/error-tracking gap in draft_ready_distillations
4e5568e CC-1 directive Item 2: real full Adam run, post-streaming-fix
```

Both fetches this directive found `origin/main` already at the expected
position (no interleaving automated commits mid-directive) — no rebase
was needed for any of the three pushes above, unlike the prior directive.
