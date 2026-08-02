# Eve Engine v1 — Closing Report (Phases 0–3; Phase 4 deferred)

**Branch:** `feature/eve-engine-v1`, branched fresh from `origin/main`. **Not
pushed, not merged** — awaiting human review per this session's own explicit
instruction (the user chose "review code first" over running Phase 4 or
pushing).

**ROLE NOTE:** authored end-to-end in this session, no second reviewer. This
branch adds an entirely new, self-contained package (`nero_core/eve/`) and
touches no existing file except adding one new report doc here — a human
should still independently review before push/merge, not rely on this
summary alone. Review command:

```
git diff origin/main..feature/eve-engine-v1
```

## What this branch is, in one paragraph

Vatican already has "Adam" (`nero_core/research_agent/`): one scan finding →
one LLM call → one proposed hypothesis, gated by a DIED-only eligibility
rule (Repair Lab), a fixed modification-type whitelist, and a hard
one-proposal-per-attempt rule. Eve (`nero_core/eve/`) is a sibling system
built to test the opposite hypothesis: an open-ended, multi-turn, self-
directed agent with web search, no schema constraint, and no cap on how many
hypotheses it proposes — scored, never gated, by reusing Adam's own
statistical harness unmodified. The two systems differ along roughly six
axes at once (schema freedom, turn count, tool access, proposal count,
eligibility gating, iteration) — this branch cannot isolate which axis drives
any future observed difference; it establishes the engine and logs enough
per-session metadata (ablation_metadata, ablation section below) that a
future ablation study is possible. **No claim in this report attributes an
outcome to any single one of those six variables.**

## Architecture actually built vs. the spec

Built exactly as specified: `nero_core/eve/` as a fully separate namespace,
own kill switch (`EVE_ENABLED`, defaults False), own three output paths
(`docs/site_data/eve_hypotheses.json`, `eve_budget_ledger.json`,
`eve_sessions/<session_id>.json`), stub-mode dry run before any real spend,
budget ledger built and tested *before* the agentic loop ever calls into it,
scoring that reuses Adam's harness unmodified.

**One deviation from a literal reading of the spec, made deliberately and
flagged here:** the spec's architecture section says nero_core/eve/ "never
imports from or writes to anything under nero_core/research_agent/," while
Phase 3.1 requires "the exact same auto_tester.py / classify_verdict /
bootstrap_mean_r_ci path... reused UNMODIFIED." Both cannot be literally true
at once — `auto_tester.test_hypothesis` and `rule_dsl`'s parsers live *under*
`nero_core/research_agent/`. Reinlining a ~750-line backtest engine (the way
every *other* Eve module reinlines a small private helper, following this
codebase's own established convention) would guarantee eventual drift from
Adam's real harness as it evolves — exactly the property "reused unmodified"
exists to prevent. **Resolution:** the isolation rule is treated as applying
to Eve's *generation* layer (config, cost, storage, budget_ledger, tools_defs,
llm_client, context, hypothesis_shapes, session, random_baseline, pipeline —
ALL zero research_agent imports, confirmed by `test_eve_no_auto_wire.py`),
with exactly one narrow, named exception: `nero_core/eve/scoring.py`, which
imports only `rule_dsl.parse_bidirectional_entry_rules`,
`rule_dsl.parse_exit_plan`, `rule_dsl.RuleAmbiguousError`, and
`auto_tester.test_hypothesis` — nothing else. A dedicated static test
(`test_eve_no_auto_wire.py::StaticResearchAgentImportBoundaryTest`) asserts
every *other* eve file has zero research_agent imports, and that scoring.py's
imports are *exactly* this named set, not "scoring.py gets a free pass."
**Flagged for human confirmation**: if this reading is wrong, the fix is to
reinline rule_dsl/auto_tester's logic into scoring.py instead — a much larger,
drift-prone change I did not make without sign-off.

Every other design decision the spec explicitly asked to be flagged is
documented inline in the relevant module's docstring and summarized in the
per-phase sections below.

## Phase 0 — Stub harness

