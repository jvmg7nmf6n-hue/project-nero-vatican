# Eve Engine v1 — Closing Report (Phases 0–3; Phase 4 deferred)

**Updated (follow-up session, harness validation and fixes):** see
"Follow-up session" below for the real K=200 random-baseline run against
BTC/4h, the p-value bug it exposed and fixed, the candle-cap root cause and
research-export split, the positive control proving the harness can say
SURVIVED, the silent-fallback trap closed, and Adam's 401
observability/ledger gaps addressed. The Phases 0–3 content below this
notice is unchanged from the original closing report.

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

> **CORRECTION (2026-08-03), appended — original text above left
> byte-identical, never mutated:** the **N = 5** value above is
> **superseded by the 3 Aug 2026 pre-registration, which fixes N = 8**.
> This is not a silent overwrite: the original reasoning above predates
> that pre-registration and was based on the same $1.50/session budget
> assumption, but Session 0's real spend came in at **$0.71**, roughly
> half the $1.50 planning figure (prompt caching working as designed) —
> at that real cost, roughly 28 sessions fit inside the $20/month ceiling,
> not 13, so the original "small enough to fit the budget" constraint that
> justified capping N at 5 no longer binds. 8 sessions still fits
> comfortably and gives a firmer result than 5 (less exposure to one
> unusually lucky or unlucky session deciding the outcome). This
> reconciliation was made and recorded here **before any countable
> session had run** under the corrected N = 8 bar — see the "Session 0"
> section below for why Session 0 itself does not count as one of the 8,
> and `docs/site_data/eve_session_registry.json` for the same correction
> recorded machine-readably, cross-referenced to this note.

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

## Follow-up session — random baseline run, harness validation, and fixes

Everything below happened in a later session, still on this same branch,
still with `EVE_ENABLED` never set to a truthy value anywhere in committed
code and still with zero real Anthropic API calls made from Eve. This work
answers the question the closing report above explicitly left open: "has the
random baseline actually been run against real candle data yet?"

### 1. The 200-row display export was silently invalidating every backtest

