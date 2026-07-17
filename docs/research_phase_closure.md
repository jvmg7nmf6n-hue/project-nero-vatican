# Research-Phase Closure — Testing-Phase Status Inventory

Status of every macro/sentiment-adjacent data source and strategy investigated in this
research phase, as of this closure note: **News Sentiment is forward-only by design**
(no historical dataset with a trustworthy backdated timestamp exists for it, so it is
scoped to live/forward use only, never backtested against fabricated history);
**Event Shock is blocked on data** (no reliable historical event-timing source was
found); **ETF Flow is blocked on data** (see `docs/etf_flow_audit.md` — Farside blocks
automated fetches, the only free option is an unofficial third-party scraper wrapper
with no documented publication timing, CoinGlass's flow API is paid-only, official fund
sponsor sites are also unreachable and have no unified API, and yfinance/Twelve Data
were confirmed directly to carry no usable ETF flow or shares-outstanding history — no
strategy was built); and **MACRO_RISK_ON was built and fully tested** (dollar-proxy +
FRED DFII10 regime strategy, `nero_core/strategies/macro_risk_on.py`, registered as
`macro-risk-on-v1.0.0`) but **did not pass the strict positive-both-halves filter on
either BTC or GOLD** (see `docs/macro_risk_on_report.md` — BTC's expectancy flips from
+0.191R train to -0.140R test; GOLD's train half is itself negative at -0.019R), so it
remains registered and tested but is not a qualifying strategy at this time.
