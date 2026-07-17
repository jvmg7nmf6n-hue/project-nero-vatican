"""Unified live-execution scheduler for Project Vatican's Phase 1 paper-tracking
survivors. See nero_core/execution/DESIGN.md for the full design rationale (timeframe
boundary detection, no-lookahead guards, error-handling taxonomy, immutable-log
principle, and why the GOLD variant below is v1.2.0, not v1.1.0).

Run every 30 minutes (.github/workflows/live_scheduler.yml, cron "0,30 * * * *"). One
process, one run_id, per-asset resilience (a fatal error on one asset is recorded and
skipped, never aborts the run for the others).

SURVIVORS WIRED (see docs/research_phase_closure.md and
docs/grid_shift_robustness_followup.md for how each earned this status):
  1. GOLD    / 1week / BREAKOUT_MOMENTUM breakout-momentum-v1.2.0-gold-calibrated-1week
  2. BNB     / 12h    / TREND_PULLBACK trend-pullback-v1.0.0
  3. BTC-ETH / 12h    / COINTEGRATION_PAIRS cointegration-pairs-v1.0.0
  4. NEWS_SENTIMENT (GOLD, BTC) news-sentiment-v1.0.0 — forward-test-only, no backtest

Usage:
    python -m nero_core.execution.live_scheduler
"""
from __future__ import annotations

import os
import sys
import time
import traceback
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from nero_core.config import load_dotenv
from nero_core.data_sources.market_data import MarketDataClient, MarketDataUnavailableError
from nero_core.data_sources.news_feed import NewsFeedClient
from nero_core.execution.candle_schedule import candle_boundary_due, daily_time_due
from nero_core.execution.replay import replay_pairs_events, replay_single_asset_events
from nero_core.strategies.breakout_momentum import STRATEGY_ID as BREAKOUT_MOMENTUM_ID
from nero_core.strategies.breakout_momentum_gold_calibrated_1week import STRATEGY_VERSION as GOLD_BM_VERSION
from nero_core.strategies.cointegration_pairs import (
    DEFAULT_PARAMETERS as PAIRS_PARAMETERS,
    PAIR as PAIRS_ASSETS,
    STRATEGY_ID as COINTEGRATION_PAIRS_ID,
    STRATEGY_VERSION as COINTEGRATION_PAIRS_VERSION,
    add_indicators as pairs_add_indicators,
    align_pair_candles,
)
from nero_core.strategies.news_sentiment import (
    DEFAULT_PARAMETERS as NEWS_PARAMS,
    STRATEGY_ID as NEWS_SENTIMENT_ID,
    analyze_sentiment,
)
from nero_core.strategies.trend_pullback import STRATEGY_ID as TREND_PULLBACK_ID
from nero_core.strategies.trend_pullback import STRATEGY_VERSION as TREND_PULLBACK_VERSION
from nero_core.truth_ledger.execution_log import (
    DEFAULT_DB_PATH,
    earliest_logged_candle_timestamp,
    has_news_sentiment_logged_today,
    insert_execution_log_row,
    insert_execution_metadata,
    insert_news_sentiment_log,
    latest_logged_candle_timestamp,
)
from tools.backtest_compare import INDICATOR_COLUMNS_TO_CHECK, VARIANT_SPECS
from tools.timeframe_data import fetch_timeframe_candles

load_dotenv()

RETRY_BACKOFF_SECONDS = (1, 3, 10)
NEWS_SENTIMENT_ASSETS = ("GOLD", "BTC")
PAIRS_TIMEFRAME = "12h"


@dataclass(frozen=True)
class SingleAssetConfig:
    asset: str
    timeframe: str
    variant_key: str
    strategy_id: str
    strategy_version: str


SINGLE_ASSET_CONFIGS = (
    SingleAssetConfig("GOLD", "1week", "breakout_momentum_gold_calibrated_1week", BREAKOUT_MOMENTUM_ID, GOLD_BM_VERSION),
    SingleAssetConfig("BNB", "12h", "trend_pullback", TREND_PULLBACK_ID, TREND_PULLBACK_VERSION),
)