`nero_core.execution.export_candle_data.export_candle_data` truncates to
`CANDLE_COUNT = 200` rows via `.tail(CANDLE_COUNT)` — correct and sufficient
for the website's own chart display, the only thing it was ever built for.
Every backtest in this project (Adam's `auto_tester.test_hypothesis`, and by
extension Eve's `scoring.py`, which reuses it unmodified) was reading that
same 200-row file, because no separate export existed. Two consequences,
both real, both silent until measured directly:

- **`ma200` was NaN everywhere except the very last row.** `ma200` needs 200
  prior closes to produce even one value — at exactly 200 rows total, that
  leaves exactly 1 non-NaN row out of 200 (0.5%). Any hypothesis whose entry
  or exit condition touches `ma200` (or is gated by an ATR/RSI/z-score column
  still inside its own warmup window on a 200-row frame) was structurally
  unable to fire on almost the entire history it was being "tested" against.
- **No IS/OOS split had enough real history to be meaningful.** 200 candles
  split 70/30 chronologically (`tools.backtest_train_test_split.
  split_chronological`) leaves ~140 training candles and ~60 test candles —
  nowhere near enough for most hypotheses to ever reach `MIN_SAMPLE_SIZE =
  20` trades on both halves, the bar `classify_verdict` requires for
  `SURVIVED`.

**Fix (commit `5dd51a0`):** a new, separate `export_research_candle_data`
(`RESEARCH_CANDLE_COUNT = 4400`, "2+ years of 4h candles to start" —
`365.25 * 2 * 6 ≈ 4383`) writes to `docs/research_data/candles/`, a directory
structurally unreachable from the website's own hardcoded
`docs/site_data`-based fetch path, so it can never bloat or be accidentally
served by the site. The website's own 200-row export is completely
untouched — same `CANDLE_COUNT`, same output directory, same cadence. A real
export was run for BTC/4h: **4400 candles, 2024-07-30 to 2026-08-02 (2.01
years), 748KB** versus the display export's 33KB for the same pair. Against
this export, `ma200` is alive across **4201/4400 rows (95.5%)**, versus
**1/200 (0.5%)** before.

### 2. The p-value estimator was fabricating significance from single trades

Running the K=200 random-hypothesis baseline (`nero_core.eve.random_
baseline`, pure stdlib, zero LLM calls, zero budget-ledger writes) against
the real BTC/4h research export exposed a live bug (commit `a0771c4`):
`normal_approx_p_value`'s zero-standard-error fallback returned `p=0.0`
(maximally "significant") for any single-trade half, because bootstrap
resampling on `n=1` always redraws the same value, collapsing the CI to zero
width. **28 of 40 OOS p-values in that run "survived" Benjamini-Hochberg FDR
correction despite every one of them having a verdict of
`INSUFFICIENT_SAMPLE`** — a fabricated signal, not a real one.

Fixed with two independent, additive guards, both failing toward "no
p-value" rather than toward significance — neither touches `classify_verdict`
or `MIN_SAMPLE_SIZE`, and `verdict_is`/`verdict_oos`/`verdict_combined` are
computed entirely independently of any p-value:

1. `normal_approx_p_value` now returns `None` (never `0.0`/`1.0`) whenever
   the CI's implied standard error is zero or numerically indistinguishable
   from zero (epsilon `1e-9`), regardless of which half or how many trades
   produced it.
2. `score_hypothesis` additionally nulls `p_value_is`/`p_value_oos` outright
   for any half below `MIN_SAMPLE_SIZE` trades — even a half with a
   non-degenerate CI is still underpowered by this project's own sample-size
   bar. This is what excludes an underpowered hypothesis from the FDR family
   entirely.

### 3. Byte-identical reproduction check

Before trusting the baseline numbers below, the K=200 run was reproduced —
same seed, same export, same unmodified harness — and the two runs' outputs
compared byte-for-byte identical. This rules out measurement-script
artifacts (a non-deterministic ordering, an uncontrolled random source, a
stale cached file) as an explanation for the results; the numbers reported
here are reproducible, not a one-off.

### 4. Random-baseline result: a floor near zero, but never claimed as exactly zero

**0 of 200 randomly-sampled DSL-expressible hypotheses reached `SURVIVED`**
against the real BTC/4h research export, run through the completely
unmodified harness (same `auto_tester.test_hypothesis`, same
`classify_verdict`, same `MIN_SAMPLE_SIZE`, same frequency gate, same
`split_chronological`). Stated precisely, per this project's own statistical
discipline: the chance-survival rate is **below ~1.5% (95% upper bound, rule
of three on 0 events in 200 trials)** — **never a flat 0%.** This distinction
matters operationally: if a future real Eve session produces, say, 1
`SURVIVED` out of 40 real proposals, that is 2.5% and is **not** clear of a
1.5% ceiling — the pre-registered kill criterion (N=5 sessions, see above)
must be evaluated against this actual bound, not against an unstated
assumption of zero.

**The single most important empirical result of this run, recorded
prominently: all 17 in-sample `PROMISING_WATCHLIST` candidates died out of
sample — 17/17.** Every one of the 17 randomly-sampled hypotheses that
looked positive on the in-sample half failed to hold up out-of-sample. This
independently validates this project's own standing rule that in-sample
results are never evidence on their own — it is not a claim specific to
Eve's future real hypotheses, it is a demonstration of the base rate for
*any* DSL-expressible hypothesis in this same search space, random or not.

Together, items 1–4 answer the open question the original closing report
left unresolved: the random baseline's chance-survival rate has now been
measured against real candle data, is reproducible, and rejects (does not
`SURVIVED`) the overwhelming majority of random garbage — establishing
**specificity**. It does not, on its own, establish that the harness can
recognize a real edge when one exists — that gap is closed by item 5.

### 5. Positive control: proving the harness can say SURVIVED, not just DIED

A harness that returns `DIED` unconditionally for everything would score
identically to the real harness on the random baseline above — 0/200 either
way. To rule that out, this session added a permanent regression test
(`tests/test_research_agent_positive_control.py`, commit `ed19cac`): a
synthetic OHLCV series with a deliberately embedded, repeating, exploitable
shock-down/rally-up pattern, run through the same completely unmodified
harness. Result: **`SURVIVED`**, comfortably clearing every gate —

| | trades | expectancy_r | CI crosses zero |
|---|---|---|---|
| in-sample | 93 | +1.77R | no |
| out-of-sample | 39 | +1.76R | no |

both trade counts well above `MIN_SAMPLE_SIZE = 20`, frequency classified
`FAST`. This was a hard gate for the session: had it failed, every `DIED`
verdict the harness has ever produced — including the random baseline's
0/200 above — would have been uninformative, and the plan was to stop and
report rather than adjust any threshold to force a pass. It passed on the
first constructed pattern; no threshold, `classify_verdict`, `MIN_SAMPLE_
SIZE`, or the frequency gate was touched to make it do so.

### 6. Closing the silent-fallback trap: the asset-universe rule

The research export above covers **BTC/4h only** — every other tracked pair
(GOLD, EURUSD, AAPL, and 28 others) still has only a 200-row site export.
Eve's own `default_candles_provider` (`nero_core/eve/pipeline.py`) checked
the research export first but **silently fell back** to the 200-row site
export for any pair without one — no error, no warning, indistinguishable
from a real result. Scoring GOLD or EURUSD would have produced a confident-
looking verdict on exactly the data items 1–2 above just proved is
meaningless for this purpose — the same failure class as the 401
observability gap in item 7.

**Fixed (commit `4ea1263`):** `default_candles_provider` now raises
`scoring.DataSourceRefusedError` — refuses, never silently substitutes — for
any `(asset, timeframe)` pair outside a new, explicit
`APPROVED_RESEARCH_UNIVERSE` (currently `{("BTC", "4h")}`), or one inside it
whose research export file is missing on disk. `score_hypothesis` catches
the refusal and tags the record `candle_data_source="refused"` instead of a
null verdict indistinguishable from "no data existed anywhere"; on success,
every scored record now carries `candle_data_source`/`candle_row_count` so
what was actually used is auditable per-record.

**Standing rule, documented at `APPROVED_RESEARCH_UNIVERSE`:** no `(asset,
timeframe)` pair enters Eve's universe until it has **both** (i) its own
full-history research export, **and** (ii) its own random-hypothesis
baseline computed against that same export — a baseline from one asset does
not transfer to another (different volatility, trend character, cost
structure). BTC/4h is the only pair with both today. SOL and PAXG are the
natural next two (also Binance-backed, can reach the same 2+ year research
window) but are **deliberately not added** — extending this set is a human
decision made after running a fresh export + baseline for that specific
pair, never inferred from which export files happen to exist on disk. The
other 29 pairs are lower priority and several are constrained by Yahoo's
~730-day intraday limit. Every session going forward should record its
asset count alongside `n_proposed` for multiplicity accounting — adding
pairs multiplies the search space, and every added pair raises the chance of
a lucky `SURVIVED` by chance alone.

### 7. Adam's 401 observability and budget-ledger gaps

Two related gaps, addressed together:

- **Website observability (commit `4a6c4cf`):** `nero_core.research_agent.
  performance` already writes `status` (`disabled`/`error`/`clean`) and
  `errors` (phase/context/message) to every run entry (commit `8204f9e`,
  pre-dating this session), but the website never read either field —
  `AgentPerformanceRun` didn't declare them, and `ResearchAgentPanel` never
  rendered `runs[]` at all. A run with `llm_calls_made=3` and no failure
  indicator looked identical to a clean one — worse than a blank panel,
  since it asserts something untrue. Fixed: the panel now has a "Recent
  runs" section with a status badge per run, and an `error` run gets a
  visibly distinct red-bordered card listing every error's phase/context/
  message.
- **Historical record correction (commit `fdae2b5`):** `docs/site_data/
  agent_performance.json`'s two 2026-07-29 run entries pre-date `status`/
  `errors` entirely (added in `8204f9e`, after both of these runs).
  **Neither entry was edited** — editing an audit record after the fact is
  exactly the failure this correction mechanism exists to prevent. Instead,
  a `corrections[]` array was appended, citing the actual commits that
  document what happened: `runs[0]` (all-zero) per commit `b3361b4`,
  `api_key=""` was passed deliberately that session (a prior key-exposure
  incident, since rotated) — `inferred_status=clean`. `runs[1]`
  (`llm_calls_made=3`, `total_llm_cost_usd=0.0`) per commit `4189f6b`,
  "failed with 401 Unauthorized on all 3 calls" — `inferred_status=error`,
  exactly the dangerous shape this whole exercise is about: 3 calls made,
  $0 spent, nothing flagging the failure.
- **Eve's budget ledger, the same failure class one layer down (commit
  `a9a4c96`):** before this fix, `session.run_session` appended a
  `"reserved"` ledger entry before every LLM call, then called `llm_client.
  call_turn`, which did `response.raise_for_status()` with no `try`/`except`
  anywhere above it — any non-2xx response, including a 401, raised
  uncaught and crashed the session with that turn's reservation stuck at
  `status="reserved"` forever. Per the ledger's own conservative-by-design
  read path, a still-`"reserved"` entry counts as spend at its *projected*
  value on every subsequent read, indefinitely — correct for a genuine crash
  mid-call (outcome truly unknown), wrong for a 401/403/429, which Anthropic
  never bills (confirmed $0, not estimated) and which never reached the
  model at all. Repeated auth failures would each leave one phantom
  reserved-forever entry, burning real budget ceiling on calls that spent
  nothing. **Fix:** `llm_client.call_turn` now raises a distinct
  `RejectedBeforeTokenProcessingError` for exactly 401/403/429 (every other
  status code is untouched, staying in the conservative "unknown outcome"
  bucket); `session.run_session` catches it, calls `budget_ledger.
  release_entry` (a new third status, `"released"`, counted as exactly
  `$0.0`, distinct from both `"reserved"` and `"actual"`), and terminates
  the session immediately rather than repeating the same doomed call on
  every remaining turn — mirroring the precedent Adam already set for
  itself in commit `4189f6b`.

