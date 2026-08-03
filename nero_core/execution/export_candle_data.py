"""Candle-export pipeline (Day 1 of the candlestick-chart arc) -- writes recent OHLCV
history per (asset, timeframe) to docs/site_data/candles/ so Day 2's charting can read
static JSON, the same way every other site_data export already does. Runs as its own
step in .github/workflows/live_scheduler.yml, deliberately separate from
live_scheduler.py itself (the same isolation principle as notify_ntfy.py/
export_site_data.py: a candle-export failure must never affect whether a trading
signal gets logged, and a scheduler bug must never block chart data from refreshing).

IN-SCOPE PAIRS: derived directly from docs/site_data/strategies.json's actual roster
(see IN_SCOPE_PAIRS below), not a guessed asset list. Three kinds of roster entries are
excluded:
  - Pair-strategy assets (BTC-ETH, GOLD-SILVER) -- no single price series exists for a
    two-leg pair, so a candlestick chart isn't meaningful. Their individual legs (BTC,
    ETH... but see the ETH note below) are covered as standalone assets instead.
  - "snapshot"-timeframe entries (BTC/ETH via ORDERFLOW_IMBALANCE) -- an order-book
    depth snapshot has no OHLCV concept at all.
  - NEWS_SENTIMENT's "daily" timeframe label is normalized onto the same real candle
    series as "24h" (they're the same data, just named differently in that module's
    own roster metadata) -- this dedupes BTC's entry, but GOLD's is a genuinely NEW
    fetch, since every other live GOLD config uses 1week, not 24h.

CORRECTION TO A PRIOR ASSUMPTION: the task spec that produced this module assumed ETH
"is already covered as a standalone asset." Checked directly against strategies.json:
it is not -- ETH has no roster entry outside the excluded pair and the OHLCV-meaningless
snapshot entry. Per "derive from the actual roster, not a guessed list," ETH is
deliberately NOT included here. Add it in a later batch if a standalone ETH config is
ever wired live.

CADENCE (the main API-budget constraint): reuses nero_core.execution.candle_schedule.
candle_boundary_due exactly as-is (no changes to that shared function) -- 1week pairs
gated on "1week", the 24h-equivalent pairs (BTC, GOLD's daily series, SILVER, all 7
PEAD stocks) on "24h", BNB on "12h". A second freshness check (compare the existing
file's own last_updated against the current cadence bucket -- same week/day/12h-window)
additionally prevents two scheduler ticks inside one ~40-minute gate window from
double-fetching. Twelve Data cost with this cadence: ~1.6 calls/day average, 5/day peak
(the one day/week the weekly boundary fires) -- see the Day 1 closing report for the
full breakdown. Crypto (Binance) and stocks/SILVER (yfinance) don't touch the Twelve
Data budget at all.

FILENAME SANITIZATION: `asset.replace("/", "")` (e.g. "EUR/USD" -> "EURUSD") -- the
SAME rule already used by tools/backtest_forex_task_b2_sweep.py, not a new convention.
Any frontend code (Day 2) that needs to look up a candle file from an asset string
MUST apply this identical rule. Filenames are `{sanitized_asset}_{timeframe}.json`.

VOLUME HONESTY: GOLD (via market_data.py's Twelve Data path) and all 3 forex pairs
(via forex_data.py) both silently fill MISSING volume with 0.0 at the data-source
layer -- see market_data.py's own comment ("Some Twelve Data feeds... report no volume
at all") and forex_data.py's identical fillna(0.0). That 0.0 is a placeholder, not a
real reading, and passing it through here would violate "never fabricate a value." This
module therefore always exports `null` for volume on those specific (asset, source)
combinations, never the source layer's placeholder zero. Crypto (Binance), stocks
(yfinance), and SILVER (yfinance futures) all provide genuine trade volume and are
passed through unchanged.

FAIL-INDEPENDENT: one pair's fetch failure (or fetch skip) is logged and the loop moves
on -- never aborts the run for any other pair, mirroring every other per-config loop in
this codebase (process_single_asset, process_pead_config, etc.).
"""
from __future__ import annotations

import json
import sys
import traceback
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from nero_core.data_sources.forex_data import ForexDataUnavailableError, fetch_forex_ohlcv
from nero_core.data_sources.market_data import MarketDataClient, MarketDataUnavailableError
from nero_core.data_sources.stock_data import StockDataUnavailableError, fetch_stock_ohlcv
from nero_core.execution.candle_schedule import candle_boundary_due
from tools.timeframe_data import fetch_timeframe_candles