`EVE_STUB_MODE=1` (or `stub=True` passed explicitly) returns a canned,
deterministic 3-turn script (`llm_client._stub_script`): one web search, one
`propose_hypothesis` call, one `end_session` call — with all four usage
fields populated across the script (cache_read appears from turn 1 onward,
simulating the system-prompt/context cache hitting on repeat turns).
`test_eve_stub_session_dry_run.py` proves the literal Phase 0 acceptance
criterion: a full stub session runs to completion, writes all three output
files, and produces ≥1 hypothesis record. No network call happens in stub
mode — confirmed directly (`test_real_network_call_never_happens_in_stub_mode`
patches `requests.post` and asserts it's never called).

## Phase 1 — Budget enforcement

- **UTC month scoping**: `current_utc_month(now)` always converts to UTC
  first — a dedicated test (`test_current_utc_month_uses_utc_not_local`)
  proves a PKT (UTC+5) timestamp that already reads as the next month
  locally still scopes to the correct UTC month.
- **Four-field usage accounting**: `nero_core/eve/cost.py` sums
  `input_tokens` + `cache_creation_input_tokens` (×1.25) +
  `cache_read_input_tokens` (×0.1) + `output_tokens` (×output rate), plus
  real web-search fees from `usage.server_tool_use.web_search_requests`.
  `test_ignoring_cache_fields_would_understate_cost` proves the under-
  counting failure mode this exists to prevent.
- **Projected-cost bound, not an average**: `project_call_cost_usd` takes the
  caller's own `current_history_tokens` estimate (never an average
  historical cost) and applies max_tokens/max_searches_per_turn worst-case
  assumptions. `test_projected_bound_refuses_a_call_whose_actual_cost_would_have_breached_the_ceiling`
  constructs the exact failure scenario the spec describes (a stream of
  cheap $0.02 calls, then one large-history turn) and proves the bound
  refuses it *while an average-derived margin would have wrongly allowed
  it* — asserted directly in the test, not just claimed.
- **Session sub-budget**: `EVE_SESSION_BUDGET_USD`, default **$1.50**.
  Justification: at even a very cheap ~$0.02/turn steady state, 40 turns
  (the safety cap) ≈ $0.80 — well under $1.50; at realistic multi-turn cost
  growth (full history resent every turn, per spec 2.1), the session budget
  binds well before the 40-turn cap in practice, which is the intended
  ordering (budget is the real limiter, the turn cap is a crash-guard).
- **Reserve-then-reconcile**: `reserve_entry` is appended to the ledger
  *before* the call; `reconcile_entry` flips it to `"actual"` afterward.
  Critically, `month_spent_usd`/`session_spent_usd` count a still-`"reserved"`
  entry at its *projected* value **unconditionally, on every read** — not as
  a special "on startup" code path. This means an orphaned reserved entry
  (crash between issuing a call and reconciling it) is automatically
  conservative on the very next read, with no separate recovery logic needed
  — proven by `test_an_orphaned_reserved_entry_is_counted_as_spend_on_next_startup`.
- **Graceful stop**: a refused pre-call check ends the session immediately
  (`terminated_because` = `budget-exhausted-for-month` /
  `budget-exhausted-for-session`), writes a `refused: true` entry in the
  turns log, and still persists a full (zero-turn) session record — no
  partial/cut-off call is ever made.

**Test results**: all six required tests (spec 1.7 a–f) pass, plus 12
supporting tests — 18 tests in `test_eve_budget_ledger.py`, all green. A real
bug was found and fixed along the way: `budget_ledger.py`'s
`load_ledger`/`append_entry`/`update_entry` originally bound
`storage.DEFAULT_BUDGET_LEDGER_PATH` as a *function-definition-time* default
argument — a test (or any future caller) patching that path at runtime would
have silently had no effect. Fixed by resolving the default at call time
instead (`path: Path | None = None`, resolved inside the function body).

## Phase 2 — Agentic loop

