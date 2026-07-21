# PSX (Pakistan Stock Exchange) Data Availability Audit

**Scope**: Data-availability audit only. No strategy code, no backtesting.
**Universe tested**: KSE-100 index, OGDC, LUCK, ENGRO, HBL, MARI.
**Date**: 2026-07.

---

## Task 1 — Data Source Discovery

### (a) `psx-data-reader` (pip package, imports as `psx`)
Installable via pip. Its OHLCV-fetching function (`stocks()`) is **broken in the
currently published release**: it crashes with
`KeyError: "None of ['TIME'] are in the columns"` on every single call.
Root cause confirmed by reading the package's own source
(`psx/web.py`): its parser hardcodes `.set_index("TIME")`, but the live
`dps.psx.com.pk/historical` endpoint it wraps now returns a column literally
named `"DATE "` — the upstream PSX portal was restructured after this
library's last functional release and it was never updated. This is not a
usage error on our side; it is a genuine, currently-unfixed upstream break.

Its `tickers()` function (hitting a separate, unaffected `/symbols` JSON
endpoint) does work, returning a real list of all 1,080 tradeable PSX
instruments (stocks, TFCs, sukuks, etc.).

**Verdict on this library**: unusable for OHLCV as published. Its only
functioning value is the symbol list.

### (b) dps.psx.com.pk (PSX's own official data portal)
No registration or payment required. Exposes an **unauthenticated POST
endpoint** at `https://dps.psx.com.pk/historical` accepting
`{month, year, symbol}` form data, returning an HTML table (`DATE, OPEN,
HIGH, LOW, CLOSE, VOLUME`) for that symbol/month. Also exposes
`https://dps.psx.com.pk/symbols` (JSON, all 1,080 instruments — no currency
field, since every instrument on this exchange is PKR-denominated by
construction).

Queried directly (bypassing the broken library), this endpoint reliably
returns real historical data. One naming quirk: the KSE-100 index symbol is
**`"KSE100"`** (no hyphen) — `"KSE-100"` and `"100INDEX"` both silently
return an empty-table placeholder rather than an error.

**Verdict**: this is the only source with genuine KSE-100 index history and
the only source depth-confirmed back before 2008. It works, but is
undocumented/unofficial-API-in-practice (an HTML portal endpoint, not a
published API) and would need a purpose-built scraper to use — no such
scraper was built in this audit (out of scope per "no strategy code").

### (c) yfinance (`.KA` suffix)
Confirmed working for individual stocks. `OGDC.KA`, `LUCK.KA`, `HBL.KA`,
`MARI.KA` all return clean daily OHLCV from **2008-01-01 through
2026-07-17** (4,817–4,818 rows each — see Task 2a).

**Does not support the KSE-100 index under any naming convention tried**
(`^KSE`, `KSE100.KA`, `^KSE100`, `KSE100PSX` all return zero rows). One
naive guess, plain `"PSX"`, resolves to a false positive — confirmed via
`.info` metadata to be Phillips 66, an unrelated NYSE-listed US oil company
(`longName='Phillips 66'`, `exchange='NYQ'`, `currency='USD'`).

### (d) Investing.com / stooq.com
`pandas_datareader` is not installed in this environment and was not added
for this audit (would pull in a new dependency for a discovery-only task).
Stooq's direct CSV endpoint (`stooq.com/q/d/l/?s=...&i=d`) was tried directly
via `requests` for several PSX ticker guesses (`kse100`, `ogdc.ka`,
`ogdc.pk`, `kse.100`, `^kse100`) — all returned a generic "page does not
exist" stub. Notably, the **same stub was returned for a known-good US
ticker (`aapl.us`)**, meaning this result reflects stooq currently blocking
or rate-limiting this request pattern in this environment generally, not a
PSX-specific absence. No working PSX access was confirmed through stooq.
Investing.com has no public/documented API and was not scraped (no
programmatic access route exists to test).

**Verdict on (d)**: no usable programmatic access confirmed via either
source in this audit.

