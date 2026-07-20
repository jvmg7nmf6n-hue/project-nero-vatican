from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from nero_core.execution.export_site_data import (
    RECENT_LEDGER_LIMIT,
    SCHEMA_VERSION,
    build_ledger_export,
    build_stats_export,
    build_strategies_export,
    main,
    write_site_data,
)
from nero_core.truth_ledger.execution_log import (
    ExecutionLogRow,
    insert_execution_log_row,
    list_execution_log,
)

NOW = datetime(2026, 7, 20, 12, 0, tzinfo=timezone.utc)

GOLD_STRATEGY = "BREAKOUT_MOMENTUM"
GOLD_VERSION = "breakout-momentum-v1.2.0-gold-calibrated-1week"
BNB_STRATEGY = "TREND_PULLBACK"
BNB_VERSION = "trend-pullback-v1.0.0"
PAIRS_STRATEGY = "COINTEGRATION_PAIRS"
PAIRS_VERSION = "cointegration-pairs-v1.0.0"
PAIRS_ASSET = "BTC-ETH"


def _row(id_: int, run_id: str, strategy: str, version: str, asset: str, signal_type: str,
         candle_timestamp: int, entry_price=None, exit_price=None, reasoning: str = "x") -> ExecutionLogRow:
    return ExecutionLogRow(
        id=id_, run_id=run_id, timestamp=NOW, strategy=strategy, strategy_version=version, asset=asset,
        signal_type=signal_type, entry_price=entry_price, exit_price=exit_price, reasoning=reasoning,
        candle_timestamp=candle_timestamp, created_at=NOW,
    )


class BuildLedgerExportTest(unittest.TestCase):
    def test_includes_schema_version_and_last_updated(self) -> None:
        export = build_ledger_export([], now=NOW)
        self.assertEqual(export["schema_version"], SCHEMA_VERSION)
        self.assertEqual(export["last_updated"], NOW.isoformat())

    def test_rows_are_newest_first(self) -> None:
        rows = [
            _row(1, "r1", GOLD_STRATEGY, GOLD_VERSION, "GOLD", "NO_TRADE", candle_timestamp=1000),
            _row(2, "r1", GOLD_STRATEGY, GOLD_VERSION, "GOLD", "NO_TRADE", candle_timestamp=3000),
            _row(3, "r1", GOLD_STRATEGY, GOLD_VERSION, "GOLD", "NO_TRADE", candle_timestamp=2000),
        ]
        export = build_ledger_export(rows, now=NOW)
        candle_timestamps = [r["candle_timestamp"] for r in export["rows"]]
        self.assertEqual(candle_timestamps[0], datetime.fromtimestamp(3.0, tz=timezone.utc).isoformat())

    def test_only_the_specified_fields_are_present(self) -> None:
        rows = [_row(1, "r1", GOLD_STRATEGY, GOLD_VERSION, "GOLD", "ENTRY", candle_timestamp=1000, entry_price=2400.0)]
        export = build_ledger_export(rows, now=NOW)
        expected_fields = {"timestamp", "strategy", "asset", "signal_type", "entry_price", "exit_price", "reasoning", "candle_timestamp"}
        self.assertEqual(set(export["rows"][0].keys()), expected_fields)

    def test_strategy_version_and_run_id_are_not_leaked(self) -> None:
        rows = [_row(1, "secret-run-id", GOLD_STRATEGY, GOLD_VERSION, "GOLD", "ENTRY", candle_timestamp=1000, entry_price=2400.0)]
        export = build_ledger_export(rows, now=NOW)
        self.assertNotIn("run_id", export["rows"][0])
        self.assertNotIn("strategy_version", export["rows"][0])

    def test_limit_caps_the_row_count(self) -> None:
        rows = [
            _row(i, "r1", GOLD_STRATEGY, GOLD_VERSION, "GOLD", "NO_TRADE", candle_timestamp=i * 1000)
            for i in range(300)
        ]
        export = build_ledger_export(rows, limit=RECENT_LEDGER_LIMIT, now=NOW)
        self.assertEqual(len(export["rows"]), RECENT_LEDGER_LIMIT)

    def test_limit_keeps_the_newest_rows(self) -> None:
        rows = [
            _row(i, "r1", GOLD_STRATEGY, GOLD_VERSION, "GOLD", "NO_TRADE", candle_timestamp=i * 1000)
            for i in range(300)
        ]
        export = build_ledger_export(rows, limit=RECENT_LEDGER_LIMIT, now=NOW)
        newest_expected = datetime.fromtimestamp(299.0, tz=timezone.utc).isoformat()
        self.assertEqual(export["rows"][0]["candle_timestamp"], newest_expected)

    def test_ties_in_candle_timestamp_broken_by_id_descending(self) -> None:
        rows = [
            _row(1, "r1", GOLD_STRATEGY, GOLD_VERSION, "GOLD", "EXIT", candle_timestamp=1000, exit_price=100.0),
            _row(2, "r1", GOLD_STRATEGY, GOLD_VERSION, "GOLD", "ENTRY", candle_timestamp=1000, entry_price=101.0),
        ]
        export = build_ledger_export(rows, now=NOW)
        self.assertEqual(export["rows"][0]["signal_type"], "ENTRY")  # id=2 comes first


