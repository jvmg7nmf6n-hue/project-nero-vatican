# CC-1 — Per-hypothesis freshness attribution via explicit source citation

Closing report, dated 2026-08-05. Response format per item: FINDING → CONFIDENCE
(confirmed-from-code / confirmed-from-data / unable-to-verify) → WHAT SHIPPED.

## Context recap

`3697e75` confirmed the freshness gate's 100%-disqualification was structural,
not an attribution limitation: even a causally-safe per-hypothesis rule
("a hypothesis may only be affected by searches preceding it") still yields
100%, because Eve front-loads all searching before proposing (see
`factory_loop_implementation_report.md` §4). This directive's approach:
Eve explicitly declares which of her own session's real search results
support each hypothesis; freshness risk attaches only to cited sources.
Both load-bearing constraints hold: **never binding, by any path** (item 7),
and **the self-declaration is recognized for what it is** (item 6).

---

## 1. The field — present always, contents may be empty

**FINDING:** `supporting_source_urls` is documented in
`nero_core/eve/tools_defs.py:69-83` (`PROPOSE_HYPOTHESIS_TOOL`'s own
description) and `nero_core/eve/session.py`'s new `CITATION_BLOCK` (inserted
into `SYSTEM_PROMPT_TEMPLATE`). The field lands on the persisted hypothesis
record at the **top level**, not inside `raw_hypothesis` —
`nero_core/eve/hypothesis_shapes.py:72-121` (`build_hypothesis_record`) sets
`record["supporting_source_urls"]` via the new `_extract_supporting_source_urls`
helper (`hypothesis_shapes.py:72-91`), always a list (default `[]`),
normalized from whatever Eve put inside her free-form `hypothesis` object.

**Deliberately NOT injected into `raw_hypothesis` itself.** That module's own
docstring already documents `generated_at` as the *one* deliberate exception
to "recorded AS-IS" (`hypothesis_shapes.py:1-16`); a second silent exception
would quietly break that guarantee and the existing verbatim-preservation
test (`test_eve_hypothesis_shapes.py::test_preserves_raw_hypothesis_verbatim_except_the_injected_generated_at`).
Confirmed this test still passes unmodified.

**Validation against real data:** `nero_core/eve/scoring.py`'s new
`validate_supporting_source_urls` (line 785) and `_session_search_url_index`
(line 748) check every claimed URL against `_iter_web_search_results`'s own
traversal of the session's real `web_search_tool_result` blocks — the same
traversal `check_freshness_disqualification`/`tag_lookahead_risk` already
use, so this can never silently disagree with them on what counts as a real
search result. A URL absent from that set is a **hard validation error**:
recorded explicitly in `supporting_source_urls_invalid` (never silently
dropped) and surfaced as a `WARNING:` line on stderr per offending
hypothesis, plus an `n_citation_validation_errors` count in
`ablation_metadata` (`nero_core/eve/pipeline.py:353-374`).

**Citation status — three distinguishable situations**, per
`classify_citation_status` (`scoring.py:803-827`):
- `CITATION_STATUS_NO_SEARCHES` ("no_searches_in_session") — the session
  performed no web searches at all.
- `CITATION_STATUS_NO_SOURCES_CLAIMED` ("no_sources_claimed") — searches
  happened, this hypothesis's validated citation list is empty.
- `CITATION_STATUS_CITED` ("cited") — one or more validated URLs.

**CONFIDENCE:** confirmed-from-code.

**WHAT SHIPPED:**
- `nero_core/eve/tools_defs.py` — `PROPOSE_HYPOTHESIS_TOOL` description
  updated (neutral wording, see item 4).
- `nero_core/eve/hypothesis_shapes.py` — `_extract_supporting_source_urls`
  + 5 new always-present top-level record fields
  (`supporting_source_urls`, `citation_status`,
  `supporting_source_urls_validated`, `supporting_source_urls_invalid`,
  `per_hypothesis_freshness`, the last four starting `None` until scoring
  fills them in — the same "starts unscored" convention `testability`/
  `verdict_is` already use).