@dataclass(frozen=True)
class RunResult:
    run_id: str
    assets_evaluated: list[str]
    assets_skipped: list[dict[str, Any]]
    errors_encountered: list[dict[str, Any]]


def classify_market_data_error(exc: Exception) -> str:
    """Heuristic classification of a MarketDataUnavailableError's accumulated message
    into PERMANENT vs TRANSIENT. MarketDataClient collapses every source's failure into
    one exception carrying a joined message string rather than a structured error type,
    so this is necessarily a string-pattern heuristic — documented as such in
    nero_core/execution/DESIGN.md, not claimed as precise."""
    message = str(exc).lower()
    permanent_markers = ("missing api key", "unauthorized", "401", "403", "invalid api key", "forbidden")
    if any(marker in message for marker in permanent_markers):
        return "PERMANENT"
    return "TRANSIENT"


def fetch_with_retry(
    fetch_fn: Callable[[], Any], sleep_fn: Callable[[float], None] = time.sleep
) -> tuple[Any | None, dict[str, Any] | None]:
    """Attempts `fetch_fn`, retrying a classified TRANSIENT MarketDataUnavailableError up
    to len(RETRY_BACKOFF_SECONDS) times with the given backoff. A PERMANENT
    classification never retries. Returns (result, None) on success, or
    (None, {"classification": ..., "message": ...}) once retries are exhausted or on an
    immediate permanent failure."""
    last_exc: Exception | None = None
    for attempt in range(len(RETRY_BACKOFF_SECONDS) + 1):
        try:
            return fetch_fn(), None
        except MarketDataUnavailableError as exc:
            last_exc = exc
            if classify_market_data_error(exc) == "PERMANENT":
                return None, {"classification": "FATAL", "message": str(exc)}
            if attempt < len(RETRY_BACKOFF_SECONDS):
                sleep_fn(RETRY_BACKOFF_SECONDS[attempt])
    return None, {"classification": "FETCH_INCOMPLETE", "message": str(last_exc)}


def process_single_asset(
    config: SingleAssetConfig,
    client: MarketDataClient,
    run_id: str,
    now: datetime,
    sleep_fn: Callable[[float], None] = time.sleep,
    db_path: Path = DEFAULT_DB_PATH,
) -> tuple[str, dict[str, Any] | None]:
    """Returns ("EVALUATED", None) or ("SKIPPED", record)."""
    spec = VARIANT_SPECS[config.variant_key]

    fetch_result, fetch_error = fetch_with_retry(
        lambda: fetch_timeframe_candles(client, config.asset, config.timeframe), sleep_fn
    )
    if fetch_error is not None:
        return "SKIPPED", {"asset": config.asset, "strategy": config.strategy_id, **fetch_error}

    candles, _source = fetch_result
    enriched = spec.add_indicators_fn(candles, spec.params)
    dropna_columns = [c for c in INDICATOR_COLUMNS_TO_CHECK if c in enriched.columns]
    evaluable = enriched.dropna(subset=dropna_columns).reset_index(drop=True)
    if evaluable.empty:
        return "SKIPPED", {
            "asset": config.asset, "strategy": config.strategy_id,
            "classification": "DATA_QUALITY", "message": "insufficient indicator warmup history",
        }

    inception = earliest_logged_candle_timestamp(config.strategy_id, config.strategy_version, config.asset, db_path)
    already_logged = latest_logged_candle_timestamp(config.strategy_id, config.strategy_version, config.asset, db_path)
    events, _state = replay_single_asset_events(evaluable, spec, config.asset, inception, already_logged)

    for event in events:
        insert_execution_log_row(
            run_id=run_id, strategy=config.strategy_id, strategy_version=config.strategy_version,
            asset=config.asset, signal_type=event.signal_type, reasoning=event.reasoning,
            candle_timestamp=event.candle_close_time, entry_price=event.entry_price, exit_price=event.exit_price,
            timestamp=now, db_path=db_path,
        )
    return "EVALUATED", None