### 8. What remains explicitly unverified

- **Adam has never scored a hypothesis.** Every real Adam run so far (`docs/
  research_agent_closing_report.md`, `docs/research_agent_real_run_
  followup.md`) either made zero LLM calls (`api_key=""`, deliberate) or hit
  401 on all 3 calls — no hypothesis has ever reached `auto_tester.test_
  hypothesis` from a real Adam session.
- **Adam's own `research_agent/pipeline.py` `default_candles_provider` still
  reads only the 200-row site export** — deliberately left unchanged this
  session (flagged for separate confirmation, per Phase 3's own design
  note). It must be pointed at a research export before its first real run,
  for the exact reason item 1 above documents — otherwise its debut results
  would be as meaningless as scoring GOLD against the site export was, and
  any future Adam-vs-Eve comparison would silently be reading two different
  datasets.
- The pre-registered kill criterion (N=5 real Eve sessions) still cannot be
  evaluated — 0 of the planned 5 have run; Phase 4 itself remains
  unauthorized and unexecuted.

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

**Follow-up session update:** full repository suite (`python -m unittest
discover -s tests -p "test_*.py"`) now stands at **2240 tests, 0 failures, 0
errors** (`Ran 2240 tests in 382.112s` / `OK`) — up from the 2187 recorded
above, +53 net new tests this session (positive control, silent-fallback
refusal, website status/errors, the correction-record regression test, and
the 401/403/429 budget-ledger fix). Unlike Phases 0–3, this follow-up *did*
modify existing test files where the fix it was proving lived in existing
code (`tests/test_eve_pipeline.py`, `tests/test_eve_budget_ledger.py`,
`tests/test_eve_llm_client.py`, `tests/test_eve_session_termination.py`) —
each modification is a same-commit companion to the source change it tests,
per the rails this follow-up session ran under (every fix needs a test
before it is considered done). Two entirely new test files were added:
`tests/test_research_agent_positive_control.py` and `tests/test_agent_
performance_correction_record.py`.

## Untracked-file accounting

All pre-date this session (present in `git status` before any Eve work
began) and are unrelated to this branch — left alone, not investigated
further, not part of this branch's diff. Reconfirmed unchanged at the end of
the follow-up session (identical `git status` output before and after):

