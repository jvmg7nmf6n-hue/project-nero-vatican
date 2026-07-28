# Infrastructure Notes: GitHub Actions as the Scheduling Backbone

Why Vatican runs on GitHub Actions cron rather than a paid VPS/scheduler, what that
choice costs, and what would actually justify paying for something else. Written so
this doesn't get re-litigated from scratch every time a scheduling bug surfaces (see
the 2026-07-28 PEAD/24h+1week `candle_boundary_due` tolerance bug and the
2026-07-29 follow-up covering "12h"/`daily_time_due` and the Binance klines 451
bug — both are case studies in this doc, not separate incidents to re-investigate).

## Why GitHub Actions

- **Free**, and this project is a public repo — Actions minutes are unlimited on
  the free tier for public repos (confirmed directly against the GitHub API, not
  assumed). There is no minutes budget to protect, which is why the redundant
  trigger design below can afford to be generous with extra cron entries.
- **Zero infrastructure to operate.** No server to patch, no uptime to monitor
  separately from the workflow's own run history, no SSH key to rotate. The Truth
  Ledger (`data/truth_ledger.db`) and every exported JSON already live in the git
  repo itself, so "the infrastructure" and "the audit trail" are the same
  artifact — a `git log` on `data/truth_ledger.db` is a deployment history too.