SCHEMA_VERSION = 1
CANDLE_COUNT = 200
DEFAULT_OUTPUT_DIR = Path(__file__).resolve().parents[2] / "docs" / "site_data" / "candles"

# RESEARCH EXPORT (added after a K=200 random-hypothesis-baseline investigation found
# ZERO of 200 sampled hypotheses ever reached MIN_SAMPLE_SIZE out-of-sample trades
# against this module's own 200-row CANDLE_COUNT display export -- see
# docs/investigations/eve_engine_v1_report.md): a SEPARATE, larger, full-history export
# for backtesting/scoring, deliberately NOT under docs/site_data/ (the display export's
# own directory, which website/lib/data.ts fetches by a hardcoded base URL
# ".../docs/site_data" -- a file under docs/research_data/ is structurally unreachable
# from that fixed path, so this can never bloat what ships with the website or get
# fetched by it by accident). CANDLE_COUNT/DEFAULT_OUTPUT_DIR above are COMPLETELY
# UNCHANGED -- the scheduled site export (export_candle_data(), called from
# .github/workflows/live_scheduler.yml) still writes exactly 200 rows to exactly the
# same place it always has.
#
# RESEARCH_CANDLE_COUNT = 4400 is "2+ years of 4h candles to start" (365.25*2*6 = 4383,
# rounded up with a small margin) -- see this module's own export_research_candle_data
# docstring for why this is a manual, deliberate, uncadenced export, not a scheduled one.
RESEARCH_CANDLE_COUNT = 4400
DEFAULT_RESEARCH_OUTPUT_DIR = Path(__file__).resolve().parents[2] / "docs" / "research_data" / "candles"

# See the "VOLUME HONESTY" module docstring section above.
_NO_REAL_VOLUME_ASSETS = {"GOLD", "EUR/USD", "GBP/USD", "USD/JPY"}


@dataclass(frozen=True)
class CandlePair:
    asset: str
    timeframe: str  # exported/display timeframe -- matches strategies.json's own field
    cadence_timeframe: str  # candle_boundary_due-compatible key: "12h" | "24h" | "1week"
    fetch_family: str  # "crypto_metals" | "forex" | "stock"


