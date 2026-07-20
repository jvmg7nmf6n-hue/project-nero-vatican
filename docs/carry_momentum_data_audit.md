# CARRY_MOMENTUM — Data Audit

**Result: ALL CLEAR.** 8/8 currencies, 7/7 forex pairs.

## FRED policy-rate / short-yield series — verified live, not assumed

Every candidate series ID was queried against the live FRED API before being
chosen (`nero_core/data_sources/fred_rates.py`'s module docstring has the full
candidate list and rejection reasons). Three currencies have a genuine daily
central-bank/overnight rate; the other five have no daily FRED series at all, so
a documented monthly OECD interbank-rate substitution is used instead:

| Currency | Series | Frequency | Substitution? |
|---|---|---|---|
| USD | DFF (Federal Funds Effective Rate) | Daily | No |
| EUR | ECBDFR (ECB Deposit Facility Rate) | Daily | No |
| GBP | IUDSOIA (SONIA) | Daily | No |
| JPY | IR3TIB01JPM156N (OECD 3-month interbank) | Monthly | **Yes** — INTDSRJPM193N and IRSTCB01JPM156N tested and rejected as stale (last updated 2019/2024) |
| CHF | IR3TIB01CHM156N (OECD 3-month interbank) | Monthly | **Yes** — no other CHF series found on FRED |
| AUD | IR3TIB01AUM156N (OECD 3-month interbank) | Monthly | **Yes** — IRSTCI01AUM156N also current; 3-month chosen for cross-currency consistency |
| NZD | IR3TIB01NZM156N (OECD 3-month interbank) | Monthly | **Yes** — IRSTCI01NZM156N tested and rejected as stale (last updated 2025-01) |
| CAD | IR3TIB01CAM156N (OECD 3-month interbank) | Monthly | **Yes** — IRSTCB01CAM156N tested and rejected as stale (last updated 2024-01) |

Live fetch confirmed all 8 currently resolve with real, current data (e.g. USD
DFF: 26,315 daily observations back to 1954-07-01, last value 3.63%; JPY
IR3TIB01JPM156N: 290 monthly observations back to 2002-04-01, last value 1.27%).

## Publication lag

Daily series: `DAILY_LAG_BUSINESS_DAYS = 2` (matches `macro_data.py`'s own DFII10
precedent). Monthly series: `MONTHLY_LAG_DAYS = 90`, a deliberately conservative
buffer — confirmed empirically via each series' own `last_updated` vs
`observation_end` metadata that these OECD interbank series lag MORE than one
month in practice (JPY's worst-observed case: an observation dated 2026-05-01
was still the newest available as of a 2026-07-16 refresh, a ~2.5-month lag).
90 days safely covers even that worst case with margin.

## Forex pairs

All 7 pairs (EUR/USD, GBP/USD, USD/JPY, USD/CHF, AUD/USD, NZD/USD, USD/CAD)
confirmed accessible via Twelve Data, native 1day, ~19 years of history each
(N=4999, capped by the API's own per-request limit). Confirmed directly that all
7 pairs share the same close_time convention (same vendor, unlike GOLD/SILVER's
cross-vendor 4-hour offset in Hypothesis 1) — an exact close_time join is
correct here, no date-based alignment needed.

**Verdict: not blocked. Proceeding to strategy build.**