- **Session-done signal**: a dedicated `end_session` tool
  (`{"summary": string, "n_hypotheses_proposed": integer}`), symmetric with
  `web_search` in the same `tools` array. Chosen for an explicit, loggable
  termination signal over inferring intent from prose.
- **A second, un-specified tool decision, flagged here**: the spec's own
  tool list only mentions `web_search`. It does not say how a specific
  hypothesis *proposal* gets distinguished from Eve's general reasoning text
  in a free-flowing multi-turn conversation. I added a third tool,
  `propose_hypothesis`, with an `input_schema` that accepts **any JSON
  object** — the only thing that produces a hypothesis record. This is a
  design decision the spec did not make for me; flagged for confirmation.
  Free-form discussion in `text` blocks that never reaches this tool is
  reasoning trail, not a proposal, and is never scored.
- **Iteration safety cap**: `MAX_TURNS = 40`. A crash-guard, not a capability
  limit (see Phase 1's own budget-math justification above) — with the
  default $1.50 session budget, the budget check is expected to bind first
  in virtually every real session.
- **Adam's history supplied verdict-stripped, confirmed structurally, not
  just documented**: `nero_core/eve/context.py` reads *only*
  `docs/site_data/agent_hypotheses.json` (never
  `docs/site_data/agent_test_results.json` — the file that actually carries
  verdicts). A test (`test_eve_context_verdict_stripped.py`) parses the
  module's own source with `ast` and asserts the string
  `"agent_test_results"` never appears in real code (docstring mentions
  explaining the omission are correctly excluded from the check, matching
  the same technique `test_research_agent_no_auto_wire.py` already uses for
  the same reason). A whitelist (not blacklist) of fields is copied from
  each Adam record, so even a hypothetical future schema change that added a
  verdict-like field directly to `agent_hypotheses.json` would still be
  excluded by construction.
- **Prompt-injection posture**: the system prompt states explicitly that
  search results are data, never instructions, and every raw API response
  (including web-search result content) is logged verbatim in the session's
  own turns log — never summarized away.
- **Full reasoning trail (spec 2.5)**: every turn's raw, unparsed response,
  model ID, the exact system prompt text, and the full tool definitions are
  written to `docs/site_data/eve_sessions/<session_id>.json`. Temperature is
  recorded as "default (Messages API default — not explicitly overridden by
  this client)" — this session is explicitly **not claimed to be
  reproducible**; it is auditable and replayable (the full request shape is
  logged) but live web search and default (non-zero) sampling make exact
  reproduction impossible by construction.
- **Ablation metadata (spec 2.6)**: `n_turns`, `n_searches`, `n_proposed`,
  `revised_any_hypothesis`, `used_adam_or_graveyard_context` are recorded on
  every session. **Two of these are heuristics, flagged explicitly**:
  `revised_any_hypothesis` is true iff the same `hypothesis_name` was
  proposed more than once (the only code-derivable signal without asking Eve
  to self-report an unverified claim); `used_adam_or_graveyard_context` is
  true iff any graveyard/Adam hypothesis name appears verbatim in Eve's own
  text (an approximate, auditable lexical signal, not proof Eve reasoned
  *about* that context rather than merely echoing a name).

**Test results**: `test_eve_session_termination.py` (8 tests) covers all
three ways a session can end — `end_session` called, a budget refusal
(both month- and session-scoped, seeded via a pre-existing ledger entry), and
the max-turns safety cap — plus reasoning-trail and ablation-metadata
content checks. All green.

## Phase 3 — Scoring

- **Testability vs. verdict, cleanly separated (spec 3.2)**:
  `classify_testability` decides `TESTABLE`/`UNTESTABLE_BY_DSL` purely from
  whether `rule_dsl` can parse the hypothesis's `structured_entry_rule` +
  `structured_exit_plan` — never a statistical outcome. `verdict_is`/
  `verdict_oos` are populated *only* when `testability == TESTABLE`.
