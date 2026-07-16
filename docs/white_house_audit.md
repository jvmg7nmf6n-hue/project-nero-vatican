# White House / Policy Event-Impact System — Data Audit

Scope: audit only. No trading strategy, no registry entry. `nero_core/macro_policy/`
ports the scoring/classification/enrichment code as-is; this document audits the
**data** that code is meant to run on before any of it feeds a backtest.

Source studied (read-only): `C:\Users\HP\Documents\Codex\2026-07-06\tu`
Ported into (this repo): `nero_core/macro_policy/white_house_sources.py`,
`white_house_dataset_builder.py`, `white_house_impact.py` — Jaccard-similarity scoring
and forward-return enrichment logic unchanged; only import paths and default file
locations (`nero_app/data/...` → `data/...`) were adapted.

---

## (a) Historical event dataset contents

**Location audited:** `nero_app/data/white_house_market_events.csv` (original NERO).
This file was **not** copied into this repo — see (d) for why.

- **Count:** 7 events (one header row + 7 data rows).
- **Date range:** 2021-01-20 to 2025-07-18 (~4.5 years, 7 events — roughly one every
  8 months on average, clearly not a systematic full record).
- **Categories** (`event_type` column): `regulatory_freeze` (1), `sanctions_geopolitics`
  (1), `crypto_policy` (4), `crypto_legislation` (1).
- **Tags observed** (`tags` column, pipe-delimited, used by the Jaccard classifier):
  `crypto_regulation`, `policy_uncertainty`, `administration_transition`, `sanctions`,
  `war`, `geopolitical_risk`, `risk_off`, `safe_haven`, `oil_supply_risk`,
  `policy_clarity`, `cbdc`, `consumer_protection`, `policy_hostile`, `bank_custody`,
  `institutional_friction`, `crypto_friendly_policy`, `anti_cbdc`,
  `regulatory_framework`, `strategic_bitcoin_reserve`, `institutional_legitimacy`,
  `structural_adoption`, `stablecoin_legislation`.

**Timestamp granularity: date only (`YYYY-MM-DD`), no time-of-day, no timezone.**
There is no separate field distinguishing "when the event happened" from "when it
became public knowledge" from "when this row was added to the CSV." All 7 rows were
evidently curated in one retrospective pass (the file has no revision history inside
it, and the last row is annotated by the original author as `"Seed row; exact official
URL/returns should be refined during data ingestion"` — an explicit admission that even
the date/URL/return values for that row are placeholders, not verified).