- `nero_core/eve/scoring.py` — `validate_supporting_source_urls`,
  `classify_citation_status`, `_session_search_url_index` (lines 748-827).

### Critical requirement: empty citation never gates DSL validity or Trial admission

**Exact validation path checked:** `nero_core.eve.scoring.classify_testability`
(the same rule-DSL parser `session.py`'s pre-submit validator and
`scoring.score_hypothesis` both use — reads only
`structured_entry_rule`/`structured_exit_plan`, confirmed directly from
`nero_core/research_agent/rule_dsl.py:206-243,352-368`, which never touches
`supporting_source_urls`), and `nero_core.research_agent.trial.is_dsl_valid`
/ `admit_to_trial` (item 4's real gate, unchanged — still DSL-validity only,
per `3697e75`).

**Test:** `tests/test_eve_citation_freshness.py::SupportingSourceUrlsNeverGatesDslOrTrialTest`
(6 tests) — a hypothesis with a **missing** `supporting_source_urls` key and
one with an **explicitly empty** list both: (a) classify as `TESTABLE`,
(b) are admitted by `admit_to_trial` with `admitted=True`, (c) confirms
`admit_to_trial`'s real signature has no `citation_status`/
`supporting_source_urls`/`per_hypothesis_freshness` parameter at all (the
same "parameter doesn't exist, not merely defaulted off" pattern
`AdmitToTrialNeverConsultsFreshnessTest` already established for freshness).
All 6 pass.

---

## 2. Freshness attributed to the citation, not the session

**FINDING:** added a **sibling** function, not a modification —
`check_freshness_disqualification` (session-wide) is byte-unchanged, still
computes and records exactly as before, including every item 7a audit field
(`offending_source_url`, `parsed_pub_date`, `rule_fired`, `hypothesis_name`).
The new `check_per_hypothesis_freshness` (`scoring.py:830-877`) attributes
freshness risk **only** to a record's own `supporting_source_urls_validated`,
reusing the identical Variant C rule
(`FRESHNESS_DISQUALIFICATION_WINDOW_DAYS`/`_RULE`) against each cited URL's
own parsed publication date — not a second, independently-tuned threshold.
`apply_per_hypothesis_freshness` (`scoring.py:880-908`) applies this across
a session's scored records, always setting every field (never left absent),
mirroring `apply_freshness_disqualification`'s own discipline.

**"Nothing to check" is a distinct, explicit result** — never "clean" (which
would imply a real check ran and found no risk): `PER_HYPOTHESIS_FRESHNESS_NOTHING_TO_CHECK`
for `CITATION_STATUS_NO_SEARCHES`/`CITATION_STATUS_NO_SOURCES_CLAIMED`, vs.
`PER_HYPOTHESIS_FRESHNESS_CHECKED_CLEAN`/`_CHECKED_DISQUALIFIED` when a real
check actually ran against cited URLs.

**Item 7a fields kept working, confirmed by test:**
`CheckPerHypothesisFreshnessTest::test_checked_disqualified_when_cited_source_is_within_the_freshness_window`
asserts `offending_source_url`, `rule_fired`, `parsed_pub_date`, and
`hypothesis_name` are all present on a disqualified per-hypothesis result.

**Direct proof this is narrower than the session-wide check** (the entire
point of item 2):
`CheckPerHypothesisFreshnessTest::test_per_hypothesis_attribution_is_narrower_than_the_session_wide_check`
constructs one session with one recent search result. The session-wide
`check_freshness_disqualification` flags the session (1 flag — every
hypothesis would be marked disqualified under the old mechanism). The
per-hypothesis check only flags the hypothesis that actually cited that URL;
a hypothesis in the same session that cited nothing gets
`PER_HYPOTHESIS_FRESHNESS_NOTHING_TO_CHECK`. Test passes.

**CONFIDENCE:** confirmed-from-code, confirmed-from-test.

**WHAT SHIPPED:** `nero_core/eve/scoring.py:664-908` (sibling section,
clearly demarcated with its own module-level comment explaining the
relationship to `check_freshness_disqualification`);
`nero_core/eve/pipeline.py:325-331` wires `apply_per_hypothesis_freshness`
into `run_pipeline`, right after the existing session-wide
`apply_freshness_disqualification` call, before FDR correction.