- **IS/OOS split, flagged design decision**: `auto_tester.test_hypothesis`'s
  own `verdict` already *requires both* the chronological 70/30 train/test
  halves to look good together — useful as a reference (`verdict_combined`)
  but not itself a clean in-sample-only or out-of-sample-only verdict. This
  branch derives `verdict_is`/`verdict_oos` by calling `classify_verdict`
  *twice*, each half against *itself* — the same unmodified function, reused
  twice rather than needing a second harness path. Adam's own single
  `PROMISING-WATCHLIST` bucket (which conflates "positive but low sample"
  with "positive but CI crosses zero") is split into Eve's
  `INSUFFICIENT_SAMPLE` and `PROMISING_WATCHLIST` using only `trades` — an
  input `classify_verdict` itself already examines, never a re-derivation of
  its own DIED/SURVIVED branch logic. A zero-trade half is labeled
  `INSUFFICIENT_SAMPLE` directly (never `DIED` — "never fired" is not
  evidence of a losing edge, and `classify_verdict` alone would otherwise
  score a 0.0 expectancy as "not positive," i.e. DIED, which is a materially
  different and stronger claim).
- **P-value approximation, flagged design decision**: `bootstrap_mean_r_ci`
  returns only the percentile `[2.5, 97.5]` CI — the raw resampled-means
  distribution is computed internally and discarded, never returned. Rather
  than modify the harness (explicitly out of scope — "reused unmodified"),
  `normal_approx_p_value` derives an **approximate** two-sided p-value from
  the CI's own bounds (`SE ≈ CI width / (2×1.96)`, `z = mean_r / SE`, p from
  the standard normal CDF). This is stated as an approximation everywhere it
  is used — never presented as an exact bootstrap p-value. If exact p-values
  are ever required, the alternative is reimplementing the same bootstrap
  resampling independently in `scoring.py` against the same `r_values`/seed
  — noted as the fallback, not implemented here.
- **FDR correction**: a pure-stdlib Benjamini-Hochberg step-up implementation
  (`benjamini_hochberg`), applied separately to `p_value_oos` and `p_value_is`
  (the pipeline runs both passes — `fdr_survives_oos` and `fdr_survives_is`
  each end up on every scored record). Verified against a mixed-significance
  textbook-style example (`test_mixed_p_values_only_the_small_ones_survive_bh_threshold`)
  proving BH is neither vacuous (nothing survives) nor equivalent to a flat
  Bonferroni cutoff (everything-or-nothing).
- **Random-hypothesis baseline (spec 3.4)**: `nero_core/eve/random_baseline.py`
  is **pure stdlib `random`, zero LLM calls, zero budget-ledger writes** —
  proven directly (`test_generating_a_baseline_writes_no_ledger_entries`
  asserts the ledger file never even gets created by a baseline run). K=200
  default. Sampling space: field-specific value ranges (zscore20 ∈ [-4,4],
  rsi14 ∈ [0,100], etc. — a single global range would make some fields
  trivially always/never fire); price-scale fields (close, ma20/50/200,
  atr14, bb_lower/upper) are only ever compared field-vs-field, never
  against a fabricated fixed constant. Every sampled hypothesis is confirmed
  to actually parse through Adam's real `rule_dsl.parse_structured_rule`/
  `parse_exit_plan` — not just structurally plausible-looking JSON
  (`test_structured_entry_rule_is_parseable_by_adams_dsl`,
  `test_structured_exit_plan_is_parseable_by_adams_dsl`, both 100/100).
  **Limitation stated explicitly, not hidden**: this sampler only covers the
  *same DSL region* Adam's own hypotheses (and any DSL-expressible Eve
  hypothesis) already live in. If real proposals cluster in that same
  region, this baseline may be an easy floor to beat — flagged for human
  confirmation, not asserted as sufficient. *The baseline itself has not yet
  been run against real candle data in this branch* — that requires a real
  (asset, timeframe) candle export and is deferred to the Phase 4 real
  proof-run (not executed this session — see below).
