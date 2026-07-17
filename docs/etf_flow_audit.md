# ETF Flow Data Audit

## Purpose

Before building an ETF-flow-based strategy, investigate whether reliable, free,
historical BTC/Gold ETF flow data (daily net inflow/outflow in USD) is actually
obtainable with a known publication timestamp — publication timing is the critical
fact for lookahead-safety, since a flow strategy that uses a number before it was
actually public would be trading on data it couldn't have had.

**Conclusion up front: not feasible to source reliably for free with known publication
timing. ETF Flow is marked "blocked on data," same as Event Shock, and no strategy is
built on it.** Findings below support that conclusion.

## (a) Farside Investors (farside.co.uk)

Farside publishes daily Bitcoin ETF flow tables (IBIT, FBTC, BITB, ARKB, GBTC, and
others) going back to the January 2024 spot-ETF launch — this is the most widely cited
source for this data.

- A direct fetch of `farside.co.uk/btc/` and `farside.co.uk/bitcoin-etf-flow-all-data/`
  both returned **HTTP 403 Forbidden** (bot-protection, not a data-availability issue —
  the site is up and human-browsable, it blocks automated requests).
- No official CSV/API export from Farside itself was found. The only "free API" found
  in a search is a **third-party, unofficial wrapper** (a "Parse" marketplace listing)
  that scrapes Farside's page and re-serves it as JSON. This is not an API Farside
  publishes, documents, or supports — it inherits every risk of screen-scraping (no
  SLA, breaks silently on any HTML change, uncertain ToS standing) plus an extra layer
  of trusting a third party's scraper to keep working.
- Publication timing is not documented anywhere I could reach (blocked by the 403).
  Industry practice for these tables is that a day's flow is derived from that day's
  after-close shares-outstanding change and appears on Farside the *next* business
  day, but this is inference, not a sourced fact — not something to build a
  lookahead-safety guarantee on.

## (b) Free API/CSV endpoints for IBIT/FBTC/GBTC/GLD/IAU flows or shares-outstanding history

- **CoinGlass** has a documented `ETF Flows History` API endpoint
  (docs.coinglass.com/reference/etf-flows-history) providing daily net flow in USD.
  Its own documentation states this endpoint requires a paid plan (Hobbyist tier and
  up) — **no free tier confirmed** for historical ETF flow data. Even on a paid plan,
  CoinGlass is a third-party redistributor; the pages I could reach did not document
  its own publication-lag methodology.
- A direct fetch of the official iShares IBIT fund page
  (`ishares.com/us/products/333011/...`) — the primary source a fund's own
  shares-outstanding/flow number would come from — also returned **HTTP 403
  Forbidden**. Each fund sponsor (BlackRock/iShares for IBIT & IAU, Fidelity for
  FBTC, Grayscale for GBTC, State Street for GLD) publishes on its own site, in its
  own format, with no unified API across sponsors — reconstructing flows from primary
  sources would mean five separate bespoke scrapers with none of them confirmed
  reachable, and no single documented publication-timing standard across issuers.
- No other free, documented, historical ETF-flow or shares-outstanding API was found
  in this search that isn't one of the above (paid, or an unofficial scraper wrapper).

## (c) yfinance / Twelve Data for shares-outstanding or AUM history

- **yfinance**, tested directly (not inferred): `Ticker.get_shares_full()` — the one
  method yfinance exposes for a historical shares-outstanding time series — was run
  against GLD, IAU, FBTC, and GBTC for a 2024-01-01 to 2024-03-01 window:
  - `AAPL` (control, a regular stock): returned 14 real data points — confirms the
    method itself works as expected for equities.
  - `GLD`, `IAU`, `FBTC`: returned `None` — **no share-count history at all.**
  - `GBTC`: returned exactly **1** data point for the entire 2-month window — not a
    usable daily (or even weekly) time series.
  - Conclusion: yfinance does not provide usable ETF shares-outstanding history for
    any of these five tickers.
- **Twelve Data**: its full documented endpoint list was enumerated directly
  (twelvedata.com/docs) — it has an "ETFs" category, but that only covers `ETF
  directory`, `Full data`, `Summary`, `Performance`, `Risk`, `Composition`, `ETF
  families`, `ETF types`. **There is no fund-flow, shares-outstanding-history, or
  AUM-history endpoint anywhere in Twelve Data's API surface.** This is consistent
  with Twelve Data's role in this project as a price/quote source, not a fund-flow
  source.

## Feasibility verdict

| Source | Free? | Historical depth | Publication timing documented? | Verdict |
|---|---|---|---|---|
| Farside (direct) | blocked (403) | unknown (site inaccessible to fetch) | no | Not usable |
| Farside (unofficial 3rd-party API wrapper) | yes | since Jan 2024 (per wrapper's own claim) | no | Not usable — scraping-of-a-scraper, no SLA/ToS standing |
| CoinGlass ETF Flows History API | no (paid tier required) | undocumented in reachable pages | no | Not usable — paid, and not proven built here |
| Official fund sponsor sites (iShares, Fidelity, Grayscale, State Street) | blocked (403) / no unified API | unknown | no | Not usable — 5 bespoke scrapers, none confirmed reachable |
| yfinance `get_shares_full` | yes | confirmed empty/unusable for GLD, IAU, FBTC; 1 point for GBTC | n/a | Not usable — tested directly, no data |
| Twelve Data | yes (existing subscription) | n/a — endpoint doesn't exist | n/a | Not usable — no such endpoint |

No path in this audit produces a free, reliable, historical ETF-flow (or
reconstructible-from-shares-outstanding) dataset with a documented publication
timestamp. Building a strategy on the one technically-free option (the unofficial
Farside-scraping wrapper) would mean depending on an unsupported, ToS-uncertain
scrape of a scrape, with no way to honestly state when a given day's number became
public — i.e. exactly the "unreliable scraping" this audit was told to avoid.

**ETF Flow is marked BLOCKED ON DATA, same status as Event Shock. No ETF Flow
strategy is built.**