---

## 3. Does Adam already have this?

**FINDING:** No — the freshness rule applies **only to Eve's session-scoped
path today**. Grepped every reference to `freshness`/`FRESHNESS` across
`nero_core/research_agent/`: the only hits are an unrelated docstring
mention (`pipeline.py:59`, "Adam's own scanner.py (candle-freshness/regime-
baseline reads)" — about candle data, not this mechanism) and
`trial.py`/`repair_to_trial.py`'s comments about the *reverted* Trial gate.
`check_freshness_disqualification`/`check_per_hypothesis_freshness` are
referenced only from `nero_core/eve/scoring.py` and `nero_core/eve/pipeline.py`
— confirmed via grep, zero hits under `nero_core/research_agent/`.

Adam's web-search channel (`hypothesis_gen.py:976-1019`, `_build_web_record`)
does already stamp per-record `source_url`, `source_tier`,
`paraphrase_confirmed` — this predates CC-1 entirely and was built for a
different purpose (sourcing-transparency/provenance disclosure, per the
"CRITICAL SOURCING RULES" in `_build_web_search_prompt`, `hypothesis_gen.py:888-905`).
It is real per-hypothesis attribution data, structurally similar in shape to
what this directive builds for Eve. **But it is never consulted by any
freshness check** — nothing in `nero_core/research_agent/` ever calls
`check_freshness_disqualification` or an equivalent against it. Adam is
**currently entirely unchecked** by any freshness mechanism.

**CONFIDENCE:** confirmed-from-code (direct grep across
`nero_core/research_agent/`, zero freshness-related hits outside
Trial-gate-reversal comments).

**WHAT SHIPPED:** nothing — report-only, per the directive's own instruction
not to implement anything for Adam under this directive.

---

## 4. Eve instructed to populate it

**FINDING:** two places, both stated neutrally (what the field is for, never
what it triggers):
- `nero_core/eve/tools_defs.py` — `PROPOSE_HYPOTHESIS_TOOL`'s description
  now says: *"include a 'supporting_source_urls' key... this is for
  traceability of which source informed which idea, purely optional, and an
  empty or omitted list is a completely normal, honest answer."*
- `nero_core/eve/session.py` — new `CITATION_BLOCK`, inserted into
  `SYSTEM_PROMPT_TEMPLATE` right after the existing end-of-session
  instruction, before the DSL vocabulary block: *"This is for traceability
  -- so it's later possible to see which source informed which idea -- and
  is entirely optional... Only list a URL a search in this session actually
  returned to you."*

Neither mentions freshness, disqualification, or any consequence — confirmed
by reading both strings directly; no occurrence of "freshness",
"disqualif", "risk", or "penalty" anywhere in either block.

**CONFIDENCE:** confirmed-from-code.

**WHAT SHIPPED:** `nero_core/eve/tools_defs.py` (description edit),
`nero_core/eve/session.py` (new `CITATION_BLOCK` constant + composed into
`SYSTEM_PROMPT_TEMPLATE`). Verified `SYSTEM_PROMPT_TEMPLATE` actually
contains `supporting_source_urls` after composition (direct import check).

---

## 5. Session 1 and the other pre-citation sessions

**FINDING:** all **16** records in `docs/site_data/eve_hypotheses.json` —
spanning **every** committed session, not just Session 1 (Session 0:
`eve-20260803T095520Z-394385c7`, 4 records; Session 0-B:
`eve-20260803T142519Z-718833c9`, 6 records; Session 1:
`eve-20260804T020749Z-4cf6e4c9`, 6 records) — predate this mechanism
entirely. One-time migration `tools/backfill_eve_pre_citation_status.py`
marks every record lacking a `citation_status` key with
`citation_status: "unscoreable_pre_citation"` and a matching
`per_hypothesis_freshness: {"result": "unscoreable_pre_citation", ...}`.
**No `supporting_source_urls` was fabricated** for any of them — the script
never invents that field, only stamps the explicit pre-citation marker;
confirmed by `test_never_fabricates_a_supporting_source_urls_list`.