- **Already proven at the append-only-ledger design this project depends on.**
  Every write path (`execution_log`, `execution_metadata`, `news_sentiment_log`,
  `orderbook_snapshots`) is insert-only with a `UNIQUE` constraint as a second
  line of defense behind the application-level "already logged" cursor (see
  `nero_core/truth_ledger/execution_log.py`'s own module docstring). That design
  was *necessary* to make a fundamentally unreliable trigger source (see below)
  safe to run redundantly — it isn't a coincidence that both exist together.

## The real cost: GitHub Actions `schedule` is genuinely unreliable

This is not a theoretical caveat — it's measured directly from this project's own
`execution_metadata` history. The live scheduler's cron fires every 30 minutes
(`"3,33 * * * *"`), which nominally means 48 runs/day. Querying real run
timestamps across 11 observed days showed only **11–18 actual runs/day (23–37%
of nominal)** — GitHub Actions is *dropping* the large majority of scheduled
ticks under load, not merely delaying them. GitHub's own docs acknowledge this
("the schedule event can be delayed during periods of high load... the workflow
will not run"), and it's worst at exactly the globally-popular top-of-hour and
midnight-UTC marks every default-configured cron job on the platform converges
on.

This single fact is the root cause behind two real incidents:

1. **2026-07-28**: `candle_boundary_due`'s 40-minute default tolerance assumed
   "some run will land near the boundary." Combined with the drop rate above,
   "24h"/"1week"-gated strategies (including GOLD/1week/BREAKOUT_MOMENTUM, this
   project's own flagship SURVIVOR) went 10+ days without a single evaluation.
   Fixed by widening tolerance to `SINGLE_SHOT_TOLERANCE_MINUTES` (240min) for
   gates with no same-day redundancy.
2. **2026-07-29**: the same pattern recurred for "12h" (`MULTI_SHOT_TOLERANCE_
   MINUTES`, 150min) and `daily_time_due` (reused 240min) — different gates,
   same underlying cause. See `nero_core/execution/candle_schedule.py`'s own
   docstring for the full numbers.

**A wide tolerance window is necessary but not sufficient.** It only helps if
*some* run actually lands inside it — and at a 23–37% completion rate, that
isn't guaranteed by the standing 30-minute cadence alone, especially for a
single-shot gate whose entire multi-hour window could plausibly see zero
completed runs on a bad day.

## The mitigation: redundant triggers, not just wide tolerance

Rather than trusting the steady-state cadence to eventually land inside each
gate's tolerance window, `.github/workflows/live_scheduler.yml` layers 3 extra
high-frequency cron entries (every ~10 minutes) on top of the standing 30-minute
one, scoped ONLY to the exact UTC windows the fragile gates can fire in:
00:00–03:59 (24h/1week + 12h AM), 12:00–14:29 (12h PM), 19:00–22:59
(`daily_time_due`, NEWS_SENTIMENT). Every run outside its own gate's window still
costs nothing beyond the free runner-minute — `candle_boundary_due`/
`daily_time_due` correctly report `NOT_DUE` and no third-party fetch ever
happens, so this doesn't add pressure to any rate-limited data source
(Twelve Data, yfinance) outside those windows.

This is safe specifically *because* the ledger is idempotent two layers deep:

- **Application layer**: `nero_core/execution/replay.py`'s replay functions only
  emit a `ReplayEvent` for a candle strictly after `already_logged_close_time_ms`
  — a redundant run re-fetches and re-replays, but silently produces zero new
  events for anything already logged.
- **Database layer**: `execution_log` has
  `UNIQUE (asset, strategy, strategy_version, candle_timestamp, signal_type)`;
  `insert_execution_log_row` catches the resulting `sqlite3.IntegrityError` and
  returns `None`, never raising. `news_sentiment_log` has the analogous
  `UNIQUE (asset, fetch_timestamp)` behind its own `has_news_sentiment_logged_
  today` pre-check.

Both layers were already in place and already tested
(`tests/test_execution_log.py::test_duplicate_signal_for_same_candle_is_a_no_op_
not_an_error`, `tests/test_live_scheduler.py::
test_running_twice_with_identical_data_produces_no_duplicate_rows`) before this
task — redundant triggers were a safe addition, not a design change that
required them to be introduced first.

## A separate, unrelated reliability gap found along the way

Auditing data-source freshness for this task surfaced a real, independent bug:
`nero_core/data_sources/market_data.py`'s Binance klines fetch hit
`api.binance.com` directly, which returns HTTP 451 to GitHub Actions' US-based
runner IPs for public market data. BNB has no Coinbase/Kraken fallback, so this
was a 100% failure rate on every gate-satisfied fetch — confirmed directly from
production history, not inferred. `nero_core/data_sources/orderbook_data.py` had
already solved the identical problem for the order-book depth endpoint by
routing through `data-api.binance.vision` first; that same fix was applied to
the klines fetch. This is called out here because it's the same *class* of
lesson as the scheduling bugs above: GitHub Actions' hosted-runner environment
has real, non-obvious constraints (dropped cron ticks, US-IP-restricted public
APIs) that only show up under actual production conditions, not local testing.

## What would trigger a move to paid infrastructure

None of these conditions hold today. This list exists so a future decision to
move off GitHub Actions is made against concrete evidence, not vibes:

- **The redundant-trigger mitigation stops being enough.** If a future health
  check run shows a gate going stale *despite* the burst schedule already
  covering its window (i.e., GitHub Actions' drop rate gets meaningfully worse,
  or a window needs sub-10-minute precision the burst schedule doesn't provide),
  that's a signal the free scheduler has hit its ceiling.
- **Sub-minute or guaranteed-latency execution becomes a real requirement.**
  Nothing in the current strategy roster needs this — every gate's own tolerance
  is measured in tens of minutes to hours by design (see `candle_schedule.py`).
  A strategy that genuinely needed second-level timing would need a different
  execution model entirely, not just a different scheduler.
- **This project stops being a public repo.** The "Actions minutes are free"
  assumption this whole redundant-trigger design leans on is specifically a
  public-repo benefit. Going private reintroduces a real minutes budget
  (2,000 min/month on GitHub's Free plan) that the burst schedule's extra ~30
  runs/day would meaningfully eat into, and the tradeoff would need
  re-evaluating.
- **A genuinely persistent process becomes necessary** — e.g. `ORDERFLOW_
  IMBALANCE` graduating from REST-polling to a real WebSocket order-book
  collector (already flagged as future work in
  `nero_core/strategies/orderflow_imbalance.py`'s own module docstring: "a
  persistent WebSocket connection is not something [GitHub Actions cron]
  infrastructure can host"). A scheduled job fundamentally cannot hold a
  long-lived connection open between runs; a VPS/small always-on process can.
- **The data-source rate-limit findings from this task's Task 2 audit
  materialize into real failures.** Currently latent (zero observed 429s in 143
  real runs): no in-run caching means GOLD/1week is independently re-fetched up
  to 3 times per run (once per SINGLE_ASSET_CONFIGS entry sharing that asset/
  timeframe), and PEAD's 7 tickers × 2 threshold configs means each ticker's
  OHLCV+earnings data is fetched twice. If Twelve Data or yfinance rate-limiting
  starts actually rejecting requests, the first fix is an in-run cache (cheap,
  no infrastructure change) — only if that's insufficient would third-party
  rate limits themselves become an infrastructure-change trigger.

Until one of these becomes true, GitHub Actions + redundant triggers + an
idempotent ledger is the right tool: free, transparent (every run's outcome is
a git-tracked JSON export), and — with the fixes in this task — now
resilient to the specific failure mode (dropped/delayed cron ticks) that
actually caused real incidents so far.