| Path | Verdict |
|---|---|
| `check_news.py`, `check_news2.py`, `check_ns.py`, `check_pead.py`, `check_pead2.py`, `check_pead3.py`, `check_pead4.py`, `check_pead_logs.py`, `check_pead_status.py`, `check_results.py`, `daily_check.bat` | Pre-existing scratch scripts at repo root — leave alone |
| `data/backups/`, `data/funding_cache/`, `data/macro_cache/` | Pre-existing data directories — leave alone |
| `tests/fixtures/frozen_candles/backward_compat_baseline_after.json`, `.../baseline_before_run.log.err` | Pre-existing fixture/log artifacts (Adam's own Task 3 backward-compat regression fixture, commit `50d3b09`) — leave alone |

## Commit list (independently revertable)

1. `3422981` — Eve engine: kill switch, 4-field cost accounting, atomic
   storage, budget ledger (Phase 1)
2. `cea176d` — Eve engine: multi-turn agentic loop, tools, context supply,
   hypothesis capture (Phases 0+2)
3. `aa5fa1c` — Eve engine: scoring against Adam's unmodified harness, random
   baseline, CLI pipeline (Phase 3)
4. `a0771c4` — Fix p-value estimator: never fabricate significance from
   degenerate/underpowered samples
5. `5dd51a0` — Add full-history research candle export, split from the
   website's 200-row display export
6. `ed19cac` — Add positive control: prove the harness can say SURVIVED,
   not just DIED
7. `4ea1263` — Close the silent-fallback trap: refuse, don't degrade,
   outside BTC/4h
8. `4a6c4cf` — Surface run status/errors on the website's
   ResearchAgentPanel
9. `fdae2b5` — Append correction records for the two pre-instrumentation
   2026-07-29 runs
10. `a9a4c96` — Eve budget ledger: release (not reserve-forever) a
    401/403/429 rejection

## Status

Not pushed, not merged. Awaiting human review of
`git diff origin/main..feature/eve-engine-v1` before any push, and awaiting
explicit authorization before Phase 4 (real API spend) is attempted in a
follow-up.

**Follow-up session status (unchanged in kind, more evidence behind it):**
still not pushed, not merged, `EVE_ENABLED` still never set to a truthy
value anywhere in committed code, zero real Anthropic API calls made from
Eve. What changed this session is confidence in the harness itself: the
random baseline has now been run against real candle data and is
reproducible (below ~1.5% chance-survival, 17/17 in-sample
`PROMISING_WATCHLIST` candidates died OOS), the harness has been proven able
to say `SURVIVED` and not just `DIED` (the positive control), the silent
200-row-fallback failure mode is closed for every pair outside BTC/4h, and
Adam's own 401/observability gaps — found via real incidents, not
hypothetically — are fixed one layer down in Eve's budget ledger before
Phase 4 could hit the identical failure for real money. Phase 4 itself
remains unauthorized and unexecuted; the pre-registered kill criterion
(N=5 real sessions) still cannot be evaluated.

**Second follow-up session:** see `docs/investigations/
live_strategy_backtest_and_universe_expansion_report.md` for backtesting
the two live BTC `RANGE_MEAN_REVERSION` variants against real multi-year
history (both DIED in-sample), Adam being pointed at the research export
with the same refusal discipline Eve has, the pre-registered expansion of
`APPROVED_RESEARCH_UNIVERSE` to BTC/ETH/SOL/PAXG (each with its own export
and K=200 baseline, 0/200 SURVIVED every time), and a full Phase 4
readiness check. Phase 4 remains unauthorized and unexecuted.

## Third follow-up session: Session 0, and the DSL vocabulary spec defect (2026-08-03)

Phase 4 (real API spend) was subsequently authorized. This section covers
what happened on the first real (non-stub) multi-turn session that actually
ran to completion, why its result does not count toward the pre-registered
bar, and the fix that followed.

### The pre-registration, verbatim

The following is copied verbatim from the instruction that authorized this
round of work, dated 2026-08-03, written *before* this section's own fix or
Session 0's result were known to the user giving it:

> Eve exists to answer one question: does an open-ended, multi-turn agent
> generate better trading hypotheses than Adam's single-shot, constrained
> approach? To keep that comparison honest, a pre-registration was written
> and dated 3 Aug 2026, BEFORE any Eve result existed:
>
> - random-hypothesis baseline: chance survival <1.5%
> - Eve must clear: 5% OOS survival, FDR-corrected, across the full
>   cross-asset family
> - 8 Eve sessions + 8 Adam runs (~$14)
> - kill criterion: if Eve does not clear 5% after 8 sessions, the
>   open-ended agent approach is falsified and the branch is archived
>
> Those numbers do not move. If a result lands below the bar it gets
> reported as a miss.

**Reconciled (2026-08-03):** this same file's own earlier "Pre-registered
kill criterion" section (above) recorded **N = 5** sessions; this
instruction states **N = 8**. Confirmed authoritative: **N = 8**, per the 3
Aug 2026 pre-registration, which post-dates and supersedes the original N =
5 figure. See the correction note appended directly under the original N =
5 text above (not deleted — the original reasoning is left byte-identical,
per this project's own append-don't-overwrite discipline for audit
records). The `5%` OOS-survival bar and the `<1.5%` chance-survival baseline
were never in dispute — only the session count. `docs/site_data/
eve_session_registry.json`'s `pre_registration` field is updated to N = 8
with the same provenance note. This reconciliation was made, and recorded
here, before any countable session had run.

### What happened in Session 0 (`eve-20260803T095520Z-394385c7`)

Mechanically, everything worked: preflight passed, budget enforcement held,
the loop ran 5 turns with 5 web searches, ntfy fired, and real spend came in
at **$0.7129** against a $1.49 projection (prompt caching working as
designed — roughly 28 sessions fit in the $20 month, not 13).

Eve's own reasoning was genuine, not templated. She read the graveyard's 13
failure patterns, searched real research, and justified each new idea
against the specific prior failure it needed to avoid. She dropped one idea
herself after concluding it was not DSL-expressible.

But all 4 hypotheses came back `UNTESTABLE_BY_DSL` — and the cause was
found, which is the important part:

- 3 used `"compare_to"` where the parser requires `"compare_to_field"`.
- 1 used a nested `{"stop_loss": {"type": "atr_multiple", ...}}` where the
  parser requires a flat `stop_atr_multiple`.

The DSL supported every mechanism she proposed. These failed on **key
naming**, not on merit. She was actively trying to conform — her own words
in turn 1: *"I should simplify this to fit the actual DSL fields cleanly...
avoid inventing unsupported operators."*

### Why this is a spec defect, not an Eve result

The original spec deliberately withheld Adam's schema so Eve would think
freely rather than fill in a form. That intent was correct. The execution
was too strict: withholding the **vocabulary** is different from withholding
the **constraints**. She needed a dictionary, not permission. That is an
error in this project's own spec, not a finding about Eve's capability.

### Decision 1 — Session 0 does not count toward the 8

Recorded explicitly as **"Session 0 — proof run"**, producing no data point
toward the 5% OOS bar. An unscoreable hypothesis is not a survival rate of
zero; it is an unknown. The same applies to the 5 earlier crashed attempts
(`eve-20260803T074058Z-df7df0f9`, `eve-20260803T075102Z-2b98a5f0`,
`eve-20260803T080243Z-29f48c2e`, `eve-20260803T080720Z-12e60677`,
`eve-20260803T081007Z-b7568699`) — those were machinery failures (2 read
timeouts at the old 60s ceiling; 3 hits of a real HTTP 400 tool-result
protocol bug, both since fixed — see "What was fixed" further above in this
report), not Eve results either.

The pre-registered session count starts counting from the first session
where hypotheses are actually scoreable. The bar itself (5%, and whichever
session count is ultimately confirmed as authoritative per the flagged
discrepancy above) is unchanged — only what qualifies as a *countable*
session is being defined, and it is being defined because of a defect on
this project's side, before any survival data exists under the corrected
system. This reasoning, plus the classification of every affected session,
is also recorded machine-readably in `docs/site_data/eve_session_registry.
json` and directly on Session 0's own session file (`session_label`,
`counts_toward_pre_registered_8`, `excluded_from_pre_registration_reason`
fields added to `docs/site_data/eve_sessions/eve-20260803T095520Z-394385c7.
json`), not only in this prose report, so it cannot later look like moving
the goalposts after the fact.

### Decision 2 — Eve now gets the DSL vocabulary (grammar, not a menu)

`nero_core/eve/session.py`'s `SYSTEM_PROMPT_TEMPLATE` now includes a
`DSL_VOCABULARY_BLOCK` supplying:

- the exact `ALLOWED_FIELDS` list (reinlined from `rule_dsl.ALLOWED_FIELDS`,
  byte-identity enforced by a new test —
  `DslVocabularyReuseTest.test_allowed_fields_match_rule_dsl_exactly`),