**Idempotent:** a record that already carries `citation_status` (of any
value) is left untouched — safe to re-run, confirmed by
`test_leaves_a_record_that_already_has_citation_status_untouched` and
`test_idempotent_second_run_marks_nothing`. Running it a second time against
the real file marked 0 records (confirmed live).

**`classify_citation_status` itself can never produce this value** —
`CITATION_STATUS_UNSCOREABLE_PRE_CITATION` exists only for this migration;
`test_classify_citation_status_never_returns_pre_citation` proves the live
classifier never returns it, so a reader can trust that any record showing
this status is genuinely pre-mechanism, never a live classification that
happened to look the same.

**CONFIDENCE:** confirmed-from-data (ran the real migration against the real
file; confirmed 16 records marked, second run marked 0; confirmed via
`RealCommittedDataBackfilledTest` reading the actual committed
`docs/site_data/eve_hypotheses.json` directly, outside any test isolation).

**WHAT SHIPPED:** `tools/backfill_eve_pre_citation_status.py` (new);
`docs/site_data/eve_hypotheses.json` updated in place (16 records marked,
migration already run); provenance note added to
`docs/site_data/eve_session_registry.json`'s
`pre_registration.per_hypothesis_citation_freshness_provenance` field,
mirroring the existing `freshness_gate_reversal_provenance` convention, with
its own regression test
(`test_eve_session_registry.py::test_per_hypothesis_citation_freshness_provenance_is_recorded`).

---

## 6. The incentive problem — named, not discovered later