class RoundTripStatsTest(unittest.TestCase):
    def test_zero_round_trips_yields_nulls(self) -> None:
        rows = [_row(1, "r1", GOLD_STRATEGY, GOLD_VERSION, "GOLD", "NO_TRADE", candle_timestamp=1000)]
        export = build_stats_export(rows, now=NOW)
        gold_stats = next(s for s in export["strategies"] if s["strategy"] == GOLD_STRATEGY)

        self.assertEqual(gold_stats["resolved_trades"], 0)
        self.assertIsNone(gold_stats["win_rate"])
        self.assertIsNone(gold_stats["expectancy_r"])
        self.assertIsNone(gold_stats["avg_return_pct"])
        self.assertIsNone(gold_stats["open_position"])

    def test_strategy_with_zero_rows_at_all_still_appears(self) -> None:
        # Empty ledger entirely.
        export = build_stats_export([], now=NOW)
        strategy_names = {s["strategy"] for s in export["strategies"]}
        self.assertIn(GOLD_STRATEGY, strategy_names)
        self.assertIn(BNB_STRATEGY, strategy_names)
        self.assertIn(PAIRS_STRATEGY, strategy_names)
        for s in export["strategies"]:
            self.assertEqual(s["resolved_trades"], 0)

    def test_one_completed_round_trip_computes_win_rate_and_return(self) -> None:
        rows = [
            _row(1, "r1", GOLD_STRATEGY, GOLD_VERSION, "GOLD", "ENTRY", candle_timestamp=1000, entry_price=100.0),
            _row(2, "r1", GOLD_STRATEGY, GOLD_VERSION, "GOLD", "EXIT", candle_timestamp=2000, exit_price=110.0,
                 reasoning="TARGET exit, r_multiple=1.250, net_pnl=45.00"),
        ]
        export = build_stats_export(rows, now=NOW)
        gold_stats = next(s for s in export["strategies"] if s["strategy"] == GOLD_STRATEGY)

        self.assertEqual(gold_stats["resolved_trades"], 1)
        self.assertEqual(gold_stats["win_rate"], 1.0)
        self.assertAlmostEqual(gold_stats["avg_return_pct"], 10.0, places=6)
        self.assertAlmostEqual(gold_stats["expectancy_r"], 1.25, places=6)

    def test_expectancy_r_is_null_when_reasoning_has_no_r_multiple(self) -> None:
        # Mirrors COINTEGRATION_PAIRS' real reasoning shape, which never includes r_multiple.
        rows = [
            _row(1, "r1", PAIRS_STRATEGY, PAIRS_VERSION, PAIRS_ASSET, "ENTRY", candle_timestamp=1000, entry_price=100.0),
            _row(2, "r1", PAIRS_STRATEGY, PAIRS_VERSION, PAIRS_ASSET, "EXIT", candle_timestamp=2000, exit_price=105.0,
                 reasoning="REVERSION exit on BTC leg, net_pnl=12.00"),
        ]
        export = build_stats_export(rows, now=NOW)
        pairs_stats = next(s for s in export["strategies"] if s["strategy"] == PAIRS_STRATEGY)

        self.assertEqual(pairs_stats["resolved_trades"], 1)
        self.assertIsNone(pairs_stats["expectancy_r"])
        # win_rate/avg_return_pct remain real numbers from structured price data even
        # though expectancy_r couldn't be recovered from free text.
        self.assertEqual(pairs_stats["win_rate"], 1.0)
        self.assertAlmostEqual(pairs_stats["avg_return_pct"], 5.0, places=6)

    def test_trailing_unpaired_entry_is_reported_as_open_position_not_a_resolved_trade(self) -> None:
        rows = [
            _row(1, "r1", BNB_STRATEGY, BNB_VERSION, "BNB", "ENTRY", candle_timestamp=1000, entry_price=500.0),
        ]
        export = build_stats_export(rows, now=NOW)
        bnb_stats = next(s for s in export["strategies"] if s["strategy"] == BNB_STRATEGY)

        self.assertEqual(bnb_stats["resolved_trades"], 0)
        self.assertIsNotNone(bnb_stats["open_position"])
        self.assertEqual(bnb_stats["open_position"]["entry_price"], 500.0)

    def test_multiple_round_trips_average_correctly(self) -> None:
        rows = [
            _row(1, "r1", BNB_STRATEGY, BNB_VERSION, "BNB", "ENTRY", candle_timestamp=1000, entry_price=100.0),
            _row(2, "r1", BNB_STRATEGY, BNB_VERSION, "BNB", "EXIT", candle_timestamp=2000, exit_price=110.0,
                 reasoning="TARGET exit, r_multiple=1.000, net_pnl=10.00"),
            _row(3, "r1", BNB_STRATEGY, BNB_VERSION, "BNB", "ENTRY", candle_timestamp=3000, entry_price=200.0),
            _row(4, "r1", BNB_STRATEGY, BNB_VERSION, "BNB", "EXIT", candle_timestamp=4000, exit_price=190.0,
                 reasoning="SL exit, r_multiple=-1.000, net_pnl=-10.00"),
        ]
        export = build_stats_export(rows, now=NOW)
        bnb_stats = next(s for s in export["strategies"] if s["strategy"] == BNB_STRATEGY)

        self.assertEqual(bnb_stats["resolved_trades"], 2)
        self.assertEqual(bnb_stats["win_rate"], 0.5)
        self.assertAlmostEqual(bnb_stats["expectancy_r"], 0.0, places=6)

    def test_orphaned_exit_without_preceding_entry_is_skipped_not_fabricated(self) -> None:
        rows = [
            _row(1, "r1", BNB_STRATEGY, BNB_VERSION, "BNB", "EXIT", candle_timestamp=1000, exit_price=100.0),
        ]
        export = build_stats_export(rows, now=NOW)
        bnb_stats = next(s for s in export["strategies"] if s["strategy"] == BNB_STRATEGY)

        self.assertEqual(bnb_stats["resolved_trades"], 0)
        self.assertEqual(bnb_stats["signal_counts"]["EXIT"], 1)

    def test_signal_counts_by_type_are_always_present(self) -> None:
        rows = [
            _row(1, "r1", GOLD_STRATEGY, GOLD_VERSION, "GOLD", "NO_TRADE", candle_timestamp=1000),
            _row(2, "r1", GOLD_STRATEGY, GOLD_VERSION, "GOLD", "NO_TRADE", candle_timestamp=2000),
            _row(3, "r1", GOLD_STRATEGY, GOLD_VERSION, "GOLD", "ENTRY", candle_timestamp=3000, entry_price=100.0),
        ]
        export = build_stats_export(rows, now=NOW)
        gold_stats = next(s for s in export["strategies"] if s["strategy"] == GOLD_STRATEGY)

        self.assertEqual(gold_stats["signal_counts"], {"ENTRY": 1, "EXIT": 0, "WATCH": 0, "NO_TRADE": 2})

    def test_roster_order_is_stable(self) -> None:
        export = build_stats_export([], now=NOW)
        names = [s["strategy"] for s in export["strategies"]]
        self.assertEqual(
            names,
            [
                GOLD_STRATEGY,
                BNB_STRATEGY,
                "BREAKOUT_MOMENTUM",
                "TREND_PULLBACK",
                "VOLATILITY_SQUEEZE",
                "VOLATILITY_SQUEEZE",
                "VOLATILITY_SQUEEZE",
                # RMR watchlist configs (Replay Machinery Generalization) -- GOLD/1week,
                # SILVER/1week, BTC/24h long-only, BTC/24h confirmation.
                "RANGE_MEAN_REVERSION",
                "RANGE_MEAN_REVERSION",
                "RANGE_MEAN_REVERSION",
                "RANGE_MEAN_REVERSION",
                PAIRS_STRATEGY,
                "ORDERFLOW_IMBALANCE",
                "ORDERFLOW_IMBALANCE",
            ],
        )