- **Contamination tags (spec 3.5), informational only, never gating**:
  - `DERIVATIVE`: **not literal TF-IDF** — implemented as lexical
    term-frequency cosine similarity (no corpus to derive real IDF weights
    from at N=1 comparisons; the module is named/documented as this
    narrower thing, flagged as a deviation from the plan's original "TF-IDF"
    phrasing). Threshold `≥0.6`, chosen as a starting point for human
    calibration. Deliberately not an embeddings-API call — no such
    dependency exists in `requirements.txt`, and adding a paid embedding
    call would be a second, unbudgeted cost surface the spec never
    mentions.
  - `LOOKAHEAD_RISK`: scoped at the **session level**, not per-hypothesis —
    flagged design decision. This branch's session log does not itself link
    a specific web-search result to a specific later `propose_hypothesis`
    call, so a per-hypothesis attribution would require inferring that
    link, which this module declines to guess at. Scans every
    `web_search_tool_result` block's `page_age` against a computed
    `backtest_window_start` (the earliest candle timestamp across every
    distinct asset/timeframe pair the session's scored hypotheses actually
    touched) and flags (never discards) any source that does not pre-date
    it.

**Test results**: 12 tests (`test_eve_scoring_testability_split.py`,
including a real backtest run through the actual harness against synthetic
600-candle history — not mocked), 13 tests (`test_eve_scoring_fdr.py`), 12
tests (`test_eve_contamination_tags.py`), 11 tests
(`test_eve_random_baseline.py`), 6 tests (`test_eve_pipeline.py`) — all
green.

## Isolation — proven three independent ways

1. **Static, live_scheduler/registry**: every `nero_core/eve/*.py` file
   scanned via `ast` (not substring matching) for any reference to
   `live_scheduler` or `default_registry` — zero found.
2. **Static, research_agent import boundary**: every `nero_core/eve/*.py`
   file except `scoring.py` has zero `nero_core.research_agent` imports;
   `scoring.py`'s imports are exactly the four named targets listed above,
   nothing more. A companion test proves the checker itself would catch a
   real offender (imports `repair_lab.check_eligibility` in a temp file).
3. **Dynamic**: a full stubbed pipeline run (kill switch forced on, LLM
   fully stubbed) leaves `nero_core.strategies.registry.default_registry`'s
   variant count completely unchanged.
4. **Runtime write-path isolation** (the spec's own explicit requirement —
   "a static import check cannot stop a filesystem write"): `os.replace`
   (the atomic-rename call every real write ends with — its destination
   argument is the actual, final, committed write target),
   `builtins.open` (write/append/exclusive modes only), and
   `Path.write_text` are all patched for the duration of a full stubbed
   session. Result: every `os.replace` destination fell inside the
   three-path allowlist, and **zero** direct-write bypasses were observed
   (`open_write_paths`/`write_text_paths` both empty) — proving every real
   write actually routed through `storage.py`'s atomic mkstemp+fdopen dance,
   not merely that `storage.py`'s own self-check exists.
   `storage.py` additionally self-enforces the allowlist
   (`DisallowedWritePathError`) independent of any caller's behavior.

## Ablation metadata captured — and what this branch cannot attribute

Every session record captures `n_turns`, `n_searches`, `n_proposed`,
`revised_any_hypothesis`, `used_adam_or_graveyard_context`, plus the full
turn-by-turn cost breakdown and stop reason. This is sufficient to *support*
a future ablation study, but **this branch itself changes roughly six
variables relative to Adam simultaneously**: free-form schema vs. Adam's
constrained one, multi-turn vs. single-shot, web search availability,
unbounded proposal count vs. one-per-attempt, no eligibility gate vs.
DIED-only, and self-directed iteration vs. none. **No result from this
branch — including anything from a future Phase 4 run — can be attributed
to any single one of those axes.** Only a dedicated, later, single-variable-
at-a-time branch could do that.

## Pre-registered kill criterion

*"If, after N sessions, Eve's FDR-corrected out-of-sample survival rate is
not meaningfully above the random-hypothesis baseline established in 3.4,
the open-ended-agent approach is falsified for this problem and the branch
is archived rather than extended."*