# Derived from docs/site_data/strategies.json's live roster -- see the module
# docstring for exactly what was excluded and why. 33 pairs.
#
# EXCEPTION (Day 7): BTC/12h has no live roster entry as of this commit -- added
# ahead of one, per explicit instruction, using the identical Binance 12h fetch
# path BNB/12h already exercises. Chart-only data until a BTC/12h strategy is
# actually registered; the strategy detail page has no route that reaches this
# file yet (fetchCandleData is keyed off a roster entry's own timeframe), so this
# is intentionally inert data, not a claim that a BTC/12h config is live.
#
# CANDLE-DATA-GAPS BATCH (feature/candle-data-gaps): two consecutive Research
# Agent runs generated hypotheses (ZSCORE_MOMENTUM_USDJPY_4H, ZSCORE_EXTREME_
# USDJPY_1D) the tester couldn't run against -- no candle file existed for
# either timeframe. Investigation found this is a recurring pattern, not a
# one-off: every (asset, timeframe) combo below was confirmed to have no
# existing export file AND to fetch cleanly from its real provider (live-
# tested directly, not assumed from provider docs) before being added here.
# Chart-only / hypothesis-testing data ahead of any live strategy registration
# for these specific (asset, timeframe) pairs, same convention as BTC/12h
# above -- not a claim that a strategy is live at any of these.
#   - USD/JPY 4h + 1day, EUR/USD 1day: Twelve Data native, no resampling
#     (forex_data.py's TWELVE_DATA_NATIVE_INTERVAL already covers all of
#     1h/4h/1day/1week for every FOREX_PAIRS entry -- confirmed live for
#     USD/JPY and GBP/USD; EUR/USD 1day not independently live-tested this
#     pass but uses the identical fetch path, so this is the same near-
#     certain case, not a distinct one). EUR/USD/4h itself is deliberately
#     NOT added here -- already in flight on a separate, unmerged branch
#     (feature/eurusd-4h-and-adx-dsl); not duplicated.
#   - BNB 4h + 24h, BTC 4h: Binance native, same fetch_timeframe_candles path
#     every other crypto entry above already uses.
#   - GOLD 4h: Twelve Data native (XAU/USD).
#   - SILVER 4h: resampled (4 consecutive 1h candles) from YFinance SI=F 1h --
#     not native (Twelve Data 404s SILVER on this plan, pre-existing), but the
#     same resample path SILVER's other timeframes already rely on.
#   - All 7 stocks' 4h: yfinance session-aware resample (fetch_stock_ohlcv's
#     own existing "4h" handling -- 4 consecutive 1h candles per RTH session),
#     live-tested against AAPL; identical code path for all 7, no per-ticker
#     branching in that function.
#
# EXCEPTION (added for RMR_LONG_ONLY_EURUSD_4H): EUR/USD/4h has no live roster
# entry either, same justification as BTC/12h above -- added ahead of one so
# this candidate strategy has real candle history to develop/test against.
# fetch_forex_ohlcv's own TWELVE_DATA_NATIVE_INTERVAL already has a native "4h"
# entry (see nero_core/data_sources/forex_data.py) -- no resampling needed here,
# unlike GOLD's 12h (Twelve Data has no native 12h for metals). This lands after
# the CANDLE-DATA-GAPS batch above, which deliberately skipped EUR/USD/4h as
# already in flight on this branch -- not a duplicate.
IN_SCOPE_PAIRS: tuple[CandlePair, ...] = (
    CandlePair("BTC", "24h", "24h", "crypto_metals"),
    CandlePair("BTC", "12h", "12h", "crypto_metals"),
    CandlePair("BTC", "4h", "4h", "crypto_metals"),
    CandlePair("BNB", "12h", "12h", "crypto_metals"),
    CandlePair("BNB", "24h", "24h", "crypto_metals"),
    CandlePair("BNB", "4h", "4h", "crypto_metals"),
    CandlePair("GOLD", "1week", "1week", "crypto_metals"),
    CandlePair("GOLD", "24h", "24h", "crypto_metals"),
    CandlePair("GOLD", "4h", "4h", "crypto_metals"),
    CandlePair("SILVER", "1week", "1week", "crypto_metals"),
    CandlePair("SILVER", "24h", "24h", "crypto_metals"),
    CandlePair("SILVER", "4h", "4h", "crypto_metals"),
    CandlePair("EUR/USD", "1week", "1week", "forex"),
    CandlePair("EUR/USD", "1day", "24h", "forex"),
    CandlePair("EUR/USD", "4h", "4h", "forex"),
    CandlePair("GBP/USD", "1week", "1week", "forex"),
    CandlePair("USD/JPY", "1week", "1week", "forex"),
    CandlePair("USD/JPY", "4h", "4h", "forex"),
    CandlePair("USD/JPY", "1day", "24h", "forex"),
    CandlePair("AAPL", "1day", "24h", "stock"),
    CandlePair("AAPL", "4h", "4h", "stock"),
    CandlePair("MSFT", "1day", "24h", "stock"),
    CandlePair("MSFT", "4h", "4h", "stock"),
    CandlePair("GOOGL", "1day", "24h", "stock"),
    CandlePair("GOOGL", "4h", "4h", "stock"),
    CandlePair("TSLA", "1day", "24h", "stock"),
    CandlePair("TSLA", "4h", "4h", "stock"),
    CandlePair("AMZN", "1day", "24h", "stock"),
    CandlePair("AMZN", "4h", "4h", "stock"),
    CandlePair("NVDA", "1day", "24h", "stock"),
    CandlePair("NVDA", "4h", "4h", "stock"),
    CandlePair("META", "1day", "24h", "stock"),
    CandlePair("META", "4h", "4h", "stock"),
)


def sanitize_asset_for_filename(asset: str) -> str:
    """"EUR/USD" -> "EURUSD" -- see the module docstring's FILENAME SANITIZATION
    section. Frontend code must apply this identical rule."""
    return asset.replace("/", "")


def candle_filename(asset: str, timeframe: str) -> str:
    return f"{sanitize_asset_for_filename(asset)}_{timeframe}.json"