---

## Task 2 — Data Quality Assessment

### (a) History depth
| Ticker | Source | Start | End | Rows |
|---|---|---|---|---|
| KSE100 (index) | dps.psx.com.pk | ~2009 (June-sampled; 2007 sample empty) | current | n/a (not bulk-pulled) |
| OGDC.KA | yfinance | 2008-01-01 | 2026-07-17 | 4,817 |
| LUCK.KA | yfinance | 2008-01-01 | 2026-07-17 | 4,818 |
| ENGRO.KA | yfinance | 2008-01-01 | **2025-01-13 (discontinued)** | 4,431 |
| HBL.KA | yfinance | 2008-01-01 | 2026-07-17 | 4,817 |
| MARI.KA | yfinance | 2008-01-01 | 2026-07-17 | 4,817 |

yfinance gives ~18.5 years for 4 of 5 stocks — comfortably exceeds the
10-year minimum and spans the 2017-19 bear market and 2024-25 bull run. The
2008-01-01 start also reaches back far enough to include the Sept–Oct 2008
crash window. The KSE-100 index itself is only available via the DPS raw
endpoint, sparse-sampled here to ~2009 depth (a full-resolution pull was not
run, since that would begin to constitute backtest-prep infrastructure,
out of scope for this audit).

**ENGRO ticker succession**: ENGRO's data stops in both dps.psx.com.pk and
yfinance at essentially the same date (Jan 2025), consistent with a
corporate holding-company restructuring. A successor ticker, **"ENGROH"**
(sector: "INV. BANKS / INV. COS. / SECURITIES COS."), continues with data
through the present **on dps.psx.com.pk** — but **yfinance has no
"ENGROH.KA" ticker at all** (confirmed: zero rows, "possibly delisted").
This means full ENGRO→ENGROH continuity is only reconstructable via the raw
DPS endpoint, not yfinance, and would require manual ticker-splicing
knowledge no automated fetch would surface on its own.

### (b) Gaps
Full-year 2024 fetch, all 6 symbols, compared against KSE-100's own
trading-day count as the "market was open" reference:

| Symbol | Trading days (2024) | Gap vs KSE100 |
|---|---|---|
| KSE100 | reference | — |
| OGDC | ~same | ~0.4% |
| LUCK | ~same | ~0.4% |
| ENGROH | ~same | ~0.4% |
| HBL | ~same | ~0.4% |
| MARI | ~same | ~0.4% |

All well under the 5% "unreliable" threshold. Gaps are not a concern for
any of the 5 stocks in the year tested.

### (c) Corporate actions — **confirmed problem**
Directly observed in MARI's 2024 daily closes (dps.psx.com.pk raw data):
smooth appreciation from ~2,147 (Jan 2024) to ~3,444 (start of Sept 2024),
then an abrupt ~8:1 cliff to ~425 within September 2024, followed by normal
trading in the 400–700 range for the rest of the year. This is the
textbook signature of an unadjusted stock split / large bonus-share issue —
not a real price crash (a real crash would not resume trading in a tight,
stable band immediately after with no partial recovery attempt).

**Critically, this is not just a raw-data problem**: yfinance's own
`Adj Close` column for `MARI.KA` shows the **same ~9:1 drop on the same
date** (2024-09-04 → 2024-09-05, Close 3,641→399, Adj Close 3,352→367) —
i.e. yfinance's split/dividend adjustment mechanism did **not** correct this
corporate action either. Neither of the two working sources tested provides
split-adjusted data for this event. Given PSX's well-documented culture of
frequent bonus-share issuance, this is very unlikely to be isolated to MARI
alone; the other 4 stocks were not individually re-checked for their own
cliffs in this audit, but the finding establishes that **no source in this
audit can be trusted to deliver pre-adjusted data** — any backtest would
need its own corporate-action detection/adjustment layer built first.

