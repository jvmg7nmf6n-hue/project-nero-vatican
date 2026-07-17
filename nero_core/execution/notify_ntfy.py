"""Post-run ntfy.sh push notification for the live scheduler.

Deliberately a SEPARATE step from live_scheduler.py itself (see
.github/workflows/live_scheduler.yml) rather than folded into run_once(): a
notification-delivery failure must never affect whether a signal gets logged, and a
logging failure must never be masked by a notification appearing to succeed. This
script re-reads what the scheduler already committed to the Truth Ledger for its own
run_id, rather than being handed the in-memory RunResult directly, so it also works
standalone (e.g. `python -m nero_core.execution.notify_ntfy` re-sends the last run's
notification without re-running anything).

One notification is sent per scheduler run (not one per signal), containing one line
per row the run actually logged (an ordinary 30-minute tick usually logs nothing, since
most configs aren't due — see nero_core/execution/candle_schedule.py — in which case a
single "Zero trades evaluated" line is sent instead of silence).

ntfy.sh is a public, unauthenticated relay — the topic name is the only thing gating who
receives these. Nothing secret (API keys, real account state) is ever put in the
message body; it only ever contains what's already public in the Truth Ledger.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from nero_core.truth_ledger.execution_log import (
    DEFAULT_DB_PATH,
    ExecutionLogRow,
    NewsSentimentLogRow,
    latest_execution_metadata,
    list_execution_log_for_run,
    list_news_sentiment_log_for_run,
)

NTFY_URL = "https://ntfy.sh/Terminal3039"
NTFY_TIMEOUT_SECONDS = 10
ZERO_SIGNAL_MESSAGE = "Vatican | Scheduler ran | Zero trades evaluated"

# (strategy_id, asset) -> (display label, display asset/timeframe) for the 3 wired
# trading configs (nero_core/execution/live_scheduler.py SINGLE_ASSET_CONFIGS + the
# pairs config). Deliberately a closed lookup, not a generic formatter, because this
# scheduler only ever wires these specific configs (see nero_core/execution/DESIGN.md) —
# an unrecognized (strategy, asset) combination falls back to the raw values rather than
# guessing a display name.
DISPLAY_NAMES: dict[tuple[str, str], tuple[str, str]] = {
    ("BREAKOUT_MOMENTUM", "GOLD"): ("GOLD Momentum", "GOLD/1week"),
    ("TREND_PULLBACK", "BNB"): ("BNB TrendPullback", "BNB/12h"),
    ("COINTEGRATION_PAIRS", "BTC-ETH"): ("BTC-ETH Pairs", "BTC-ETH/12h"),
}
NEWS_SENTIMENT_LABEL = "News Sentiment"

_R_MULTIPLE_PATTERN = re.compile(r"r_multiple=([-+]?\d*\.?\d+)")


def _extract_r_multiple(reasoning: str) -> float | None:
    """r_multiple isn't its own execution_log column — it's embedded in the reasoning
    text replay.py always writes for EXIT events (see nero_core/execution/replay.py's
    ReplayEvent construction). Parsed here rather than added as a new column to keep
    this notifier a pure read-side add-on with no ledger schema change. Returns None
    (never a guessed value) if the text doesn't match the expected format."""
    match = _R_MULTIPLE_PATTERN.search(reasoning)
    return float(match.group(1)) if match else None


def format_execution_log_line(row: ExecutionLogRow) -> str:
    label, asset_display = DISPLAY_NAMES.get((row.strategy, row.asset), (row.strategy, row.asset))
    if row.signal_type == "ENTRY":
        result = f"OPENED @ {row.entry_price:.2f}" if row.entry_price is not None else "monitoring"
    elif row.signal_type == "EXIT":
        r_multiple = _extract_r_multiple(row.reasoning)
        result = f"{r_multiple:+.2f}R {'✓' if r_multiple >= 0 else '✗'}" if r_multiple is not None else "R n/a"
    else:  # NO_TRADE, WATCH
        result = "no signal"
    return f"Vatican | {label} | {asset_display} | {row.signal_type} | {result}"


def format_news_sentiment_line(row: NewsSentimentLogRow) -> str:
    result = "no signal" if row.signal_type == "NEUTRAL" else f"confidence {row.confidence:.2f}"
    return f"Vatican | {NEWS_SENTIMENT_LABEL} | {row.asset} | {row.signal_type} | {result}"


def build_notification_message(run_id: str, db_path: Path = DEFAULT_DB_PATH) -> str:
    execution_rows = list_execution_log_for_run(run_id, db_path)
    news_rows = list_news_sentiment_log_for_run(run_id, db_path)
    lines = [format_execution_log_line(r) for r in execution_rows]
    lines += [format_news_sentiment_line(r) for r in news_rows]
    return "\n".join(lines) if lines else ZERO_SIGNAL_MESSAGE


def send_ntfy_notification(
    message: str, url: str = NTFY_URL, timeout_seconds: int = NTFY_TIMEOUT_SECONDS
) -> bool:
    """Best-effort delivery — never raises. Returns True on a successful 2xx response,
    False on any failure (network error, timeout, non-2xx status), always printing the
    reason rather than swallowing it silently. Notifications are nice-to-have, not
    critical: a failure here must never be treated as a scheduler failure."""
    try:
        response = requests.post(url, data=message.encode("utf-8"), timeout=timeout_seconds)
        response.raise_for_status()
        return True
    except requests.RequestException as exc:
        print(f"ntfy notification failed (non-fatal): {exc.__class__.__name__}: {exc}")
        return False


def main() -> None:
    latest_run = latest_execution_metadata()
    message = build_notification_message(latest_run.run_id) if latest_run is not None else ZERO_SIGNAL_MESSAGE
    print(f"Sending ntfy notification to {NTFY_URL}:\n{message}")
    send_ntfy_notification(message)


if __name__ == "__main__":
    main()