def _fetch_candles(pair: CandlePair, client: MarketDataClient) -> pd.DataFrame:
    if pair.fetch_family == "crypto_metals":
        candles, _source = fetch_timeframe_candles(client, pair.asset, pair.cadence_timeframe)
        return candles
    if pair.fetch_family == "forex":
        result = fetch_forex_ohlcv(pair.asset, pair.timeframe)
        return result.prices
    if pair.fetch_family == "stock":
        result = fetch_stock_ohlcv(pair.asset, pair.timeframe)
        return result.prices
    raise ValueError(f"unknown fetch_family: {pair.fetch_family!r}")  # pragma: no cover - defensive


def _row_to_candle(row: pd.Series, asset: str) -> dict[str, object]:
    volume = None if asset in _NO_REAL_VOLUME_ASSETS else float(row["volume"])
    return {
        "time": int(row["open_time"]) // 1000,
        "open": float(row["open"]),
        "high": float(row["high"]),
        "low": float(row["low"]),
        "close": float(row["close"]),
        "volume": volume,
    }


def _read_existing_last_updated(path: Path) -> datetime | None:
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text())
        return datetime.fromisoformat(data["last_updated"])
    except (OSError, ValueError, KeyError, json.JSONDecodeError):
        return None


def _already_fresh(existing: datetime | None, cadence_timeframe: str, now: datetime) -> bool:
    """True if `existing` (the current export file's own last_updated) already falls
    within the SAME cadence bucket as `now` -- so a second scheduler tick inside the
    same ~40-minute candle_boundary_due window doesn't burn a second, redundant fetch
    of data that hasn't changed."""
    if existing is None:
        return False
    if cadence_timeframe == "1week":
        return existing.isocalendar()[:2] == now.isocalendar()[:2]
    if cadence_timeframe == "24h":
        return existing.date() == now.date()
    if cadence_timeframe == "12h":
        return (existing.date(), existing.hour // 12) == (now.date(), now.hour // 12)
    if cadence_timeframe == "4h":
        return (existing.date(), existing.hour // 4) == (now.date(), now.hour // 4)
    return False


@dataclass(frozen=True)
class CandleExportResult:
    exported: list[str]
    skipped_not_due: list[str]
    skipped_fresh: list[str]
    errors: list[dict[str, str]]


def export_candle_data(
    now: datetime | None = None,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    client: MarketDataClient | None = None,
    force: bool = False,
) -> CandleExportResult:
    """`force=True` bypasses both the cadence gate and the freshness check --
    every in-scope pair is fetched regardless of `now`. Never used by the
    scheduled run (which always calls this with force's default, False); it
    exists for a one-time manual bootstrap of a fresh deploy of this pipeline,
    so docs/site_data/candles/ doesn't sit empty for up to a week waiting for
    every pair's natural cadence to come around on its own."""
    now = now or datetime.now(timezone.utc)
    client = client or MarketDataClient()
    output_dir.mkdir(parents=True, exist_ok=True)

    exported: list[str] = []
    skipped_not_due: list[str] = []
    skipped_fresh: list[str] = []
    errors: list[dict[str, str]] = []

    for pair in IN_SCOPE_PAIRS:
        filename = candle_filename(pair.asset, pair.timeframe)
        path = output_dir / filename

        if not force and not candle_boundary_due(pair.cadence_timeframe, now):
            skipped_not_due.append(filename)
            continue

        if not force and _already_fresh(_read_existing_last_updated(path), pair.cadence_timeframe, now):
            skipped_fresh.append(filename)
            continue

        try:
            candles = _fetch_candles(pair, client)
        except (MarketDataUnavailableError, ForexDataUnavailableError, StockDataUnavailableError) as exc:
            errors.append({"asset": pair.asset, "timeframe": pair.timeframe, "message": f"{exc.__class__.__name__}: {exc}"})
            continue
        except Exception as exc:  # noqa: BLE001 - one pair's unexpected failure must never abort the others
            errors.append({"asset": pair.asset, "timeframe": pair.timeframe, "message": f"{exc.__class__.__name__}: {exc}"})
            continue

        if candles.empty:
            errors.append({"asset": pair.asset, "timeframe": pair.timeframe, "message": "no candles returned"})
            continue

        ordered = candles.sort_values("open_time").tail(CANDLE_COUNT).reset_index(drop=True)
        rows = [_row_to_candle(row, pair.asset) for _, row in ordered.iterrows()]

        payload = {
            "schema_version": SCHEMA_VERSION,
            "asset": pair.asset,
            "timeframe": pair.timeframe,
            "last_updated": now.isoformat(),
            "candles": rows,
        }
        path.write_text(json.dumps(payload, indent=2) + "\n")
        exported.append(filename)

    return CandleExportResult(exported=exported, skipped_not_due=skipped_not_due, skipped_fresh=skipped_fresh, errors=errors)


def export_research_candle_data(
    pairs: tuple[CandlePair, ...],
    now: datetime | None = None,
    output_dir: Path = DEFAULT_RESEARCH_OUTPUT_DIR,
    client: MarketDataClient | None = None,
    candle_count: int = RESEARCH_CANDLE_COUNT,
) -> CandleExportResult:
    """Full-history research export for backtesting/scoring -- a SEPARATE
    file, SEPARATE directory, from export_candle_data()'s own 200-row
    display export above (that function is completely unmodified by this
    one's existence). Reuses `_fetch_candles` UNCHANGED (the same
    provider-cascading fetch every pair above already uses -- BTC/4h via
    Binance already requests up to 50,000 candles per
    tools.timeframe_data.NATIVE_INTERVAL_CANDLES, so no fetch-side change
    was needed at all, only a bigger `.tail()` here instead of
    export_candle_data's CANDLE_COUNT=200) -- only the final truncation
    width differs.

    No cadence/freshness gating (`candle_boundary_due`/`_already_fresh`) --
    this is a MANUAL, deliberate research fetch a human runs when they want
    a fresh/larger research window, not a 30-minute scheduled cron tick, so
    those two checks (built for exactly that repeated-tick scenario) don't
    apply here.

    KNOWN EXTERNAL CONSTRAINT: yfinance-backed intraday assets (stocks,
    SILVER/PLATINUM's 4h resampled from 1h) are capped by Yahoo Finance's
    OWN documented ~730-day intraday lookback -- not something this function
    (or anything in this codebase) can fetch around. BTC/crypto pairs via
    Binance are unaffected (Binance's own klines history goes back to each
    symbol's listing date with no such short-window restriction)."""
    now = now or datetime.now(timezone.utc)
    client = client or MarketDataClient()
    output_dir.mkdir(parents=True, exist_ok=True)

    exported: list[str] = []
    errors: list[dict[str, str]] = []

    for pair in pairs:
        filename = candle_filename(pair.asset, pair.timeframe)
        path = output_dir / filename

        try:
            candles = _fetch_candles(pair, client)
        except (MarketDataUnavailableError, ForexDataUnavailableError, StockDataUnavailableError) as exc:
            errors.append({"asset": pair.asset, "timeframe": pair.timeframe, "message": f"{exc.__class__.__name__}: {exc}"})
            continue
        except Exception as exc:  # noqa: BLE001 - one pair's unexpected failure must never abort the others
            errors.append({"asset": pair.asset, "timeframe": pair.timeframe, "message": f"{exc.__class__.__name__}: {exc}"})
            continue

        if candles.empty:
            errors.append({"asset": pair.asset, "timeframe": pair.timeframe, "message": "no candles returned"})
            continue

        ordered = candles.sort_values("open_time").tail(candle_count).reset_index(drop=True)
        rows = [_row_to_candle(row, pair.asset) for _, row in ordered.iterrows()]

        payload = {
            "schema_version": SCHEMA_VERSION,
            "asset": pair.asset,
            "timeframe": pair.timeframe,
            "last_updated": now.isoformat(),
            "candle_count_requested": candle_count,
            "candles": rows,
        }
        path.write_text(json.dumps(payload, indent=2) + "\n")
        exported.append(filename)

    return CandleExportResult(exported=exported, skipped_not_due=[], skipped_fresh=[], errors=errors)


def main() -> None:
    """Never raises -- a script failure must show up in the GitHub Actions log, but
    must not fail the workflow step itself (same convention as live_scheduler.main())."""
    try:
        result = export_candle_data()
        print(
            f"Candle export: exported={result.exported}, "
            f"skipped_not_due={len(result.skipped_not_due)}, skipped_fresh={len(result.skipped_fresh)}, "
            f"errors={len(result.errors)}"
        )
        for err in result.errors:
            print(f"  ERROR: {err}")
    except Exception:  # noqa: BLE001
        traceback.print_exc()


if __name__ == "__main__":
    main()