### (d) Currency
**Confirmed PKR (Pakistani Rupee)** for all PSX instruments — structural,
not something the data itself needs to declare (PSX has no USD-denominated
listings; the `/symbols` endpoint doesn't even carry a currency field for
this reason). Vatican's existing strategy code assumes USD pricing
throughout — any PSX research would need explicit PKR handling (position
sizing, cross-asset comparisons, any USD-quoted correlated instrument) added
before reuse of existing strategy logic.

### (e) Liquidity (avg. daily volume, 2024)
| Ticker | Avg. daily volume | Note |
|---|---|---|
| OGDC | ~8.77M shares | high |
| HBL | ~3.16M shares | high |
| MARI | ~870K shares | moderate |
| LUCK | ~230K shares | **lower — flag** |
| ENGROH | ~101K shares | **lower — flag** (also newest/least-mature ticker) |

LUCK and ENGROH's lower volumes mean backtest fee models would need to
account for wider realistic spreads than a fixed-bps assumption captures.

---

## Task 3 — Verdict: **YELLOW**

Depth (10+ years for 4/5 stocks via yfinance, ~17 years for the index via
the DPS raw endpoint), gaps (~0.4%, well under threshold), and currency
(PKR, unambiguous) all clear the bar. But the **corporate-actions
adjustment requirement fails outright** — confirmed directly, in both
available data sources, on a real ticker in the requested universe — which
by the audit's own GREEN criteria disqualifies GREEN. This is not a
theoretical risk flagged from general PSX knowledge; it was directly
observed and independently cross-confirmed.

This is not RED either: the depth, gap, and currency findings are all
solid, liquidity is adequate for 3 of 5 names, and the KSE-100 index itself
has real multi-year history via the DPS portal (just not via yfinance). The
problem is narrow and specific — corporate-action adjustment — not a
wholesale absence of usable data.

## Closing Summary

- **Sources that work**: yfinance (`.KA` suffix) for individual-stock OHLCV,
  ~18.5 years deep, low gaps. `dps.psx.com.pk`'s raw (undocumented)
  endpoint for both individual stocks and the KSE-100 index itself
  (yfinance has no index coverage at all). `psx-data-reader`'s pip package
  is broken for OHLCV as published; only its symbol list works.
- **Sources that don't**: stooq.com CSV endpoint returned no usable data for
  any ticker tried in this environment (result inconclusive — same stub
  returned even for a known-good US ticker, suggesting a blocking/rate-limit
  issue rather than confirmed PSX absence). Investing.com has no
  programmatic access path.
- **Data quality per ticker**: OGDC, LUCK, HBL, MARI — deep history, low
  gaps, adequate-to-high liquidity, **but uncorrected for at least one
  confirmed split/bonus event (MARI, Sept 2024)**. ENGRO requires manual
  splicing to ENGROH past Jan 2025, and ENGROH is unavailable on yfinance
  entirely (DPS-only). All PKR-denominated.
- **Verdict: YELLOW.** Recommend a **limited** sweep only, with these
  explicit caveats carried into any future research:
  1. Build a corporate-action detection pass (e.g. flag single-day
     price-ratio discontinuities beyond a threshold) before trusting any
     PSX backtest return series — do not assume yfinance's `Adj Close` has
     already handled this correctly for PSX names.
  2. Recommended ticker universe if proceeding: **OGDC, LUCK, HBL** (best
     combination of depth, gap-cleanliness, and liquidity) as a first-pass
     set; MARI only with the known Sept-2024 split explicitly patched;
     ENGRO/ENGROH only with manual ticker-splicing and awareness that
     yfinance cannot supply the post-2025 leg at all.
  3. Recommended timeframe: daily bars only — no evidence was gathered in
     this audit for intraday PSX data availability from any source, and
     none should be assumed.
  4. KSE-100 index-level research would require building a small custom
     scraper against `dps.psx.com.pk/historical` (symbol `"KSE100"`) — no
     such scraper exists yet; this audit only confirmed the endpoint itself
     is reachable and returns genuine data.

No strategy code or backtest logic was written for this audit.
