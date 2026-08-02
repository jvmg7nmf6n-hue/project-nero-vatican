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


# Default data_source represents a CONFIRMED-CLEAN row -- every test in this file
# that builds a round trip and expects it to count as resolved is implicitly
# asserting "clean data behaves as before the quarantine fix" (see
# QuarantineAwareStatsTest below for the None/mismatched-source cases this default
# deliberately does NOT cover).
CLEAN_SOURCE = "TEST_SOURCE"


def _row(id_: int, run_id: str, strategy: str, version: str, asset: str, signal_type: str,
         candle_timestamp: int, entry_price=None, exit_price=None, reasoning: str = "x",
         data_source: str | None = CLEAN_SOURCE) -> ExecutionLogRow:
    return ExecutionLogRow(
        id=id_, run_id=run_id, timestamp=NOW, strategy=strategy, strategy_version=version, asset=asset,
        signal_type=signal_type, entry_price=entry_price, exit_price=exit_price, reasoning=reasoning,
        candle_timestamp=candle_timestamp, created_at=NOW, data_source=data_source,
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
        expected_fields = {
            "timestamp", "strategy", "strategy_version", "asset", "signal_type",
            "entry_price", "exit_price", "reasoning", "candle_timestamp",
        }
        self.assertEqual(set(export["rows"][0].keys()), expected_fields)

    def test_run_id_is_not_leaked(self) -> None:
        rows = [_row(1, "secret-run-id", GOLD_STRATEGY, GOLD_VERSION, "GOLD", "ENTRY", candle_timestamp=1000, entry_price=2400.0)]
        export = build_ledger_export(rows, now=NOW)
        self.assertNotIn("run_id", export["rows"][0])

    def test_strategy_version_is_included_for_individual_strategy_pages(self) -> None:
        # Added for Step 4 (individual strategy pages): without it, two configs that
        # share a (strategy, asset) but differ only by version -- e.g.
        # RANGE_MEAN_REVERSION long-only vs confirmation, both on BTC -- would have
        # their trade histories silently merged on the public ledger export. Unlike
        # run_id (pure internal bookkeeping), strategy_version is already public in
        # stats.json and strategies.json, so exposing it here leaks nothing new.
        rows = [_row(1, "r1", GOLD_STRATEGY, GOLD_VERSION, "GOLD", "ENTRY", candle_timestamp=1000, entry_price=2400.0)]
        export = build_ledger_export(rows, now=NOW)
        self.assertEqual(export["rows"][0]["strategy_version"], GOLD_VERSION)

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
                # Donchian Cross-Asset Deep-Dive promotion list -- GOLD/1week/N20 is
                # the last entry appended to SINGLE_ASSET_CONFIGS.
                "DONCHIAN_TREND",
                PAIRS_STRATEGY,
                "ORDERFLOW_IMBALANCE",
                "ORDERFLOW_IMBALANCE",
                # Three New Hypothesis Batch, post-batch promotion list --
                # GOLD_SILVER_RATIO_MR/1day + PEAD (7 tickers x 2 configs).
                "GOLD_SILVER_RATIO_MR",
                *(["PEAD"] * 14),
                # Donchian Cross-Asset Deep-Dive promotion list -- EUR/USD, GBP/USD
                # (N20), USD/JPY (N40), fetched via a separate DONCHIAN_FOREX_CONFIGS
                # list (MarketDataClient has no forex routing), appended last.
                *(["DONCHIAN_TREND"] * 3),
            ],
        )


