"""CC-1 DIRECTIVE (2026-08-07): regression guard for the Friday/Monday
WEEKLY_CLOSE_WEEKDAY mismatch fixed in nero_core/execution/candle_schedule.py.

Two independent checks:
1. A permanent, hardcoded assertion that WEEKLY_CLOSE_WEEKDAY still matches
   the real vendor convention this directive confirmed (Monday) -- catches
   an accidental revert even with no live data available (e.g. a fresh
   clone with an empty database).
2. A live cross-check against data/truth_ledger.db's own real execution_log
   rows (skipped, not failed, if that file/data isn't present) -- for
   every one of the 4 real "1week"-gated configs
   (nero_core/execution/live_scheduler.py's SINGLE_ASSET_CONFIGS + GOLD,
   DONCHIAN_FOREX_CONFIGS for EUR/USD, GBP/USD, USD/JPY), every ALREADY-
   LOGGED candle_timestamp must fall on WEEKLY_CLOSE_WEEKDAY. This is
   deliberately NOT read from docs/site_data/candles/*.json's own "time"
   field -- that field is `open_time` (nero_core/execution/
   export_candle_data.py::_row_to_candle), which for GOLD specifically is
   currently WRONG (a separate, real, NOT-fixed-in-this-directive bug:
   nero_core/data_sources/market_data.py's own `_twelve_data_interval_
   milliseconds` has no "1week" entry, silently falling back to its 1-day
   default -- confirmed by comparing against forex_data.py's own correctly-
   complete TWELVE_DATA_INTERVAL_MILLISECONDS dict, which DOES have
   "1week": 604_800_000). execution_log's own `candle_timestamp` is
   `close_time`, computed directly from the vendor's own timestamp with no
   such bug, and is what candle_schedule.py's gate itself is actually
   compared against -- the correct, reliable ground truth for this test.

WHEN ADDING A 5TH "1week"-GATED CONFIG: add its (strategy, asset) pair to
WEEKLY_GATED_STRATEGY_ASSETS below so this test starts covering it too --
this list is not auto-derived from live_scheduler.py, so it needs a
deliberate addition, matching this test's own purpose (a fifth config's
weekday mismatch should be someone's conscious decision to check, not
something that silently slips through).
"""
from __future__ import annotations

import sqlite3
import unittest
from datetime import datetime, timezone
from pathlib import Path

from nero_core.execution.candle_schedule import WEEKLY_CLOSE_WEEKDAY
from nero_core.truth_ledger.models import DEFAULT_DB_PATH

WEEKLY_GATED_STRATEGY_ASSETS = [
    ("BREAKOUT_MOMENTUM", "GOLD"),
    ("RANGE_MEAN_REVERSION", "GOLD"),
    ("DONCHIAN_TREND", "GOLD"),
    ("DONCHIAN_TREND", "EUR/USD"),
    ("DONCHIAN_TREND", "GBP/USD"),
    ("DONCHIAN_TREND", "USD/JPY"),
]


class WeeklyCloseWeekdayConstantTest(unittest.TestCase):
    def test_weekly_close_weekday_is_monday_matching_the_confirmed_vendor_convention(self) -> None:
        """Permanent guard, no live data required: catches an accidental
        revert back to Friday (weekday 4) or any other unverified value."""
        self.assertEqual(
            WEEKLY_CLOSE_WEEKDAY, 0,
            "WEEKLY_CLOSE_WEEKDAY changed without re-confirming the real vendor "
            "close-weekday for every '1week'-gated config -- see this module's own "
            "docstring and docs/investigations/factory_loop_implementation_report.md "
            "for how 0 (Monday) was confirmed.",
        )


class WeeklyCloseWeekdayLiveDataCrossCheckTest(unittest.TestCase):
    def setUp(self) -> None:
        if not Path(DEFAULT_DB_PATH).exists():
            self.skipTest(f"{DEFAULT_DB_PATH} not present in this checkout")

    def test_every_1week_gated_configs_real_logged_candles_close_on_the_configured_weekday(self) -> None:
        with sqlite3.connect(str(DEFAULT_DB_PATH)) as conn:
            cur = conn.cursor()
            for strategy, asset in WEEKLY_GATED_STRATEGY_ASSETS:
                with self.subTest(strategy=strategy, asset=asset):
                    cur.execute(
                        "SELECT DISTINCT candle_timestamp FROM execution_log WHERE strategy = ? AND asset = ?",
                        (strategy, asset),
                    )
                    timestamps = [row[0] for row in cur.fetchall()]
                    if not timestamps:
                        self.skipTest(f"no real execution_log rows yet for {strategy}/{asset}")
                        continue
                    for ts in timestamps:
                        candle_closed_at = datetime.fromtimestamp(ts / 1000.0, tz=timezone.utc)
                        self.assertEqual(
                            candle_closed_at.weekday(), WEEKLY_CLOSE_WEEKDAY,
                            f"{strategy}/{asset}'s real logged candle_timestamp {candle_closed_at.isoformat()} "
                            f"({candle_closed_at.strftime('%A')}) does not match WEEKLY_CLOSE_WEEKDAY="
                            f"{WEEKLY_CLOSE_WEEKDAY} -- either the vendor's convention changed, or this "
                            f"config's real data was never this test's basis.",
                        )


if __name__ == "__main__":
    unittest.main()