**The structural weakness, stated plainly:** the proposer (Eve) and the
cited evidence (her own search log) are the same party. If freshness
disqualification ever became binding, Eve would have a direct incentive to
omit a recent source from her citation list. **Unlike fabrication, omission
cannot be caught by validating citations against the search log** — the
validation in item 1 only checks that a *claimed* URL was really searched;
it has no way to detect a URL that *should* have been claimed but wasn't.
The `paraphrase_confirmed` precedent (Adam's web channel) is not fully
analogous: that field gates nothing against the proposer's own interest —
there is no adverse consequence to Adam for a `paraphrase_confirmed: true`
claim, so there's no comparable incentive to misreport it.

**Structural protections that DO exist, confirmed from code:**

1. **Scoring is a strictly separate pass, after the session ends.** Read
   `nero_core/eve/session.py::run_session` in full (lines 454-647): the
   entire turn loop calls only `scoring.classify_testability` (DSL-parse
   check, mid-session, for the pre-submit retry validator) — never
   `check_freshness_disqualification`, `check_per_hypothesis_freshness`, or
   any reference to `citation_status`/`per_hypothesis_freshness` anywhere in
   the file. `nero_core/eve/pipeline.py::run_pipeline` calls
   `session.run_session(...)` to completion (line 293-294) and only *after*
   it returns does it call `scoring.score_all`,
   `apply_freshness_disqualification`,
   `apply_per_hypothesis_freshness` (lines 296-329). Eve never observes a
   freshness or citation-validation outcome within a session — confirmed
   directly from the code path, not inferred.

2. **No freshness/citation-validation flag is fed back into any future
   session's context**, checked across every plausible path:
   - `nero_core/eve/context.py` (`load_context`/`EveContext.as_prompt_text`,
     what every session's first user message is built from) reads only
     `quant_metrics.json` (tracked pairs), `failure_patterns.json`
     (graveyard), and `agent_hypotheses.json` (Adam's history,
     whitelist-field-stripped — `_ADAM_HISTORY_FIELDS`, line 47-50, contains
     no verdict-, freshness-, or citation-related field at all). It has no
     function that even constructs a path to `eve_hypotheses.json` or any
     Eve-scored output.
   - `nero_core.research_agent.hypothesis_gen`'s prompt building
     (`_build_web_search_prompt`) reads `tracked_pairs`,
     `known_hypothesis_names`, `failure_patterns` — confirmed via direct
     grep that `nero_core/research_agent/` contains **zero** imports of
     `nero_core.eve` anywhere (the one textual hit is a comment, not an
     import — `trial.py:88`). Structurally cannot read Eve's scoring output.
   - The graveyard/failure-patterns channel: `failure_patterns.json` is
     written by `nero_core.research_agent.graveyard_distillation`/`pipeline.py`
     — Adam's own machinery, entirely separate from
     `nero_core/eve/pipeline.py`. Neither imports the other.
   - Eve's own write-path allowlist (`nero_core/eve/storage.py:44-62`,
     `_is_allowed_write_path`) structurally limits every write in
     `nero_core/eve/` to exactly 3 paths (`eve_hypotheses.json`,
     `eve_budget_ledger.json`, `eve_sessions/<id>.json`) — none of which
     `context.py` or Adam's prompt-building ever reads.

   **This is currently unlearnable by Eve** — not merely unobserved this
   session, but structurally absent from every path that could carry it
   forward to a future session. This is a real, existing protection, not an
   assumption.

**Standing rule, stated explicitly:** this design is sound *only* while the
flag stays informational. **No future change should route freshness or
citation-validation outcomes back into agent context (Eve's or Adam's)
without first re-opening this incentive question** — doing so would create
exactly the misreporting incentive described above, with no existing
mechanism to detect the omission half of it.

No future change should route freshness or citation-validation outcomes back
into agent context without reopening this incentive analysis. The protection
documented above is real but incidental — nothing in the code was built to
preserve it (it is a byproduct of scoring running after the session and of
`context.py`'s unrelated whitelist, not a deliberate safeguard), so a future
feature that shows Eve her own past results (e.g. a "what happened to my
prior proposals" context block) would silently break it without anyone
having to touch this section at all.

**CONFIDENCE:** confirmed-from-code (full read of `session.py`, `context.py`,
`hypothesis_gen.py`'s prompt builder, `storage.py`'s write allowlist;
direct grep confirming zero `nero_core.eve` imports anywhere under
`nero_core/research_agent/`).

**WHAT SHIPPED:** this analysis, recorded in this report and in
`docs/site_data/eve_session_registry.json`'s new
`per_hypothesis_citation_freshness_provenance.incentive_analysis` field (so
it survives independently of this report file). No code change addresses
the incentive problem itself — it is a structural property of "informational
only," not a bug to fix.

---

## 7. Stays informational — no binding, by any path

**FINDING:** confirmed unchanged:
- `admit_to_trial`'s signature still has no freshness/citation parameter of
  any kind (`inspect.signature` check in
  `SupportingSourceUrlsNeverGatesDslOrTrialTest::test_admit_to_trial_signature_has_no_citation_parameter`,
  passes). The existing `AdmitToTrialNeverConsultsFreshnessTest` in
  `test_trial_admission.py` (asserting no `freshness_disqualified`
  parameter) still passes unmodified.
- `apply_fdr_correction`'s signature has no citation/freshness parameter
  either (`NeverBindingRegressionTest::test_apply_fdr_correction_signature_has_no_citation_parameter`).
  Only `is_self_derivative` exclusion remains — unchanged, confirmed by the
  full `test_eve_scoring_fdr.py` suite passing unmodified.
- Direct proof a `per_hypothesis_freshness: "checked_disqualified"` record
  still fully participates in the FDR family
  (`NeverBindingRegressionTest::test_apply_fdr_correction_ignores_per_hypothesis_freshness_entirely`)
  — `fdr_survives_oos` is populated normally, no
  `excluded_from_fdr_family_reason` appears.
- No recommendation to re-enable binding disqualification anywhere in this
  report or the shipped code/comments — every mention of the possibility is
  framed as "a separate, explicit, deliberate decision," matching the
  standing rule from `3697e75`.

**Bar constants unchanged — test added:**
`ConstantsUncnhangedTest::test_evidence_bar_constants_unchanged` asserts
`MIN_SAMPLE_SIZE == 20`, `TARGET_RESOLVED_TRADES == 30`,
`FAST_MAX_MONTHS == 6.0`, `VIABLE_MAX_MONTHS == 12.0`,
`DEFAULT_FDR_ALPHA == 0.05`, `FRESHNESS_DISQUALIFICATION_WINDOW_DAYS == 30`.
Passes. No file defining any of these constants
(`tools/backtest_statistics.py`, `nero_core/research_agent/frequency_gate.py`,
`nero_core/eve/scoring.py`) was touched by this directive except to append
new, unrelated functions at the end of `scoring.py`.

**CONFIDENCE:** confirmed-from-code, confirmed-from-test.

**WHAT SHIPPED:** no production code changed in `trial.py` or the binding
paths of `scoring.py` (`apply_fdr_correction`, `admit_to_trial`). New
regression tests added as listed above.

---

## 8. Coordination note — `derived_from` field

**FINDING:** grepped the entire codebase for `derived_from` — the only hits
are unrelated test names (`test_repair_lab_chain_record.py`'s
`..._derived_from_4_died_attempts...`,
`test_range_mean_reversion_confirmation.py`'s `..._derived_from_candle_open...`).
**No `derived_from` field exists anywhere on `propose_hypothesis`'s schema or
any hypothesis record shape.** The other directive referenced in this
item's coordination note has **not shipped**.

**CONFIDENCE:** confirmed-from-code (direct grep, zero real hits).

**WHAT SHIPPED:** nothing for that directive (out of scope, per its own
instruction). Flagging here, as requested, so the two can be sequenced: this
directive's changes to `propose_hypothesis`'s schema
(`nero_core/eve/tools_defs.py`) and the DSL-validation path
(`nero_core/eve/hypothesis_shapes.py`) are additive-only (one new optional
field, five new always-present record fields, none of them touching
`structured_entry_rule`/`structured_exit_plan`). A future `derived_from`
addition should be similarly additive and should re-run
`SupportingSourceUrlsNeverGatesDslOrTrialTest`'s pattern for its own field
before shipping, to confirm the two changes don't collide on DSL validity.

---

## Test counts

**Python, targeted:**
- `tests/test_eve_citation_freshness.py` — new file, 29 tests, all pass
  (covers items 1, 2, 5, 7 regression guards).
- `tests/test_eve_session_registry.py` — +1 test
  (`test_per_hypothesis_citation_freshness_provenance_is_recorded`), 10
  tests total, all pass.
- Directly-related existing files re-run unmodified and confirmed still
  passing: `test_eve_freshness_disqualification.py`, `test_trial_admission.py`,
  `test_eve_hypothesis_shapes.py`, `test_eve_scoring_fdr.py`,
  `test_eve_llm_client.py`, `test_eve_session_termination.py`,
  `test_eve_dsl_validator.py` — 139 tests, all pass.

**Full suite, Python** (`python -m unittest discover -s tests`):
- **Before:** 2491 tests, **OK** (0 failures, 0 errors).
- **After:** 2521 tests, **OK** (0 failures, 0 errors). Delta: **+30**,
  reconciling exactly (29 new file + 1 registry test).

**Full suite, website** (`npm test` / jest):
- **Before:** 598 tests, 596 passing, **2 failing** — both in
  `__tests__/siteDataSchema.test.ts` (`failure_patterns.json` missing/undefined
  `fix_rationale` on a fixable entry, and a duplicate-`family` check) —
  **pre-existing, unrelated to this directive** (this directive touched no
  website files and no `failure_patterns.json` content).
- **After:** 598 tests, 596 passing, same 2 pre-existing failures,
  identical failure output. Confirmed this directive's `git diff` touches
  zero files under `website/`.

## Stale-figure check

No figure in this directive was found to be stale. The one number worth
double-checking against real data — "16 existing committed records" implied
by item 5's "across all committed session files" phrasing — was verified
directly against `docs/site_data/eve_hypotheses.json` (16 records, matching
the 4+6+6 split across Session 0 / Session 0-B / Session 1 already on file
in `eve_session_registry.json`), not assumed from memory.
