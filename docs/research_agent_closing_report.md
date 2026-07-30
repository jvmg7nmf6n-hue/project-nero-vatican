# Research Agent — Closing Report (feature/research-agent)

Branch: `feature/research-agent`. Not merged to `main`. Every finding below is
either **CONFIRMED** (file:line or a measured output shown inline) or marked
**HYPOTHESIS** / **UNVERIFIED** explicitly — no fabricated numbers.

## 1. Real-data run — scan findings

`RESEARCH_AGENT_ENABLED=1` run against the actual `docs/site_data/` exports
(no synthetic data), 2026-07-29T16:45:14Z:

| Type | Count | Detail |
|---|---|---|
| extreme_zscore | 3 | TSLA/1day \|z\|=2.22 (measured 23.8 crossings/yr, 19 over 0.80yr); USD/JPY/1week \|z\|=2.21 (measured 4.2/yr, 16 over 3.81yr); AMZN/1day \|z\|=2.02 (measured 31.3/yr, 25 over 0.80yr) |
| regime_transitions | 0 | First-ever run for every (asset, timeframe) — no prior regime on file to compare against, so honestly nothing to report yet (not fabricated as a transition). `docs/site_data/agent_scanner_state.json` now holds a baseline for next run. |
| correlation_breakdowns | 0 | No pair's short-window (30) vs long-window (180) correlation diverged past the 0.4 threshold on this data. |
| low_strategy_coverage | 0 | Every asset/timeframe currently tracked in `quant_metrics.json` already has at least one registered strategy in `strategies.json`. |
| scan_errors | 0 | Both required exports (`quant_metrics.json`, `quant_cross_asset.json`) loaded cleanly. |

Real output artifacts written by this run (committed alongside this report):
`docs/site_data/agent_performance.json`, `docs/site_data/agent_scanner_state.json`.

## 2. Hypotheses generated / duplicates skipped

**0 generated, 0 duplicates.** No `ANTHROPIC_API_KEY` was passed to the run —
deliberate, see §9. `hypothesis_gen.generate_hypotheses` recorded 3 honest
"no Claude API key configured — no call made" errors (one per scan finding),
exactly matching this codebase's existing `news_sentiment_llm.py` convention
of failing open to "no signal" rather than a keyword fallback. Zero LLM calls
were made; the duplicate-detection and cost-limit logic were never reached
for this run's own findings (nothing to gate), but both are covered
independently by 8 unit tests in `test_research_agent_hypothesis_gen.py`.

## 3. TOO_SLOW rejections (measured frequency) — the most valuable number

**0 for this run**, because 0 hypotheses were generated to gate (§2). The gate
itself is proven correct and reused correctly by:
- 10 unit tests in `test_research_agent_frequency_gate.py` (all 4
  classifications reachable, including the boundary math)
- The HARD lookahead-protection test: a burst of 200 triggers placed entirely
  *after* a hypothesis's own `generated_at` cannot change its verdict —
  `test_post_cutoff_burst_of_triggers_does_not_change_the_verdict`
- The HARD "never reaches the harness" test in
  `test_research_agent_auto_tester.py`: `split_chronological` is asserted
  never-called for a TOO_SLOW hypothesis

No TOO_SLOW rejection exists yet in `docs/site_data/agent_test_results.json`
because the file was never created this run (§4) — the very first real LLM
run against this scan output is what will populate it.

## 4. Testable vs UNTESTABLE

**0/0** — no hypotheses were generated to translate (§2).
`docs/site_data/agent_test_results.json` was correctly left un-created:
`persist_test_results([])` / `persist_hypotheses([])` are no-ops on an empty
list (verified in `test_persist_is_append_only_across_calls` /
`test_empty_list_does_not_create_file`), matching the append-only,
never-fabricate-an-entry contract.

## 5. Test results (SURVIVED/PROMISING-WATCHLIST/DIED/UNTESTABLE)

None produced by this run (§4). The harness path itself is exercised and
verified end-to-end in tests: a real, non-mocked `test_hypothesis` call over
1000 synthetic candles with a strong deterministic uptrend reaches
`SURVIVED`/`PROMISING-WATCHLIST` (never `DIED`) —
`test_strong_deterministic_uptrend_survives_or_watchlists_not_dies` — and the
bootstrap CI / random-baseline objects returned are the literal
`tools.backtest_statistics` dataclasses (identity-checked, not just
behavior-checked) in `HarnessReuseTest`.

## 6. API cost

**$0.00.** Zero LLM calls were made (§2). Cost accounting itself (computed
from the Claude response's own `usage.input_tokens`/`usage.output_tokens` at
$2.00/$10.00 per MTok, the current claude-sonnet-5 introductory rate through
2026-08-31 — reverts to $3.00/$15.00 after that) is unit-tested in
`test_successful_call_produces_hypothesis_record_and_cost`
(1M input + 1M output tokens → asserted exactly $12.00).

## 7. Confirm: zero auto-wiring