class BuildStrategiesExportTest(unittest.TestCase):
    def test_roster_includes_verification_status_from_the_mapping(self) -> None:
        export = build_strategies_export(now=NOW)
        gold_entry = next(e for e in export["strategies"] if e["name"] == GOLD_STRATEGY)
        self.assertEqual(gold_entry["verification_status"], "triple-verified")
        self.assertEqual(gold_entry["asset"], "GOLD")
        self.assertEqual(gold_entry["timeframe"], "1week")

    def test_pairs_entry_uses_hyphenated_asset_label(self) -> None:
        export = build_strategies_export(now=NOW)
        pairs_entry = next(e for e in export["strategies"] if e["name"] == PAIRS_STRATEGY)
        self.assertEqual(pairs_entry["asset"], "BTC-ETH")

    def test_news_sentiment_appears_with_daily_timeframe(self) -> None:
        export = build_strategies_export(now=NOW)
        news_entries = [e for e in export["strategies"] if e["name"] == "NEWS_SENTIMENT"]
        self.assertEqual(len(news_entries), 2)  # GOLD, BTC
        for entry in news_entries:
            self.assertEqual(entry["timeframe"], "daily")

    def test_schema_version_and_last_updated_present(self) -> None:
        export = build_strategies_export(now=NOW)
        self.assertEqual(export["schema_version"], SCHEMA_VERSION)
        self.assertEqual(export["last_updated"], NOW.isoformat())


class WriteSiteDataTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self._tmp.name) / "test_truth_ledger.db"
        self.output_dir = Path(self._tmp.name) / "site_data"
        self.addCleanup(self._tmp.cleanup)

    def test_writes_all_four_files_as_valid_json(self) -> None:
        insert_execution_log_row(
            run_id="r1", strategy=GOLD_STRATEGY, strategy_version=GOLD_VERSION, asset="GOLD",
            signal_type="NO_TRADE", reasoning="x", candle_timestamp=1000, timestamp=NOW, db_path=self.db_path,
        )

        write_site_data(db_path=self.db_path, output_dir=self.output_dir, now=NOW)

        for filename in ("ledger_full.json", "ledger_recent.json", "stats.json", "strategies.json"):
            path = self.output_dir / filename
            self.assertTrue(path.exists())
            payload = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(payload["schema_version"], SCHEMA_VERSION)
            self.assertEqual(payload["last_updated"], NOW.isoformat())

    def test_is_read_only_over_the_ledger(self) -> None:
        insert_execution_log_row(
            run_id="r1", strategy=GOLD_STRATEGY, strategy_version=GOLD_VERSION, asset="GOLD",
            signal_type="NO_TRADE", reasoning="x", candle_timestamp=1000, timestamp=NOW, db_path=self.db_path,
        )
        before = list_execution_log(db_path=self.db_path)

        write_site_data(db_path=self.db_path, output_dir=self.output_dir, now=NOW)
        write_site_data(db_path=self.db_path, output_dir=self.output_dir, now=NOW)  # run twice for good measure

        after = list_execution_log(db_path=self.db_path)
        self.assertEqual(len(before), len(after))
        self.assertEqual(before, after)

    def test_main_never_raises_even_when_the_export_fails(self) -> None:
        from unittest.mock import patch

        with patch("nero_core.execution.export_site_data.write_site_data", side_effect=OSError("disk full")):
            try:
                main()
            except Exception as exc:  # noqa: BLE001
                self.fail(f"main() must never raise; raised {exc!r}")


if __name__ == "__main__":
    unittest.main()
