# Project Vatican (NERO-2) — Build Instructions for Claude Code

## Context

You are building **Vatican**, a second-generation evolution of an existing project called **NERO**.

- **Original NERO location (read-only source, DO NOT MODIFY):**
  `C:\Users\HP\Documents\Codex\2026-07-06\tu`
- **You are working in:** `C:\Users\HP\Documents\Codex\project-nero-vatican` (this folder, empty right now)

NERO is a working Streamlit-based crypto/gold trading research system: live dashboards, a verdict engine, a mean-reversion paper trader, 5 parallel strategy-lab algos, quant intelligence (correlation, beta, Granger causality, cointegration, GARCH, Kalman beta), ETF flow scanner, historical market memory, White House/policy event study, prediction log, strategy performance auditor, and GitHub Actions automation. It is genuinely built — 8,400+ lines, 20 test files. Study it before writing anything.

Vatican's purpose: become a paid, evidence-driven trading signal/research platform for gold and crypto traders, eventually sellable as a business (target: institutional-grade, auditable track record, not hype).

## Hard Rules — Non-Negotiable

1. **Never read, print, copy, or commit secrets.** This includes API keys, Gmail app passwords, Twelve Data keys, Gemini keys, ntfy private topics, contents of `.streamlit/secrets.toml`, `.env`, or any `local_settings.json`. Use environment variables / Streamlit secrets placeholders only. If you need to reference a secret's *name*, reference it — never its value.
2. **Paper trading only.** No real exchange order execution. No private exchange API keys. No financial advice language anywhere in UI copy, code comments, or docs. No guaranteed-profit claims.
3. **Never modify anything inside `C:\Users\HP\Documents\Codex\2026-07-06\tu`.** Read from it (to study/copy patterns) but all writes happen only inside `project-nero-vatican`.
4. **No strategy may silently self-modify parameters.** Any parameter change creates a new, explicitly versioned strategy variant — never mutate an existing one in place.
5. **No lookahead bias.** All strategy/backtest logic must only use closed-candle data available at decision time.

## Scope for THIS session — Phase 0 + Phase 1 ONLY

Do not attempt the full 9-module spec in one pass. Build only the following now. Everything else (ETF flow layer, macro/policy intelligence, mobile alerts, reports, full UI) comes in later sessions once this foundation is solid and tested.

### Step 1 — Analysis (do this first, before writing code)
Read the original NERO codebase at the path above. Produce a short written summary (as a markdown file `docs/nero_analysis.md` in this new repo) covering:
- What modules exist and what each does (one line each)
- Which modules are safe to port over largely as-is vs which need restructuring
- Confirm no secrets exist in any file you read

### Step 2 — Scaffold the Vatican folder structure
Inside `project-nero-vatican`, create:
```
project-nero-vatican/
  app.py
  nero_core/
    config.py
    schema.py
    data_sources/
    quant/
    strategies/
    council/
    truth_ledger/
    storage/
  data/
  tools/
  tests/
  docs/
  .github/workflows/
  requirements.txt
  README.md
  .gitignore
  .env.example
```
Set up `.gitignore` to exclude secrets/env files from day one (copy the pattern from original NERO's `.gitignore`, don't skip this).

### Step 3 — Port the Quant Intelligence + core schema
- Copy `quant_intelligence.py` and `schema.py` patterns from original NERO into `nero_core/quant/` and `nero_core/schema.py`, adapting imports to the new structure. Keep the Pydantic model discipline.
- Do not add new quant methods yet — just get the existing ones running cleanly in the new structure with tests passing.

### Step 4 — Truth Ledger foundation
- Design a SQLite-backed schema (file: `nero_core/truth_ledger/models.py`) for a signal/prediction ledger with these fields: timestamp, asset, strategy_id, strategy_version, direction, confidence, entry_condition_values (JSON), reason, result, exit_reason, r_multiple, fees_slippage_estimate, truth_label (enum: TRUE_POSITIVE, FALSE_POSITIVE, TRUE_NEGATIVE, FALSE_NEGATIVE, INCONCLUSIVE).
- Write basic CRUD functions and one test proving no-duplicate-trade insertion and correct truth labeling logic.

### Step 5 — Strategy Registry (versioning)
- Build `nero_core/strategies/registry.py`: a strategy must be registered with a unique ID + explicit version string + parameter dict. Attempting to change parameters on an existing version must fail — it must require registering a new version instead. Write a test proving this.
- Port ONE existing strategy (Mean Reversion) into this registry as the first proof of concept. Do not port all 5 yet.

### Step 6 — Council Engine (skeleton only)
- Build `nero_core/council/engine.py` that outputs the JSON shape below, using real data only for the inputs currently ported (quant consensus + mean reversion strategy state). Everything else outputs `null`/"insufficient data" honestly rather than fake values.
```json
{
  "asset": "BTC",
  "global_score": 0,
  "stance": "NO_TRADE | WATCH | PAPER_TEST_READY | HIGH_QUALITY_SETUP",
  "directional_bias": "LONG | SHORT | NEUTRAL",
  "confidence": 0,
  "risk": 0,
  "top_supportive_factors": [],
  "top_blockers": [],
  "recommended_strategy": "",
  "summary": ""
}
```

### Step 7 — Tests
Every module above needs at least one real test (not placeholder). Run the full test suite before declaring this phase done. Report pass/fail honestly — do not mark something done if tests fail.

## Deliverable for this session

1. `docs/nero_analysis.md` — the codebase study
2. Working scaffold with Steps 2–6 implemented
3. Passing test suite
4. A short `docs/phase0_1_summary.md`: what got built, what's stubbed/fake, known limitations, and a proposed plan for the NEXT phase (ETF flow, macro/policy, full strategy portfolio, UI, alerts, reports — do not build these yet, just outline)

## Tone/Discipline

Be honest about what's real vs stubbed. Do not fabricate strategy performance numbers or claim "edge" that hasn't been empirically shown in the ledger. This system's entire value proposition is evidence-based trustworthiness — treat that as a hard constraint on your own output too.