class QuarantineAwareStatsTest(unittest.TestCase):
    """Structural fix (2026-07-30): _strategy_stats must run every round trip
    through nero_core.execution.quarantine's exclude functions before aggregating
    -- confirmed here for a synthetic strategy (GOLD_STRATEGY/BNB_STRATEGY, same
    fixtures RoundTripStatsTest uses), not an ORDERFLOW-specific check, since the
    fix lives in the shared function every roster entry runs through."""

    def test_unrecorded_source_round_trip_is_excluded_but_counted_as_unverified(self) -> None:
        rows = [
            _row(1, "r1", GOLD_STRATEGY, GOLD_VERSION, "GOLD", "ENTRY", candle_timestamp=1000,
                 entry_price=100.0, data_source=None),
            _row(2, "r1", GOLD_STRATEGY, GOLD_VERSION, "GOLD", "EXIT", candle_timestamp=2000, exit_price=110.0,
                 reasoning="TARGET exit, r_multiple=1.250", data_source=None),
        ]
        export = build_stats_export(rows, now=NOW)
        gold_stats = next(s for s in export["strategies"] if s["strategy"] == GOLD_STRATEGY)

        self.assertEqual(gold_stats["resolved_trades"], 0)
        self.assertEqual(gold_stats["unverified_trades"], 1)
        self.assertIsNone(gold_stats["win_rate"])
        self.assertIsNone(gold_stats["avg_return_pct"])
        self.assertIsNone(gold_stats["expectancy_r"])

    def test_mismatched_source_round_trip_is_excluded_but_counted_as_unverified(self) -> None:
        rows = [
            _row(1, "r1", GOLD_STRATEGY, GOLD_VERSION, "GOLD", "ENTRY", candle_timestamp=1000,
                 entry_price=100.0, data_source="Binance"),
            _row(2, "r1", GOLD_STRATEGY, GOLD_VERSION, "GOLD", "EXIT", candle_timestamp=2000, exit_price=110.0,
                 reasoning="TARGET exit, r_multiple=1.250", data_source="Coinbase"),
        ]
        export = build_stats_export(rows, now=NOW)
        gold_stats = next(s for s in export["strategies"] if s["strategy"] == GOLD_STRATEGY)

        self.assertEqual(gold_stats["resolved_trades"], 0)
        self.assertEqual(gold_stats["unverified_trades"], 1)
        self.assertIsNone(gold_stats["win_rate"])

    def test_mixed_clean_and_unverified_round_trips_only_averages_the_clean_ones(self) -> None:
        rows = [
            # Clean: 100 -> 110, win.
            _row(1, "r1", BNB_STRATEGY, BNB_VERSION, "BNB", "ENTRY", candle_timestamp=1000, entry_price=100.0),
            _row(2, "r1", BNB_STRATEGY, BNB_VERSION, "BNB", "EXIT", candle_timestamp=2000, exit_price=110.0,
                 reasoning="r_multiple=1.000"),
            # Clean: 200 -> 190, loss.
            _row(3, "r1", BNB_STRATEGY, BNB_VERSION, "BNB", "ENTRY", candle_timestamp=3000, entry_price=200.0),
            _row(4, "r1", BNB_STRATEGY, BNB_VERSION, "BNB", "EXIT", candle_timestamp=4000, exit_price=190.0,
                 reasoning="r_multiple=-1.000"),
            # Unrecorded source: 300 -> 600 (would be a huge win if counted -- must not
            # move win_rate/avg_return_pct at all).
            _row(5, "r1", BNB_STRATEGY, BNB_VERSION, "BNB", "ENTRY", candle_timestamp=5000,
                 entry_price=300.0, data_source=None),
            _row(6, "r1", BNB_STRATEGY, BNB_VERSION, "BNB", "EXIT", candle_timestamp=6000, exit_price=600.0,
                 reasoning="r_multiple=5.000", data_source=None),
        ]
        export = build_stats_export(rows, now=NOW)
        bnb_stats = next(s for s in export["strategies"] if s["strategy"] == BNB_STRATEGY)

        self.assertEqual(bnb_stats["resolved_trades"], 2)
        self.assertEqual(bnb_stats["unverified_trades"], 1)
        self.assertEqual(bnb_stats["win_rate"], 0.5)
        self.assertAlmostEqual(bnb_stats["expectancy_r"], 0.0, places=6)

    def test_trailing_unpaired_entry_with_unrecorded_source_is_not_reported_as_open_position(self) -> None:
        rows = [
            _row(1, "r1", BNB_STRATEGY, BNB_VERSION, "BNB", "ENTRY", candle_timestamp=1000,
                 entry_price=500.0, data_source=None),
        ]
        export = build_stats_export(rows, now=NOW)
        bnb_stats = next(s for s in export["strategies"] if s["strategy"] == BNB_STRATEGY)

        self.assertIsNone(bnb_stats["open_position"])

    def test_trailing_unpaired_entry_with_unrecorded_source_is_flagged_as_unverified_open_entry(self) -> None:
        # Phase 1 Fix A (docs/investigations/phase_a_pead_ledger_anomaly.md):
        # this is the exact MSFT/TSLA/META PEAD shape -- a lone ENTRY with
        # data_source=None, no EXIT. open_position stays honestly None (no
        # confirmed-clean open position exists), but unverified_open_entries
        # must now surface the same "we can't verify this yet" signal
        # unverified_trades already gives the resolved-round-trip case, not a
        # silent, unexplained absence.
        rows = [
            _row(1, "r1", BNB_STRATEGY, BNB_VERSION, "BNB", "ENTRY", candle_timestamp=1000,
                 entry_price=500.0, data_source=None),
        ]
        export = build_stats_export(rows, now=NOW)
        bnb_stats = next(s for s in export["strategies"] if s["strategy"] == BNB_STRATEGY)

        self.assertIsNone(bnb_stats["open_position"])
        self.assertEqual(bnb_stats["unverified_open_entries"], 1)

    def test_a_confirmed_clean_open_entry_reports_zero_unverified_open_entries(self) -> None:
        # Sanity check the other direction: a genuinely clean open position
        # (AAPL/AMZN's real shape) must not be flagged as unverified.
        rows = [
            _row(1, "r1", BNB_STRATEGY, BNB_VERSION, "BNB", "ENTRY", candle_timestamp=1000, entry_price=500.0),
        ]
        export = build_stats_export(rows, now=NOW)
        bnb_stats = next(s for s in export["strategies"] if s["strategy"] == BNB_STRATEGY)

        self.assertIsNotNone(bnb_stats["open_position"])
        self.assertEqual(bnb_stats["unverified_open_entries"], 0)

    def test_unverified_open_entries_is_zero_when_nothing_was_ever_logged(self) -> None:
        export = build_stats_export([], now=NOW)
        for s in export["strategies"]:
            self.assertEqual(s["unverified_open_entries"], 0)

    def test_unverified_trades_is_zero_when_nothing_was_ever_logged(self) -> None:
        # Distinguishes "truly awaiting first signal" (0/0) from "has unverified
        # trades pending" (0 resolved, >0 unverified) -- the website needs both
        # numbers to choose the right honest state (lib/statLine.ts).
        export = build_stats_export([], now=NOW)
        for s in export["strategies"]:
            self.assertEqual(s["unverified_trades"], 0)

    def test_orderflow_quarantine_cutoff_excludes_pre_cutoff_trades_even_with_a_recorded_source(self) -> None:
        # Real cutoffs from nero_core.execution.quarantine.QUARANTINE_CUTOFFS -- a row
        # with a genuinely recorded, matching source is STILL excluded if it predates
        # the documented incident cutoff for its (strategy, version, asset) key.
        from nero_core.execution.quarantine import QUARANTINE_CUTOFFS
        from nero_core.strategies.orderflow_imbalance import STRATEGY_ID, STRATEGY_VERSION

        cutoff = QUARANTINE_CUTOFFS[(STRATEGY_ID, STRATEGY_VERSION, "BTC")]
        rows = [
            _row(1, "r1", STRATEGY_ID, STRATEGY_VERSION, "BTC", "ENTRY", candle_timestamp=cutoff - 10_000,
                 entry_price=100.0, data_source="Binance BTCUSDT 1h candles | orderbook: x"),
            _row(2, "r1", STRATEGY_ID, STRATEGY_VERSION, "BTC", "EXIT", candle_timestamp=cutoff - 5_000,
                 exit_price=110.0, reasoning="r_multiple=1.000", data_source="Binance BTCUSDT 1h candles | orderbook: x"),
        ]
        export = build_stats_export(rows, now=NOW)
        orderflow_btc = next(
            s for s in export["strategies"] if s["strategy"] == STRATEGY_ID and s["asset"] == "BTC"
        )

        self.assertEqual(orderflow_btc["resolved_trades"], 0)
        self.assertEqual(orderflow_btc["unverified_trades"], 1)

    def test_signal_counts_are_not_reduced_by_quarantine(self) -> None:
        # signal_counts is an activity tally, not a performance claim -- it must stay
        # raw even when the round trip it came from is unverified/quarantined.
        rows = [
            _row(1, "r1", GOLD_STRATEGY, GOLD_VERSION, "GOLD", "NO_TRADE", candle_timestamp=500, data_source=None),
            _row(2, "r1", GOLD_STRATEGY, GOLD_VERSION, "GOLD", "ENTRY", candle_timestamp=1000,
                 entry_price=100.0, data_source=None),
            _row(3, "r1", GOLD_STRATEGY, GOLD_VERSION, "GOLD", "EXIT", candle_timestamp=2000, exit_price=110.0,
                 data_source=None),
        ]
        export = build_stats_export(rows, now=NOW)
        gold_stats = next(s for s in export["strategies"] if s["strategy"] == GOLD_STRATEGY)

        self.assertEqual(gold_stats["signal_counts"], {"ENTRY": 1, "EXIT": 1, "WATCH": 0, "NO_TRADE": 1})
        self.assertEqual(gold_stats["resolved_trades"], 0)
        self.assertEqual(gold_stats["unverified_trades"], 1)


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
        self.assertEqual(len(news_entries), 4)  # v1.0.0 x (GOLD, BTC) + v2.0.0-llm-claude x (GOLD, BTC)
        for entry in news_entries:
            self.assertEqual(entry["timeframe"], "daily")

    def test_news_sentiment_v1_and_v2_are_separate_distinct_roster_entries(self) -> None:
        """v2.0.0-llm-claude must appear as its own entry, never merged with or
        mistaken for v1.0.0's row -- both versions run in parallel and must be
        independently visible to the site."""
        export = build_strategies_export(now=NOW)
        news_entries = [e for e in export["strategies"] if e["name"] == "NEWS_SENTIMENT"]
        versions_by_asset = {(e["asset"], e["version"]) for e in news_entries}
        self.assertEqual(
            versions_by_asset,
            {
                ("GOLD", "news-sentiment-v1.0.0"), ("BTC", "news-sentiment-v1.0.0"),
                ("GOLD", "news-sentiment-v2.0.0-llm-claude"), ("BTC", "news-sentiment-v2.0.0-llm-claude"),
            },
        )
        v2_entries = [e for e in news_entries if e["version"] == "news-sentiment-v2.0.0-llm-claude"]
        for entry in v2_entries:
            self.assertTrue(entry["verification_status"].startswith("experimental"))
            self.assertNotIn("watchlist", entry["verification_status"])
            self.assertNotIn("verified —", entry["verification_status"])

    def test_schema_version_and_last_updated_present(self) -> None:
        export = build_strategies_export(now=NOW)
        self.assertEqual(export["schema_version"], SCHEMA_VERSION)
        self.assertEqual(export["last_updated"], NOW.isoformat())

    def test_roster_includes_source_report_from_the_mapping(self) -> None:
        export = build_strategies_export(now=NOW)
        gold_entry = next(e for e in export["strategies"] if e["name"] == GOLD_STRATEGY)
        self.assertEqual(gold_entry["source_report"], "docs/statistical_harness_upgrade.md")

    def test_configs_with_no_historical_backtest_export_a_null_source_report(self) -> None:
        export = build_strategies_export(now=NOW)
        news_entries = [e for e in export["strategies"] if e["name"] == "NEWS_SENTIMENT"]
        self.assertEqual(len(news_entries), 4)
        for entry in news_entries:
            self.assertIsNone(entry["source_report"])

    def test_roster_includes_backtest_evaluation_from_the_mapping(self) -> None:
        # RANGE_MEAN_REVERSION BTC/24h (added this session): the roster export
        # must actually carry the structured DIED/INSUFFICIENT_SAMPLE verdict,
        # not just the free-text verification_status summary.
        export = build_strategies_export(now=NOW)
        long_only = next(
            e for e in export["strategies"]
            if e["name"] == "RANGE_MEAN_REVERSION" and e["version"] == "range-mean-reversion-v1.1.0-long-only"
        )
        self.assertEqual(long_only["backtest_evaluation"]["verdict_is"], "DIED")
        self.assertEqual(long_only["backtest_evaluation"]["verdict_oos"], "INSUFFICIENT_SAMPLE")

    def test_cointegration_pairs_roster_entry_carries_untestable_reason_and_real_evidence(self) -> None:
        export = build_strategies_export(now=NOW)
        pairs_entry = next(e for e in export["strategies"] if e["name"] == PAIRS_STRATEGY)
        evaluation = pairs_entry["backtest_evaluation"]
        self.assertIsNotNone(evaluation["untestable_reason"])
        self.assertEqual(evaluation["is_trades"], 61)
        self.assertEqual(evaluation["oos_trades"], 22)

    def test_configs_with_no_structured_evaluation_export_the_default(self) -> None:
        export = build_strategies_export(now=NOW)
        news_entries = [e for e in export["strategies"] if e["name"] == "NEWS_SENTIMENT"]
        for entry in news_entries:
            self.assertIsNone(entry["backtest_evaluation"]["verdict_is"])
            self.assertIsNotNone(entry["backtest_evaluation"]["note"])


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

    def test_ledger_excludes_unrecorded_source_trade_legs_but_keeps_watch_rows(self) -> None:
        # The unverified ENTRY/EXIT pair (data_source unset -> None) must not appear
        # in the public ledger, but the WATCH row for the same config must -- it's
        # not a trade leg and carries no performance claim.
        insert_execution_log_row(
            run_id="r1", strategy=GOLD_STRATEGY, strategy_version=GOLD_VERSION, asset="GOLD",
            signal_type="WATCH", reasoning="watching", candle_timestamp=500, timestamp=NOW, db_path=self.db_path,
        )
        insert_execution_log_row(
            run_id="r1", strategy=GOLD_STRATEGY, strategy_version=GOLD_VERSION, asset="GOLD",
            signal_type="ENTRY", reasoning="x", candle_timestamp=1000, entry_price=100.0,
            timestamp=NOW, db_path=self.db_path,
        )
        insert_execution_log_row(
            run_id="r1", strategy=GOLD_STRATEGY, strategy_version=GOLD_VERSION, asset="GOLD",
            signal_type="EXIT", reasoning="x", candle_timestamp=2000, exit_price=110.0,
            timestamp=NOW, db_path=self.db_path,
        )

        write_site_data(db_path=self.db_path, output_dir=self.output_dir, now=NOW)

        ledger = json.loads((self.output_dir / "ledger_full.json").read_text(encoding="utf-8"))
        signal_types = [r["signal_type"] for r in ledger["rows"]]
        self.assertIn("WATCH", signal_types)
        self.assertNotIn("ENTRY", signal_types)
        self.assertNotIn("EXIT", signal_types)

    def test_ledger_excludes_mismatched_source_round_trip(self) -> None:
        insert_execution_log_row(
            run_id="r1", strategy=GOLD_STRATEGY, strategy_version=GOLD_VERSION, asset="GOLD",
            signal_type="ENTRY", reasoning="x", candle_timestamp=1000, entry_price=100.0,
            timestamp=NOW, data_source="Binance", db_path=self.db_path,
        )
        insert_execution_log_row(
            run_id="r1", strategy=GOLD_STRATEGY, strategy_version=GOLD_VERSION, asset="GOLD",
            signal_type="EXIT", reasoning="x", candle_timestamp=2000, exit_price=110.0,
            timestamp=NOW, data_source="Coinbase", db_path=self.db_path,
        )

        write_site_data(db_path=self.db_path, output_dir=self.output_dir, now=NOW)

        ledger = json.loads((self.output_dir / "ledger_full.json").read_text(encoding="utf-8"))
        self.assertEqual(ledger["rows"], [])

    def test_ledger_keeps_a_confirmed_clean_round_trip(self) -> None:
        # Regression: a genuinely clean round trip (matching, recorded source) must
        # still appear in the ledger -- this fix must not turn into "hide everything."
        insert_execution_log_row(
            run_id="r1", strategy=GOLD_STRATEGY, strategy_version=GOLD_VERSION, asset="GOLD",
            signal_type="ENTRY", reasoning="x", candle_timestamp=1000, entry_price=100.0,
            timestamp=NOW, data_source="Binance", db_path=self.db_path,
        )
        insert_execution_log_row(
            run_id="r1", strategy=GOLD_STRATEGY, strategy_version=GOLD_VERSION, asset="GOLD",
            signal_type="EXIT", reasoning="x", candle_timestamp=2000, exit_price=110.0,
            timestamp=NOW, data_source="Binance", db_path=self.db_path,
        )

        write_site_data(db_path=self.db_path, output_dir=self.output_dir, now=NOW)

        ledger = json.loads((self.output_dir / "ledger_full.json").read_text(encoding="utf-8"))
        self.assertEqual([r["signal_type"] for r in ledger["rows"]], ["EXIT", "ENTRY"])  # newest first

        stats = json.loads((self.output_dir / "stats.json").read_text(encoding="utf-8"))
        gold_stats = next(s for s in stats["strategies"] if s["strategy"] == GOLD_STRATEGY)
        self.assertEqual(gold_stats["resolved_trades"], 1)
        self.assertEqual(gold_stats["unverified_trades"], 0)


if __name__ == "__main__":
    unittest.main()