- the exact `ALLOWED_OPS` list (same reinline/test pattern),
- the exact key names the parser expects (`compare_to_field`,
  `stop_atr_multiple`, `target_r_multiple`, `max_holding_hours`,
  `stop_pct_of_entry`, `target_pct_of_entry`, `dynamic_target_condition`,
  `regime_break_condition`, `regime_break_consecutive_bars`,
  `structured_entry_rule`, `structured_entry_rule_short`,
  `structured_exit_plan`),
- ONE minimal worked example, deliberately mechanism-neutral
  (`{"field": "close", "op": "gt", "value": 0}` / symmetric 1.0/1.0
  stop-target) — syntax only, not a suggested strategy.

This is framed explicitly as vocabulary, not permission: Eve may still
propose anything at all, including mechanisms the DSL cannot express — those
are still recorded honestly as `UNTESTABLE_BY_DSL`, because whether her
creativity outruns the DSL is real capability data. No example of a
specific strategy or mechanism was added anywhere in this block, per
explicit instruction — field names and syntax only, so this narrows nothing
about what Eve may propose.

nero_core/eve/session.py itself still has zero direct
`nero_core.research_agent` imports (`test_eve_no_auto_wire.py` unchanged and
still green) — `DSL_ALLOWED_FIELDS`/`DSL_ALLOWED_OPS` are reinlined
constants, the same pattern `WEB_SEARCH_TOOL` already used, guarded the same
way.

### Decision 3 — pre-submit DSL validator, up to 2 retries

`nero_core/eve/session.py::_process_proposed_hypotheses` now runs every
`propose_hypothesis` call through `scoring.classify_testability` (the exact
same `rule_dsl` parser `scoring.py` uses for real scoring later — called via
`nero_core.eve.scoring`, which remains the one documented, allowlisted
exception through which this branch ever touches `nero_core.research_agent`)
**before** finalizing it as a persisted record:

- **Parses (`TESTABLE`)** → finalized immediately, normal acknowledgement.
- **Fails to parse, retries remaining** (`MAX_DSL_RETRIES = 2`) → **not**
  finalized yet. The parser's own error message is returned to Eve as that
  call's `tool_result`, inviting a revise-and-resubmit; logged to this
  session's own `dsl_correction_log` as `"retry_offered"`.
- **Fails to parse, retries exhausted** → finalized **as-is**, honestly
  `UNTESTABLE_BY_DSL` — this validator only rescues a good idea from a typo;
  it never hides a hypothesis the DSL genuinely cannot express. Logged as
  `"retries_exhausted"`.

Every correction attempt (which hypothesis, what the parser said, the exact
raw hypothesis object attempted) is logged to the session record's new
`dsl_correction_log` field, and rolled up into `ablation_metadata` as
`n_dsl_correction_attempts`, `n_hypotheses_needing_dsl_correction`,
`n_hypotheses_recovered_by_dsl_correction`, and
`n_hypotheses_dsl_retries_exhausted` — how often Eve needs a correction is
itself capability data worth measuring across the 8 sessions, per
instruction.

Retries are grouped per hypothesis by its own `hypothesis_name` (the only
stable identifier across a revise-and-resubmit, since each retry is a
genuinely new `propose_hypothesis` tool-call id) — a hypothesis resubmitted
under a *different* name is untraceable as a retry of the same idea and gets
its own fresh 2-attempt budget; a known, documented limitation
(`_hypothesis_retry_key`'s own docstring), not a safety hole, since
`MAX_TURNS`/the session budget ceiling still bound total turns regardless.
Every retry attempt is charged to the session's normal turn/budget
accounting exactly like any other turn — a schema typo now costs one cheap
correction turn, not an entire session, but it is never free.

`llm_client.build_next_user_message` was extended to accept either one
string (the original behavior, applied to every pending tool call) or a
dict of `tool_use_id -> text` (new), so a turn with multiple pending
`propose_hypothesis` calls can send each one a different reply — e.g. a
plain acknowledgement to a valid proposal and the parser's own error to a
broken one in the same turn.

### Tests added this session

- `tests/test_eve_dsl_validator.py` (new, 10 tests): direct unit coverage of
  `_process_proposed_hypotheses`'s retry/finalize decision logic using the
  exact real Session 0 failure shape (`compare_to` vs `compare_to_field`),
  plus two full `run_session`-level end-to-end tests (retry-then-success,
  and retries-exhausted-still-recorded) driven through a mocked `call_turn`.
- `tests/test_eve_session_registry.py` (new, 5 tests): validates
  `docs/site_data/eve_session_registry.json`'s shape and cross-checks it
  directly against the real `eve_budget_ledger.json` and the real Session 0
  session file, so the registry cannot silently drift from what actually
  happened.
- `tests/test_eve_llm_client.py` (extended): `DslVocabularyReuseTest` (4
  tests, byte-identity against `rule_dsl.ALLOWED_FIELDS`/`ALLOWED_OPS`, the
  exact key names present in the system prompt, and the worked example
  itself actually parsing) and `BuildNextUserMessagePerToolResultTest` (3
  tests, for the new dict-shaped `tool_result_text` parameter).

### Housekeeping confirmations

- `EVE_ENABLED` remains `False` by default in every committed reference —
  `nero_core/eve/config.py::is_enabled` only returns `True` for an explicit
  truthy value, and the one committed reference to the variable
  (`.env.example:15`, `EVE_ENABLED=`) is empty. The real, gitignored local
  `.env` is not committed and its value is never printed here.
- Working tree confirmed clean before commit; every untracked file
  pre-dates this session and is unrelated to this branch's diff (see the
  "Untracked-file accounting" table above — unchanged).
- Full Python suite (`python -m unittest discover -s tests -p
  "test_*.py"`): **2334 tests, 0 failures, 0 errors** (`Ran 2334 tests in
  733.562s` / `OK`) — up from 2312 before this session's 22 new tests (10 in
  `tests/test_eve_dsl_validator.py`, 5 in `tests/test_eve_session_registry.
  py`, 7 added to `tests/test_eve_llm_client.py`); 2312 + 22 = 2334 exactly,
  confirming no existing test was silently dropped.
- Full website Jest suite: **582 passed, 582 total** — unchanged before and
  after (no `website/` file was touched this session).

## Fourth follow-up session: Session 0-B, the asset universe, and a full precondition audit (2026-08-03)

### Session 0-B (`eve-20260803T142519Z-718833c9`) — the asset universe gap