def process_pairs(
    client: MarketDataClient,
    run_id: str,
    now: datetime,
    sleep_fn: Callable[[float], None] = time.sleep,
    db_path: Path = DEFAULT_DB_PATH,
) -> tuple[str, dict[str, Any] | None]:
    x_name, y_name = PAIRS_ASSETS
    label = f"{x_name}-{y_name}"

    def _fetch() -> tuple:
        x_candles, _ = fetch_timeframe_candles(client, x_name, PAIRS_TIMEFRAME)
        y_candles, _ = fetch_timeframe_candles(client, y_name, PAIRS_TIMEFRAME)
        return x_candles, y_candles

    fetch_result, fetch_error = fetch_with_retry(_fetch, sleep_fn)
    if fetch_error is not None:
        return "SKIPPED", {"asset": label, "strategy": COINTEGRATION_PAIRS_ID, **fetch_error}

    x_candles, y_candles = fetch_result
    aligned = align_pair_candles(x_candles, y_candles, x_name, y_name)
    enriched = pairs_add_indicators(aligned, PAIRS_PARAMETERS, x_name, y_name)
    evaluable = enriched.dropna(subset=["zscore"]).reset_index(drop=True)
    if evaluable.empty:
        return "SKIPPED", {
            "asset": label, "strategy": COINTEGRATION_PAIRS_ID,
            "classification": "DATA_QUALITY", "message": "insufficient indicator warmup history",
        }

    inception = earliest_logged_candle_timestamp(COINTEGRATION_PAIRS_ID, COINTEGRATION_PAIRS_VERSION, label, db_path)
    already_logged = latest_logged_candle_timestamp(COINTEGRATION_PAIRS_ID, COINTEGRATION_PAIRS_VERSION, label, db_path)
    events, _state = replay_pairs_events(evaluable, PAIRS_PARAMETERS, x_name, y_name, inception, already_logged)

    for event in events:
        insert_execution_log_row(
            run_id=run_id, strategy=COINTEGRATION_PAIRS_ID, strategy_version=COINTEGRATION_PAIRS_VERSION,
            asset=label, signal_type=event.signal_type, reasoning=event.reasoning,
            candle_timestamp=event.candle_close_time, entry_price=event.entry_price, exit_price=event.exit_price,
            timestamp=now, db_path=db_path,
        )
    return "EVALUATED", None


def process_news_sentiment(
    run_id: str, now: datetime, db_path: Path = DEFAULT_DB_PATH, news_client: NewsFeedClient | None = None
) -> tuple[list[str], list[dict[str, Any]]]:
    gemini_key = os.getenv("GEMINI_API_KEY", "")
    client = news_client or NewsFeedClient()

    evaluated: list[str] = []
    errors: list[dict[str, Any]] = []
    for asset in NEWS_SENTIMENT_ASSETS:
        if has_news_sentiment_logged_today(asset, now, db_path):
            continue
        try:
            feed_result = client.load(asset)
        except Exception as exc:  # noqa: BLE001 - one asset's feed failure must not block the other
            errors.append({"asset": asset, "strategy": NEWS_SENTIMENT_ID, "classification": "FETCH_INCOMPLETE", "message": str(exc)})
            continue

        result = analyze_sentiment(feed_result.headlines, asset, now, gemini_api_key=gemini_key, params=NEWS_PARAMS)
        insert_news_sentiment_log(
            run_id=run_id, asset=asset, fetch_timestamp=now, signal_type=result.signal_type,
            confidence=result.confidence, reasoning=result.summary, source=result.source,
            sentiment_score=result.sentiment_score, db_path=db_path,
        )
        evaluated.append(asset)
    return evaluated, errors