**Concrete data-quality finding, not just a documentation gap:** I compared the raw seed
CSV against the committed "enriched" output
(`reports/white_house_market_events_enriched.csv`) row by row. Every `btc_*` column
(`btc_return_1d/7d/30d`, `btc_impact_score`, `btc_price_at_event`) is **byte-identical**
between the seed and the "enriched" file. Only the `gold_*` columns actually changed
(and gold's enriched prices are realistic non-round decimals like `1870.90625`, vs. the
seed's suspiciously round `btc_price_at_event` values like `35500`, `90000`, `120000`).
I confirmed the mechanism in `enrich_events_with_returns`: if `btc_prices` is `None`,
the function skips BTC entirely and returns the input columns untouched — it was
**never actually run against real BTC price data**, only against a gold price series
(one that isn't present anywhere in the repo — see (d)). A regression test
(`test_enrich_events_with_only_one_asset_leaves_the_other_untouched`) is now in this
repo's suite proving that pass-through behavior, so this isn't a one-off reading error.
**Practical conclusion: every BTC return/impact number in this seed dataset is an
illustrative placeholder, not a measured value.** Only the gold numbers reflect an
actual (now-unreproducible) computation.

## (b) Data sources

`white_house_sources.py` defines four fetch targets, all plain unauthenticated `GET`
requests (a `User-Agent` header is set; no API key, no auth token, anywhere):

| Source | URL | Live today? |
|---|---|---|
| White House Briefing Room | `https://www.whitehouse.gov/briefing-room/` | Yes — HTTP 200 |
| GovInfo Presidential Documents | `https://www.govinfo.gov/app/collection/CPD` | Yes — HTTP 200 |
| American Presidency Project | `https://www.presidency.ucsb.edu/` | Yes — HTTP 200 |
| Biden White House Archive | `https://bidenwhitehouse.archives.gov/briefing-room/` | Yes — HTTP 200 |

Checked with one polite request per URL (1s spacing between requests, no retries, no
polling) on 2026-07-17. All four returned HTTP 200 directly, no redirects.

**No API key is required for anything in `white_house_sources.py`,
`white_house_dataset_builder.py`, or `white_house_impact.py`.** Classification is pure
keyword substring matching (`TAG_KEYWORDS`) plus Jaccard set similarity — no LLM call
anywhere in this subsystem. For contrast: this codebase's `GEMINI_API_KEY` env var
*is* used elsewhere in the original NERO source (`ai_sentiment.py`,
`prediction_lab.py`) — but never by the White House module. (Referencing the name only,
per policy — its value was never read or printed.)

## (c) Lookahead-bias assessment

**A bias-free event backtest is not possible with this data as it stands today.**
Specific gaps, in order of how much they'd actually corrupt a backtest:

1. **Selection bias dwarfs timestamp bias.** 7 hand-picked events over 4.5 years,
   curated in one retrospective pass, is not a systematic sample — it looks like
   "events someone already knew mattered" rather than "every qualifying White House
   communication in the window." A model trained or backtested against tags on these 7
   events is partly backtesting the curator's hindsight, not a discoverable signal.
2. **The BTC ground truth is fabricated (see (a)).** Even ignoring timing, a backtest
   using these BTC return/impact numbers would be fitting to illustrative placeholders,
   not real market reactions. This alone blocks any BTC-side conclusion until the
   dataset is rebuilt against a real price feed.
3. **No intraday timestamp.** `_price_on_or_after` (the enrichment join) picks the
   first price row with `date >= event_date` — implicitly treating the event as known
   before that day's close. A White House action announced at 6pm ET the same
   calendar day would already be "priced in" to that day's close under this scheme,
   silently converting a same-day reaction into what looks like a forward return,
   or vice versa for a pre-market announcement. Without knowing whether an event
   happened at 9am or 9pm, you cannot correctly anchor the "reaction window."
4. **"Recorded" vs. "public" time is conflated implicitly.** The `date` column reads as
   the event/action date (cross-checked against the dated government URLs, e.g. an
   executive order's URL path matches its `date` column), which is a reasonable proxy
   for "became public" for signed EOs and same-day press releases — but this is an
   inference from the URL, not a modeled distinction, and would not hold for events
   discovered/reported with a lag (e.g. a leaked policy stance later officially
   confirmed).

**What would be needed to make this bias-free:**
- A systematic, not hand-picked, event collection — every qualifying release from the
  four official sources in a defined window, tagged the same way, whether or not it
  turned out to move price (this is what `white_house_sources.py`'s snapshot fetcher is
  a first step toward, but it only surfaces a link snapshot — it does not yet
  automatically ingest new tagged, dated, priced events into the seed CSV).
- Real publish timestamps (ideally to the minute, with timezone) — the govinfo/
  whitehouse.gov pages do carry publish dates; the actual time-of-day would need
  scraping from the page or a wire-service pickup timestamp, not just the calendar date
  currently stored.
- Actual BTC and Gold price series re-joined through `enrich_events_with_returns` with
  both `btc_price_path` and `gold_price_path` supplied, so every return/impact number is
  freshly computed and verifiable, not carried over from hand-entered placeholders.
- Ideally intraday (hourly or finer) price data so the reaction window starts from the
  correct candle relative to the actual announcement time, not the next available daily
  close on or after the calendar date.

## (d) Data storage

- **Original NERO:** `nero_app/data/white_house_market_events.csv` is a small
  (~2 KB, 7 rows), hand-curated file **committed to the repo** — it is not built or
  fetched at runtime. `white_house_sources.py`'s `fetch_source_snapshot` only produces a
  snapshot of *recent links* found on the four official sites (for a human to review);
  nothing in the ported code automatically turns a fetched link into a new tagged,
  priced row in the seed CSV — that step is manual/curatorial today.
- **`reports/white_house_market_events_enriched.csv` and
  `reports/white_house_impact_summary.csv`** are generated outputs of
  `tools/nero_white_house_dataset.py`, committed as example artifacts — but, per (a),
  **not reproducible from what's in the repo**: no BTC or Gold price CSV exists
  anywhere in `nero_app/data/` or `reports/`, so whoever produced these committed files
  must have pointed the builder at an external gold price file that was never
  committed, and never supplied a BTC price file at all.
- **This repo (project-nero-vatican):** the 7-event seed CSV was **not** copied over.
  `nero_core/macro_policy/white_house_dataset_builder.py`'s
  `DEFAULT_INPUT_PATH = Path("data/white_house_market_events.csv")` does not exist yet —
  `load_event_memory`/`load_white_house_events` will return an empty DataFrame until a
  real dataset is built. This is intentional: porting a dataset with the (a)/(c)
  problems above as if it were ready-to-use would misrepresent its reliability.

## Bottom line

The code (Jaccard classifier, forward-return enrichment, source snapshot fetcher) is
straightforward to port and is now ported with tests. The **data** is not ready for a
backtest: it's a 7-row hand-picked seed with date-only timestamps, an explicit
"unrefined" placeholder row, and BTC return/impact numbers that were never actually
computed against real BTC prices. Building a real strategy on top of this today would
be backtesting illustrative numbers, not a market signal. No strategy work should start
here until the dataset itself is rebuilt per the "what would be needed" list in (c).