The very next real session after the DSL vocabulary fix landed confirmed
that fix worked completely: **6/6 hypotheses parsed on their first
attempt** (0 `UNTESTABLE_BY_DSL`, 0 pre-submit-validator correction
attempts needed — `n_dsl_correction_attempts: 0`,
`n_hypotheses_recovered_by_dsl_correction: 0`). Terminated via
`end_session_called` (not a budget stop): 6 turns, 3 web searches, $0.4834
real spend against the $1.50 budget.

But **0/6 hypotheses were actually scored.** Every one targeted an (asset,
timeframe) pair outside `nero_core.asset_universe.APPROVED_RESEARCH_
UNIVERSE` — `GOLD/1week`, `SILVER/1week`, `MSFT/1day`, `USD/JPY/1day`, and
a malformed `"asset": "BTC/4h"` value (asset and timeframe mashed into one
field) — and every one was refused real backtest data
(`candle_data_source: "refused"`) before ever reaching `auto_tester.
test_hypothesis`.

Same reasoning as Session 0: an unscoreable hypothesis is an unknown, not
a survival rate of zero, and the cause was outside Eve's control — she was
never told which pairs this platform can actually backtest. She *was*
given a list of "tracked (asset, timeframe) pairs" in her context (drawn
from `quant_metrics.json`, a much wider set — every pair the platform has
*any* quant/site data for), and reasonably reached for economically
plausible pairs from it. That list was never wrong information; it was
incomplete without also stating which of those pairs can actually be
scored.

Recorded as **"Session 0-B — asset universe gap"** in `docs/site_data/
eve_session_registry.json` and directly on the session's own file (same
`session_label` / `counts_toward_pre_registered_8` / `excluded_from_pre_
registration_reason` pattern as Session 0). Produces no data point toward
the 5% OOS bar. **The pre-registered 8 still has not started.**

### Fix: the approved research universe, same framing as the DSL vocabulary

`nero_core/eve/session.py` now imports `APPROVED_RESEARCH_UNIVERSE`
directly from `nero_core.asset_universe` — a shared, neutral module under
neither `nero_core.eve` nor `nero_core.research_agent` that Eve and Adam
already both import, so this is a live import, not a reinlined-and-tested
copy (no drift risk to guard against the way `DSL_ALLOWED_FIELDS`/`DSL_
ALLOWED_OPS` need to be). A new `APPROVED_RESEARCH_UNIVERSE_BLOCK` states
the exact four pairs — `asset="BTC", timeframe="4h"` /
`asset="ETH", timeframe="4h"` / `asset="PAXG", timeframe="4h"` /
`asset="SOL", timeframe="4h"` — explicitly as **available data, not
permitted ideas**: Eve may still propose on any pair at all, and one
outside the list is still recorded and scored honestly as refused, never
silently dropped or auto-redirected — whether her reasoning keeps reaching
for pairs this platform lacks is itself useful signal about what data to
acquire next. The DSL vocabulary block's own worked example was also fixed
to model the correct `"asset": "BTC", "timeframe": "4h"` separated-field
shape (it previously used placeholder text that never demonstrated this,
which is plausibly part of why the real `"BTC/4h"` mangling happened in
the first place).

### The full precondition audit — requested BEFORE running a third session

Two sessions in a row have now produced zero scoreable output because of
something Eve was never told: first the DSL key names, then the asset
universe. Rather than find a third gap the same expensive way, every
precondition a hypothesis must satisfy to get a real, scored verdict was
audited end-to-end against the actual pipeline code (`nero_core/eve/
scoring.py`, `nero_core/research_agent/auto_tester.py`, `nero_core/
research_agent/frequency_gate.py`, `nero_core/asset_universe.py`, `tools/
backtest_statistics.py`) — not inferred from behavior, read directly.