def run_once(
    client: MarketDataClient | None = None,
    now: datetime | None = None,
    db_path: Path = DEFAULT_DB_PATH,
    sleep_fn: Callable[[float], None] = time.sleep,
) -> RunResult:
    run_id = str(uuid.uuid4())
    now = now or datetime.now(timezone.utc)
    start_time = now
    client = client or MarketDataClient()

    assets_evaluated: list[str] = []
    assets_skipped: list[dict[str, Any]] = []
    errors_encountered: list[dict[str, Any]] = []

    for config in SINGLE_ASSET_CONFIGS:
        if not candle_boundary_due(config.timeframe, now):
            assets_skipped.append({"asset": config.asset, "strategy": config.strategy_id, "classification": "NOT_DUE"})
            continue
        try:
            status, record = process_single_asset(config, client, run_id, now, sleep_fn, db_path)
        except Exception as exc:  # noqa: BLE001 - one config's unexpected failure must not abort the run
            errors_encountered.append(
                {"asset": config.asset, "strategy": config.strategy_id, "classification": "FATAL", "message": f"{exc.__class__.__name__}: {exc}"}
            )
            continue
        if status == "EVALUATED":
            assets_evaluated.append(config.asset)
        elif record["classification"] == "FATAL":
            errors_encountered.append(record)
        else:
            assets_skipped.append(record)

    pairs_label = "-".join(PAIRS_ASSETS)
    if candle_boundary_due(PAIRS_TIMEFRAME, now):
        try:
            status, record = process_pairs(client, run_id, now, sleep_fn, db_path)
        except Exception as exc:  # noqa: BLE001
            errors_encountered.append(
                {"asset": pairs_label, "strategy": COINTEGRATION_PAIRS_ID, "classification": "FATAL", "message": f"{exc.__class__.__name__}: {exc}"}
            )
        else:
            if status == "EVALUATED":
                assets_evaluated.append(pairs_label)
            elif record["classification"] == "FATAL":
                errors_encountered.append(record)
            else:
                assets_skipped.append(record)
    else:
        assets_skipped.append({"asset": pairs_label, "strategy": COINTEGRATION_PAIRS_ID, "classification": "NOT_DUE"})

    if daily_time_due(NEWS_PARAMS.daily_run_hour_utc, now):
        try:
            news_evaluated, news_errors = process_news_sentiment(run_id, now, db_path)
            assets_evaluated.extend(f"NEWS_SENTIMENT:{a}" for a in news_evaluated)
            errors_encountered.extend(news_errors)
        except Exception as exc:  # noqa: BLE001
            errors_encountered.append(
                {"asset": "NEWS_SENTIMENT", "strategy": NEWS_SENTIMENT_ID, "classification": "FATAL", "message": f"{exc.__class__.__name__}: {exc}"}
            )
    else:
        assets_skipped.append({"asset": "NEWS_SENTIMENT", "strategy": NEWS_SENTIMENT_ID, "classification": "NOT_DUE"})

    end_time = datetime.now(timezone.utc)
    insert_execution_metadata(run_id, start_time, end_time, assets_evaluated, assets_skipped, errors_encountered, db_path)
    return RunResult(run_id, assets_evaluated, assets_skipped, errors_encountered)


def main() -> None:
    """Never raises — a script failure must show up in the GitHub Actions log, but must
    not fail the workflow step itself (per project spec: the workflow's own git-commit
    step still runs even after a scheduler bug, so already-inserted rows aren't lost)."""
    try:
        result = run_once()
        print(
            f"Live scheduler run {result.run_id}: evaluated={result.assets_evaluated}, "
            f"skipped={len(result.assets_skipped)}, errors={len(result.errors_encountered)}"
        )
        for record in result.assets_skipped:
            print(f"  SKIPPED: {record}")
        for record in result.errors_encountered:
            print(f"  ERROR: {record}")
    except Exception:  # noqa: BLE001
        traceback.print_exc()


if __name__ == "__main__":
    main()
