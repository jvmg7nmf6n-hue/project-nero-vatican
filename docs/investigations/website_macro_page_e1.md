# Website Part E — /macro page

Date: 2026-08-07. CC-1 comprehensive directive, Part E.

## E1 — data plumbing, reported first per explicit instruction

**Before this page**, the site could NOT read any Bellwether/macro data at
all: `docs/site_data/macro_reads.json` did not exist. The export mechanism
(`export_macro_reads_json()` in `nero_core/execution/bellwether_overlay.py`)
was already built in Part C, but the scheduled overlay workflow
(`.github/workflows/bellwether_overlay.yml`, every 8h) had not yet had its
first tick — there was nothing for this page to fetch.

**An export step WAS needed, and it already existed** (Part C's own work)
— what was missing was a first real run. Ran
`python -m nero_core.execution.bellwether_overlay` for real against
production `data/truth_ledger.db` (previously only smoke-tested against a
copy) — committed separately from this page
(`a6d664a`, "first real Bellwether macro overlay run"), matching the
directive's own concern separation. This seeded real data: GOLD BEARISH
(agreement 50%, coverage 11%), BITCOIN STRONG_BULLISH (agreement 100%,
coverage 24%), 0 of 54 existing `ORDERFLOW_IMBALANCE/BTC` entries flagged
(all `insufficient_data` — they predate this first-ever macro read, the
documented no-lookahead first-deployment behavior). Confirmed live on
`raw.githubusercontent.com` before building this page against it — no
speculative UI built against data that might not exist.

**No new dependency, no backend** — `fetchMacroReads()` follows the exact
same `fetchJson`/`revalidate = 300` pattern every other page uses.

## What's real, and what's a known, disclosed limitation

- Per-asset bias/agreement/coverage/probability_up: real, from A1's split
  metric (Part A).
- 15-agent provenance breakdown: real, named individually, with a static
  reference table (`lib/macroReads.ts::AGENT_REAL_DATA_SOURCE`) mapping the
  3 currently-real/mixed agents to their actual data sources (FRED DFII10,
  DX-Y.NYB, ^VIX, Binance funding rate) — this mapping is this project's
  own already-documented sourcing (`README_VATICAN.md`), not derived from
  the export itself.
- Reasoning/risks/alternative scenarios: real, verbatim from Bellwether's
  own output.
- **Known limitation, stated honestly, not glossed over**: the export
  carries agent-level PROVENANCE only, not each agent's individual SIGNAL
  (bullish/bearish/rationale) or a machine-readable per-agent data-source
  string. The directive asked for "each agent's signal, its provenance
  label, and its data source where real" — the signal-level detail isn't
  currently exported (Bellwether's `AnalysisOutput.provenance_breakdown` is
  agent→provenance only; per-agent signals live in each `AgentResult`,
  which the overlay job doesn't currently persist). Building that would
  mean extending `export_macro_reads_json()` — flagged as a real follow-up,
  not silently worked around or faked.
- Conflict annotations: real, from Part C's `macro_conflict_flags` table —
  currently all `insufficient_data` (correct, honest, first-deployment
  state), never rendered as if a real evaluation happened.
- History: real, currently 2 rows (1 GOLD + 1 BITCOIN cycle) — an honest
  "too early to show a trend" note is shown rather than a misleadingly
  sparse chart.

## E2 — honest empty/partial states

- Zero total reads: a page-level message naming the exact reason (overlay
  hasn't run, or circuit breaker tripped) — never a blank page.
- A read for only one asset: the OTHER asset shows its own specific
  "no read yet" card, not a silent gap.
- `bias == "NEUTRAL"` with `coverage < 0.15`: an explicit red note — "Neutral
  because coverage is low... not a considered market view" — so a thin
  read can never be mistaken for a considered NEUTRAL call.
- Data age on every panel: every read/history row shows its own real UTC
  timestamp.

## E3 — conflict annotation, linked toward the Truth Ledger

The `ORDERFLOW_IMBALANCE/BTC` section shows every evaluated flag (entry
direction, status, conflicted?, reason) and links to `/#ledger`. A full
per-row deep link (macro_reads_id → exact read) is possible with the data
already exported but wasn't built as a dedicated route this pass — the
table already exposes the same reasoning text a deep link would show;
flagged as a incremental follow-up, not required for E3's own ask of
"surface it, link through."

## E4 — framing, checked against the actual page copy

`eyebrow: "Bellwether — partially wired"`, page description explicitly
states "not an 'AI macro intelligence' framing while most of its 15 agents
are still synthetic." No page anywhere claims certainty or edge. The
provenance table is the visually largest section — deliberately, per the
directive's own observation that this is "probably the most interesting"
part.

## Verification

- 6 new tests for `lib/macroReads.ts` (latest-read selection, provenance
  counting, per-asset/conflicted flag filtering) + 5 new tests for
  `app/macro/page.tsx` (empty state, real dual-asset render, per-asset
  partial state, sparse-history note, empty-conflicts state).
- `next build` compiles; real Playwright screenshot of `/macro` against the
  live dev server (fetching the REAL, just-pushed `macro_reads.json` from
  `raw.githubusercontent.com`) confirms the full page renders correctly:
  both asset cards, the 15-row provenance table with real data sources,
  reasoning/scenarios, the 20-row conflict table, and history — zero
  console errors.
- `npx jest`: 669/671 passing (2 pre-existing, unrelated
  `siteDataSchema.test.ts` failures, unchanged from every other report this
  session).