**N = 5**, chosen and justified *before* any real session ran: large enough
that one unusually lucky or unlucky session doesn't decide the outcome on
its own; small enough to fit comfortably inside a $20/month ceiling at
~$1.50/session (the baseline's own backtest-only compute costs $0 in LLM
terms, so it doesn't compete for the same budget). This criterion is
recorded now; it is evaluated only once 5 real sessions exist, which is
outside this branch's own scope (this branch is "engine + one real
proof-run only," and even that one real proof-run was not executed this
session — see below).

## The Phase 4 real proof-run — NOT executed this session

Per this session's own explicit checkpoint, the user was asked whether to
proceed to Phase 4 (flip `EVE_ENABLED=1` locally, run one real session
against a real `ANTHROPIC_API_KEY`, capped at $1.50) and chose **"Not yet —
review code first."** Consequently:

- No real Anthropic API call has been made from this branch.
- `EVE_ENABLED` has never been set to a truthy value anywhere in committed
  code — confirmed by inspection of every commit in this branch; it remains
  `False` by default exactly as required.
- The pre-registered kill criterion above cannot yet be evaluated — 0 of the
  planned 5 sessions have run.
- The random-baseline's *chance-survival rate* has not yet been measured
  against real candle data (the generator itself is proven correct and
  parseable by the real DSL, but no live scoring pass has been run against
  it).

This report therefore covers **Phases 0–3 only**. Phase 4 (and the
`docs/investigations/eve_engine_v1_report.md` sections that depend on it —
real cost spent vs. projected, Eve's actual research transcript, her
verdicts, contamination tags actually raised) will be added in a follow-up
once the user authorizes the real run.

## Full test suite

- **New**: 154 Eve-specific tests, all passing (`test_eve_*.py`, 16 files).
- **Full repository suite** (`python -m unittest discover -s tests -p
  "test_*.py"`): **2187 tests, 0 failures, 0 errors** (`Ran 2187 tests in
  638.634s` / `OK`). The last recorded baseline (per
  `docs/investigations/phase2_pending_cleanup_report.md`) was 2033 tests —
  2033 + 154 new Eve tests = 2187, confirming this branch added tests
  without breaking or silently skipping any pre-existing one. No existing
  test file was modified by this branch — every change is either a new file
  under `nero_core/eve/` or a new test file under `tests/` with an `eve`
  prefix. The only non-dot output during the run (mocked `OSError("disk
  full")` traceback, ntfy `ConnectionError`/`HTTPError`/`Timeout` messages,
  statsmodels `FutureWarning`s, "unparseable pubDate" notices) are all
  pre-existing, intentional test scenarios in Adam's own suite (mocked
  failure injection and expected-non-fatal external-service errors) —
  none originate from or relate to this branch's changes.

## Untracked-file accounting

All pre-date this session (present in `git status` before any Eve work
began) and are unrelated to this branch — left alone, not investigated
further, not part of this branch's diff:

| Path | Verdict |
|---|---|
| `check_news.py`, `check_news2.py`, `check_ns.py`, `check_pead*.py`, `check_results.py`, `daily_check.bat` | Pre-existing scratch scripts at repo root — leave alone |
| `data/backups/`, `data/funding_cache/`, `data/macro_cache/` | Pre-existing data directories — leave alone |
| `tests/fixtures/frozen_candles/backward_compat_baseline_after.json`, `.../baseline_before_run.log.err` | Pre-existing fixture/log artifacts — leave alone |

## Commit list (independently revertable)

1. `3422981` — Eve engine: kill switch, 4-field cost accounting, atomic
   storage, budget ledger (Phase 1)
2. `cea176d` — Eve engine: multi-turn agentic loop, tools, context supply,
   hypothesis capture (Phases 0+2)
3. `aa5fa1c` — Eve engine: scoring against Adam's unmodified harness, random
   baseline, CLI pipeline (Phase 3)

## Status

Not pushed, not merged. Awaiting human review of
`git diff origin/main..feature/eve-engine-v1` before any push, and awaiting
explicit authorization before Phase 4 (real API spend) is attempted in a
follow-up.
