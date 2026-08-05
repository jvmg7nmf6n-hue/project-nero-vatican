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
inserted between the Graveyard and Lab links. **Live-URL verification:
pending until after this section's own commit is pushed and confirmed
landed (item 0) and the site's 300s ISR revalidation window has passed --
see the verification note at the end of this section.**

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

**PUSH_LOG_PLACEHOLDER**

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