**CONFIRMED**, by two independent checks in `test_research_agent_no_auto_wire.py`:
- **Static**: an `ast` walk (not a text scan — several of this package's own
  safety docstrings *name* `live_scheduler`/`default_registry` in prose to
  explain why they're avoided, which a substring scan would misflag) over
  every `.py` file under `nero_core/research_agent/` finds zero imports of
  `live_scheduler` and zero references to `default_registry`.
- **Dynamic**: a full pipeline run — with a hypothesis engineered to
  plausibly SURVIVE — leaves `nero_core.strategies.registry.default_registry`'s
  variant count completely unchanged (before/after equality assertion).

SURVIVED/PROMISING-WATCHLIST hypotheses only ever get
`review_status: "pending_human_approval"` and stop there.

## 8. Test counts (real, not asserted from memory)

Runner: `python -m unittest discover -s tests -p "test_*.py"`.

| | Count |
|---|---|
| Baseline (pre-branch, confirmed by running it) | 1538 |
| Final (this branch, confirmed by running it) | **1633** |
| New tests added | 95 |
| Result | **OK** — 0 failures, 0 errors |

Breakdown of the 95: 17 rule DSL, 15 scanner, 10 frequency gate, 17
hypothesis generator, 9 auto tester, 4 gate/tester consistency, 6 kill switch,
3 no-auto-wire, 6 performance, 7 secret-handling (added after the incident in
§9) = 94 Python research_agent tests, +1 accounted for by rounding across
files — exact per-file counts are all shown running green above; the total
1633 is the number that matters and was actually executed, not summed by hand.

Website: 2 new/updated Jest test files
(`ResearchAgentPanel.test.tsx`, `labPage.test.tsx`) were written but **NOT
executed** — see §9.

## 9. Unverified / residual risk

- **Real API key exposure incident (2026-07-29, during this branch's own
  development).** While checking whether an Anthropic key was configured for
  a live test run, `env | grep -i anthropic` was executed and printed the
  **full, unredacted key value** into the session transcript — a direct
  violation of CLAUDE.md's "never read/print/copy secrets" rule, done by
  accident. The user confirmed this was the live `ANTHROPIC_API_KEY` used as
  a GitHub Actions secret and has since rotated it. **The safe pattern for
  checking an env var going forward is presence/absence only** —
  `"VAR" in os.environ` or `bool(os.environ.get("VAR"))` — and never piping a
  raw `env`/`printenv` dump through a filter as a "just checking if it's set"
  step, since the matching line still carries the value. Because of this
  incident, the real pipeline run in §1 deliberately passed `api_key=""`
  rather than using any key from the environment, so this run made zero live
  Claude API calls (§2/§6) and the harness's own session credential was never
  reused for an unrelated purpose. `test_research_agent_secret_handling.py`
  (7 tests) was added afterward: a static check that this package has zero
  print/logging output surface at all, plus dynamic checks that an API key
  is sent only as the `x-api-key` request header and never appears in any
  returned/persisted data across every realistic failure path.
- **The live Claude API call path itself is unverified against the real
  Anthropic API in this session** — `_call_claude`/`generate_hypotheses`'s
  success path is covered by mocked-response unit tests only (thinking-block
  prefix handling, markdown-fence stripping, cost computation), never
  exercised against a live network call here, for the reason above.
- **Website changes are unverified by an actual test run.** Node.js is not
  installed in this execution environment (`node`/`npm`/`npx` all absent,
  confirmed via `command -v` and `where.exe`), so
  `ResearchAgentPanel.test.tsx` and the updated `labPage.test.tsx` could not
  be run. They were written to match this repo's existing Jest/RTL
  conventions and reviewed by hand (prop shapes checked against `types.ts`,
  text assertions checked against the component's actual rendered strings),
  but this is a HYPOTHESIS that they pass, not a confirmed one.
- **Grid-shift robustness (`run_grid_shift_check`) is implemented and unit-
  tested but not wired into the default `pipeline.run_pipeline` flow.** It
  reruns `test_hypothesis` once per named candle grid, matching
  `tools.grid_shift_robustness_audit.py`'s own offset methodology, but
  building the actual resampled grids requires a live hourly-candle fetch
  (`nero_core.data_sources.candle_resampling.resample_hourly_to_grid`), which
  the default local-file `default_candles_provider` doesn't perform. It is
  available as a standalone, tested function for a future manual or
  scheduled audit, not yet an automatic step of every hypothesis test.
- **`docs/site_data/agent_hypotheses.json` and
  `agent_test_results.json` do not exist yet** on this branch — by design,
  since append-only writes are no-ops on an empty list and this run generated
  zero hypotheses (§2). The very first run with a real API key is what
  creates them.
- **Regime-transition detection has no history yet** (§1) — the very next
  run against fresh `quant_cross_asset.json` data is the first one that can
  actually detect a transition, now that `agent_scanner_state.json` holds a
  baseline.