| # | Precondition | Where enforced | What happens if unmet | Is Eve currently told? |
|---|---|---|---|---|
| 1 | `structured_entry_rule`/`structured_exit_plan` parse via the rule DSL (exact field names, op names, key names) | `scoring.classify_testability` (pre-submit validator + final scoring, same call) | Recorded `UNTESTABLE_BY_DSL`, up to 2 correction retries first | **YES** — fixed this branch (`DSL_VOCABULARY_BLOCK`), confirmed working: 0/6 failures in Session 0-B |
| 2 | `(asset, timeframe)` is in `APPROVED_RESEARCH_UNIVERSE` (`(BTC,4h)`/`(ETH,4h)`/`(SOL,4h)`/`(PAXG,4h)` only) | `pipeline.default_candles_provider`, raises `DataSourceRefusedError` | Recorded `candle_data_source: "refused"`, no verdict at all | **YES** — fixed this session (`APPROVED_RESEARCH_UNIVERSE_BLOCK`), not yet exercised by a real session |
| 3 | `generated_at` present and ISO8601-parseable in the raw hypothesis object | `auto_tester._parse_generated_at`, checked FIRST inside `test_hypothesis`, before the frequency gate or any backtest | `verdict_combined="UNTESTABLE"`, `frequency_classification="UNMEASURABLE"`, `verdict_is`/`verdict_oos` both null — **but `testability` stays `"TESTABLE"`** (that field is set earlier, by `classify_testability`, and never revisited), so a scored record can read `testability: TESTABLE` next to `verdict_combined: UNTESTABLE` — confusing, and a real trap for the next session unless flagged now | **NO.** Never mentioned anywhere in `SYSTEM_PROMPT_TEMPLATE`, `DSL_VOCABULARY_BLOCK`, `APPROVED_RESEARCH_UNIVERSE_BLOCK`, or `PROPOSE_HYPOTHESIS_TOOL`'s description. Nothing auto-injects it into a real Eve hypothesis either — `hypothesis_shapes.build_hypothesis_record` only stamps session/turn/tool-call metadata around `raw_hypothesis`, never adds a field inside it. (The only place `generated_at` IS auto-populated is `nero_core/eve/random_baseline.py`, a completely separate synthetic-baseline generator Eve's own hypotheses never touch.) **This is very likely the next gap to bite, now that DSL syntax and asset universe are both fixed.** |
| 4 | Entry-rule trigger frequency clears `TOO_SLOW`/`UNMEASURABLE` — needs ≥30 triggers/year to clear `VIABLE`, ≥60/year to clear `FAST` (`TARGET_RESOLVED_TRADES=30` resolved trades within `VIABLE_MAX_MONTHS=12`/`FAST_MAX_MONTHS=6` months), and ≥60 eligible candles before `generated_at` to even attempt a measurement | `frequency_gate.measure_entry_frequency`, called by `auto_tester.test_hypothesis` as its own first real step (after the `generated_at` check) | `verdict_combined="SKIPPED"` — **never reaches the backtest at all**, "HARD RULE: must never reach the harness, no matter how strong the mechanism looks" (`frequency_gate.py`'s own words) | **NO.** Not mentioned anywhere Eve can read. This is the user's own flagged concern, confirmed directly in code: Adam's 9 hypotheses were all rejected `TOO_SLOW` under this exact gate. Eve currently has zero numeric sense of how selective an entry condition can be before it's rejected as too rare — nothing tells her the ~30/year (VIABLE) or ~60/year (FAST) thresholds, or that a threshold like `zscore20 <= -3` on a 4h chart might simply never fire often enough regardless of whether the mechanism is sound. |
| 5 | ≥`MIN_SAMPLE_SIZE` (20) trades on BOTH halves, positive expectancy on both, AND bootstrap CI clears zero on both, to reach `SURVIVED` rather than the softer `PROMISING-WATCHLIST` | `tools.backtest_statistics.classify_verdict`, called inside `test_hypothesis` after a real backtest runs | Still gets a real verdict (never `SKIPPED`/`UNTESTABLE`) — capped at `PROMISING-WATCHLIST` at best, and `scoring._p_value_for_half` nulls the p-value (so it's excluded from FDR correction) below this threshold | **NO**, but lower severity than #3/#4 — this doesn't block a verdict outright, only caps which verdict is reachable and whether the p-value counts toward the FDR family. Worth telling her eventually so she understands *why* a real, working hypothesis with too few trades can't be reported as `SURVIVED`, but not a blocker to running a session. |
| 6 | Research export file physically exists on disk for the approved pair | `pipeline.default_candles_provider` reads `docs/research_data/candles/<pair>.json` | Recorded `candle_data_source: "refused"` (same as #2) | **N/A for Eve** — not a hypothesis property she can reason about, purely a data-availability fact. Confirmed **not currently a live risk**: all 4 approved pairs' export files exist on disk today (`BTC_4h.json`, `ETH_4h.json`, `PAXG_4h.json`, `SOL_4h.json`, all present). |
| 7 | ATR-based stop (`stop_atr_multiple`) requires a valid (non-NaN, positive) `atr14` reading on the entry candle to actually open a trade | `auto_tester._size_entry_for_hypothesis` | No hard rejection — the trigger still counts toward the frequency gate, but a triggering candle during ATR warmup silently produces no trade (fewer realized trades than the raw trigger count would suggest) | **NO**, lowest severity of the group — a natural, minor consequence of indicator warmup the DSL vocabulary block already establishes the general principle for (warmup = does not fire), not a distinct gate that rejects a hypothesis outright. A `stop_pct_of_entry` plan avoids this entirely. Flagged for completeness, not urgent. |

**Summary for the decision this audit exists to support:** items 1 and 2 are
now fixed and confirmed/pending-confirmation respectively. **Item 3
(`generated_at`) is assessed as the single highest-probability next
failure** — structurally identical to items 1 and 2 (a silent, total
precondition Eve has no way to know about), and specifically because
`testability` and `verdict_combined` can disagree if it's missing, it's
also the one most likely to *look* like a different kind of confusing bug
if hit blind, rather than reading immediately as "another undocumented
precondition." **Item 4 (frequency gate)** is the user's own named
example and is real, but partially self-solving for a very selective
condition on a 4h chart (Eve can reason qualitatively about
"fires rarely" even without the exact numbers) — supplying the exact
≥30/≥60-per-year thresholds would let her reason quantitatively instead.
Items 5–7 are lower severity and do not block a session from producing a
real verdict on their own.

No code changes were made for items 3–7 in this pass — reported per
instruction, not fixed, pending review before Session 1 (the first
countable one) is run.

### Test counts, this fourth follow-up session

Full Python suite (`python -m unittest discover -s tests -p
"test_*.py"`): **2338 tests, 0 failures, 0 errors** (`Ran 2338 tests in
718.501s` / `OK`) — up from 2334 (the count at the end of the third
follow-up session) by 4 new tests: 1 in `tests/test_eve_session_registry.
py` (`test_session_count_reconciliation_is_recorded_not_silently_changed`,
part of the N=5→N=8 reconciliation) and 3 in `tests/test_eve_llm_client.py`
(`test_system_prompt_states_the_approved_research_universe`, `test_worked_
example_shows_asset_and_timeframe_as_separate_fields`, `test_asset_
universe_framed_as_data_not_permission`). Website Jest suite unchanged
(582/582 — no `website/` file touched this session).

## Fifth follow-up session: fixing items 3, 4, 5, 7 all together, and the re-audit (2026-08-03)

Per instruction, all four remaining findable gaps from the precondition
audit were fixed in one pass — "I am not spending another session
discovering the next one" — rather than one gap per session.

### Item 3 — `generated_at`: made server-side, and the contradiction reconciled

**Never Eve's problem now.** `nero_core.eve.hypothesis_shapes._inject_
generated_at` stamps a real, correct ISO8601 `generated_at` onto every
`raw_hypothesis` at the moment `hypothesis_shapes.build_hypothesis_record`
finalizes it — the ONE place a fresh record is built, called from both a
successful first attempt and a correction-exhausted finalize inside
`session._process_proposed_hypotheses`. It **always overrides** anything
Eve might supply herself (there's no legitimate reason for her to supply
one, and trusting a self-reported value would reopen the exact
lookahead-cutoff manipulation risk this field exists to prevent). Returns a
new dict — the caller's own `raw_hypothesis` is never mutated in place.

**Fails loudly, never silently**, per instruction: raises `TypeError`
immediately if `raw_hypothesis` isn't a dict (defense-in-depth — every real
caller already guards this, but the function doesn't trust that
indirectly), and the injected value is asserted to round-trip through
`datetime.fromisoformat` — the exact parser `auto_tester._parse_
generated_at` uses — so a future refactor that breaks this crashes
immediately rather than surfacing as a confusing downstream verdict. An
uncaught exception here is not silent: `pipeline.run_pipeline`'s existing
`except Exception` path already notifies and re-raises rather than
swallowing.

**The contradiction reconciled.** `scoring.score_hypothesis` now imports
`VERDICT_UNTESTABLE` directly from `auto_tester` (reused, never re-typed as
a magic string — `test_eve_no_auto_wire.py`'s `SCORING_ALLOWED_IMPORTS`
updated to allow exactly this one additional named import) and, whenever
`adam_test_hypothesis`'s own return has `verdict == VERDICT_UNTESTABLE`,
downgrades `testability` from `"TESTABLE"` to a new, distinct
`TESTABILITY_UNTESTABLE_BY_HARNESS`, carrying Adam's own human-readable
`reason` forward as `testability_reason`. A record can now never assert
`testability: "TESTABLE"` next to `verdict_combined: "UNTESTABLE"`. With
`generated_at` now always present, this specific path is structurally
unreachable via real inputs (`classify_testability` and `auto_tester.test_
hypothesis` parse the exact same dict with the exact same functions, so
they can never disagree on DSL shape) — the reconciliation is a hard
invariant guarding against that always being true, not a fix conditioned on
it, and is tested by mocking the harness call directly
(`TestabilityVerdictReconciliationTest`) since no real scenario can trigger
it anymore.

### Items 4, 5, 7 — told to Eve, same framing as the DSL vocabulary

A new `FREQUENCY_AND_VERDICT_BLOCK` in `session.py`'s system prompt, appended
after the asset-universe block:

- **Item 4 (frequency gate):** the exact thresholds — reinlined from
  `frequency_gate.FAST_MAX_MONTHS`/`VIABLE_MAX_MONTHS`/`TARGET_RESOLVED_
  TRADES` with a byte-identity drift test (`FrequencyGateReuseTest`, same
  pattern as the DSL fields/ops) — **~30 trades/year to reach the harness at
  all, ~60/year to be tested comfortably**, stated as a measured property of
  the platform, not an instruction. Includes the user-supplied finding that
  this platform's own LLM-authored hypotheses have overestimated their own
  trigger frequency by roughly 5x on average (claimed 24-32/year, measured
  2.5-15/year, all rejected `TOO_SLOW`) — **note on provenance**: this exact
  figure was not independently locatable in any file in this repo (`docs/
  research_agent_real_run_followup.md`, the closest candidate, explicitly
  states "Did the LLM follow the 20-30 trades/year instruction? UNVERIFIED
  — cannot be answered this run" because zero real Adam LLM calls had
  succeeded at that point); included verbatim per explicit instruction from
  the user as the domain-authoritative source, flagged here rather than
  silently presented as independently re-verified.
- **Item 5 (SURVIVED bar):** `MIN_SAMPLE_SIZE` (live import from `tools.
  backtest_statistics` — not under `nero_core.research_agent`, no drift risk
  by construction) — ≥20 resolved trades per half, positive expectancy on
  both, bootstrap CI clearing zero on both, for `SURVIVED`; a softer
  `PROMISING-WATCHLIST` otherwise, never a rejection.
- **Item 7 (ATR warmup):** one line — a `stop_atr_multiple` plan can only
  open a trade when `atr14` is a valid reading on the entry candle;
  `stop_pct_of_entry` is not subject to this.

### Re-audited precondition table

Every row from the original audit, re-checked against the code as it now
stands:

| # | Precondition | Told to Eve, or handled server-side? |
|---|---|---|
| 1 | DSL syntax parses | **Told** — `DSL_VOCABULARY_BLOCK`, confirmed working (Session 0-B: 6/6 first-attempt parses) |
| 2 | `(asset, timeframe)` in `APPROVED_RESEARCH_UNIVERSE` | **Told** — `APPROVED_RESEARCH_UNIVERSE_BLOCK`, not yet exercised by a real session |
| 3 | `generated_at` present & ISO8601 | **Handled server-side** — always injected by `hypothesis_shapes._inject_generated_at`, fails loudly if it ever can't be; Eve never needs to know this field exists |
| 3b | (reporting correctness, not itself a precondition) `testability` must never contradict `verdict_combined` | **Fixed** — `scoring.score_hypothesis` reconciles via `TESTABILITY_UNTESTABLE_BY_HARNESS` |
| 4 | Frequency ≥~30/year (VIABLE), ≥~60/year (FAST) | **Told** — `FREQUENCY_AND_VERDICT_BLOCK`, with the LLM overestimation-bias context |
| 5 | ≥20 trades/half + positive expectancy + CI clears zero, for SURVIVED | **Told** — same block |
| 6 | Research export file exists on disk | **N/A for Eve** — confirmed still true: all 4 approved pairs' exports present |
| 7 | Valid `atr14` at entry for an ATR-based stop | **Told** — one line, same block |

**Every row is now either (a) told to Eve, or (b) handled entirely
server-side so she never needs to know.** No open gap remains in this
table as of this commit.

### Tests added this session

- `tests/test_eve_hypothesis_shapes.py` (extended): generated_at injection
  overrides Eve's own value, never mutates the input dict, and fails loudly
  (`TypeError`) on a non-dict input; the old "verbatim" test updated to
  exempt exactly the one injected field.
- `tests/test_eve_scoring_testability_split.py` (extended):
  `TestabilityVerdictReconciliationTest` — the harness-returns-UNTESTABLE
  case downgrades `testability` and never leaves it at `TESTABLE`; a real
  SURVIVED/DIED verdict never triggers the downgrade.
- `tests/test_eve_dsl_validator.py` (updated): three raw_hypothesis
  equality assertions now exempt the injected `generated_at` field via a
  small local helper.
- `tests/test_eve_llm_client.py` (extended): `FrequencyGateReuseTest`-style
  drift guards for the reinlined frequency-gate constants and the live
  `MIN_SAMPLE_SIZE` import, plus content assertions that the system prompt
  states the frequency thresholds, the overestimation finding, the SURVIVED
  bar, and the ATR warmup note.
- `tests/test_eve_no_auto_wire.py` (updated): `SCORING_ALLOWED_IMPORTS`
  extended by exactly one entry (`VERDICT_UNTESTABLE`).

Full Python suite: **248/248** Eve-specific tests passing (`python -m
unittest discover -s tests -p "test_eve_*.py"`). Full repository suite
(`python -m unittest discover -s tests -p "test_*.py"`): **2349 tests, 0
failures, 0 errors** (`Ran 2349 tests in 361.959s` / `OK`) — up from 2338
by 11 new tests (3 in `tests/test_eve_hypothesis_shapes.py`, 2 in
`tests/test_eve_scoring_testability_split.py`, 6 in `tests/test_eve_llm_
client.py`). Website Jest suite unchanged (582/582 — no `website/` file
touched this session).
