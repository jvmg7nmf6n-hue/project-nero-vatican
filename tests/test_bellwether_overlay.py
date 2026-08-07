"""CC-1 Part C: tests for nero_core.execution.bellwether_overlay -- the
conflict-evaluation threshold logic, the circuit breaker, and the ledger write
path (process_orderflow_conflicts). Requires vatican/bellwether importable
(the module adds it to sys.path itself, matching tools/sweep.py's own
convention) -- skipped cleanly if bellwether's own dependencies aren't
installed in this environment.
"""
from __future__ import annotations

import tempfile
import unittest
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

try:
    from nero_core.execution.bellwether_overlay import (
        BellwetherCircuitBreakerOpen,
        _evaluate_entry,
        build_real_macro_events,
        process_orderflow_conflicts,
        run_bellwether_with_circuit_breaker,
    )
    from nero_core.execution.live_scheduler import ORDERFLOW_ID, ORDERFLOW_VERSION
    from nero_core.truth_ledger.execution_log import insert_execution_log_row
    from nero_core.truth_ledger.macro_reads import insert_macro_read, list_macro_conflict_flags
    _IMPORT_ERROR = None
except Exception as exc:  # noqa: BLE001 -- environment-dependent soft skip, not a code bug
    _IMPORT_ERROR = exc


@dataclass
class _FakeEntry:
    id: int
    reasoning: str
    timestamp: datetime


@unittest.skipIf(_IMPORT_ERROR is not None, f"bellwether not importable in this environment: {_IMPORT_ERROR}")
class EvaluateEntryTest(unittest.TestCase):
    def _read(self, bias="BEARISH", agreement=0.7, coverage=0.3, provenance="mixed"):
        return _FakeRead(bias=bias, agreement=agreement, coverage=coverage,
                         provenance_breakdown={"bitcoin_analysis": provenance})

    def test_long_entry_flagged_when_bearish_aligned_and_covered(self) -> None:
        entry = _FakeEntry(id=1, reasoning="direction=LONG stop_loss=100.0 imbalance_ratio=3.5", timestamp=datetime.now(timezone.utc))
        conflicted, reason, direction = _evaluate_entry(entry, self._read(bias="BEARISH", agreement=0.7, coverage=0.3))
        self.assertTrue(conflicted)
        self.assertEqual(direction, "LONG")

    def test_short_entry_flagged_when_bullish_aligned_and_covered(self) -> None:
        entry = _FakeEntry(id=2, reasoning="direction=SHORT stop_loss=100.0 imbalance_ratio=0.2", timestamp=datetime.now(timezone.utc))
        conflicted, reason, direction = _evaluate_entry(entry, self._read(bias="STRONG_BULLISH", agreement=0.65, coverage=0.2))
        self.assertTrue(conflicted)
        self.assertEqual(direction, "SHORT")

    def test_not_flagged_when_same_direction(self) -> None:
        entry = _FakeEntry(id=3, reasoning="direction=LONG stop_loss=100.0 imbalance_ratio=3.5", timestamp=datetime.now(timezone.utc))
        conflicted, _, _ = _evaluate_entry(entry, self._read(bias="BULLISH", agreement=0.9, coverage=0.9))
        self.assertFalse(conflicted)

    def test_not_flagged_when_agreement_below_threshold(self) -> None:
        entry = _FakeEntry(id=4, reasoning="direction=LONG stop_loss=100.0 imbalance_ratio=3.5", timestamp=datetime.now(timezone.utc))
        conflicted, reason, _ = _evaluate_entry(entry, self._read(bias="BEARISH", agreement=0.4, coverage=0.5))
        self.assertFalse(conflicted)
        self.assertIn("agreement", reason)

    def test_not_flagged_when_coverage_below_threshold(self) -> None:
        entry = _FakeEntry(id=5, reasoning="direction=LONG stop_loss=100.0 imbalance_ratio=3.5", timestamp=datetime.now(timezone.utc))
        conflicted, reason, _ = _evaluate_entry(entry, self._read(bias="BEARISH", agreement=0.9, coverage=0.05))
        self.assertFalse(conflicted)
        self.assertIn("coverage", reason)

    def test_not_flagged_when_macro_read_is_synthetic(self) -> None:
        """Circuit-breaker-adjacent guard at the evaluation level: even a
        stored read must never flag anything if ITS OWN bitcoin provenance
        wasn't real/mixed."""
        entry = _FakeEntry(id=6, reasoning="direction=LONG stop_loss=100.0 imbalance_ratio=3.5", timestamp=datetime.now(timezone.utc))
        conflicted, reason, _ = _evaluate_entry(entry, self._read(bias="BEARISH", agreement=0.9, coverage=0.9, provenance="synthetic"))
        self.assertFalse(conflicted)
        self.assertIn("provenance", reason)

    def test_insufficient_data_when_no_macro_read_exists(self) -> None:
        entry = _FakeEntry(id=7, reasoning="direction=LONG stop_loss=100.0 imbalance_ratio=3.5", timestamp=datetime.now(timezone.utc))
        conflicted, reason, direction = _evaluate_entry(entry, None)
        self.assertFalse(conflicted)
        self.assertEqual(direction, "LONG")
        self.assertIn("no macro read exists", reason)

    def test_unparseable_direction_never_flags(self) -> None:
        entry = _FakeEntry(id=8, reasoning="garbage reasoning with no direction field", timestamp=datetime.now(timezone.utc))
        conflicted, reason, direction = _evaluate_entry(entry, self._read())
        self.assertFalse(conflicted)
        self.assertIsNone(direction)


@dataclass
class _FakeRead:
    bias: str
    agreement: float
    coverage: float
    provenance_breakdown: dict


@unittest.skipIf(_IMPORT_ERROR is not None, f"bellwether not importable in this environment: {_IMPORT_ERROR}")
class ProcessOrderflowConflictsTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self._tmp.name) / "test_truth_ledger.db"
        self.addCleanup(self._tmp.cleanup)

    def test_every_entry_gets_exactly_one_flag_ever(self) -> None:
        entry_ts = datetime.now(timezone.utc) - timedelta(hours=1)
        insert_execution_log_row(
            run_id="r1", strategy=ORDERFLOW_ID, strategy_version=ORDERFLOW_VERSION, asset="BTC",
            signal_type="ENTRY", reasoning="direction=LONG stop_loss=90.0 imbalance_ratio=3.5",
            candle_timestamp=1, entry_price=100.0, timestamp=entry_ts, db_path=self.db_path,
        )
        insert_macro_read(
            run_id="mr1", asset="BITCOIN", bias="BEARISH", confidence=0.5, agreement=0.7,
            coverage=0.3, probability_up=0.3, provenance_breakdown={"bitcoin_analysis": "mixed"},
            reasoning="r", risks=[], alternative_scenarios=[], data_mode="live",
            timestamp=entry_ts - timedelta(minutes=30), db_path=self.db_path,
        )
        conflicts = process_orderflow_conflicts(db_path=self.db_path)
        self.assertEqual(len(conflicts), 1)
        flags = list_macro_conflict_flags(db_path=self.db_path)
        self.assertEqual(len(flags), 1)
        self.assertTrue(flags[0].conflicted)

        # Re-running must never re-flag the same entry.
        conflicts_again = process_orderflow_conflicts(db_path=self.db_path)
        self.assertEqual(len(conflicts_again), 0)
        self.assertEqual(len(list_macro_conflict_flags(db_path=self.db_path)), 1)

    def test_no_lookahead_entry_before_any_macro_read_is_insufficient_data(self) -> None:
        entry_ts = datetime.now(timezone.utc) - timedelta(days=2)
        insert_execution_log_row(
            run_id="r1", strategy=ORDERFLOW_ID, strategy_version=ORDERFLOW_VERSION, asset="BTC",
            signal_type="ENTRY", reasoning="direction=SHORT stop_loss=110.0 imbalance_ratio=0.2",
            candle_timestamp=1, entry_price=100.0, timestamp=entry_ts, db_path=self.db_path,
        )
        # Macro read exists only AFTER the entry -- must not be used.
        insert_macro_read(
            run_id="mr1", asset="BITCOIN", bias="BULLISH", confidence=0.5, agreement=0.9,
            coverage=0.9, probability_up=0.9, provenance_breakdown={"bitcoin_analysis": "real"},
            reasoning="r", risks=[], alternative_scenarios=[], data_mode="live",
            timestamp=entry_ts + timedelta(hours=1), db_path=self.db_path,
        )
        conflicts = process_orderflow_conflicts(db_path=self.db_path)
        self.assertEqual(len(conflicts), 0)
        flags = list_macro_conflict_flags(db_path=self.db_path)
        self.assertEqual(flags[0].status, "insufficient_data")


@unittest.skipIf(_IMPORT_ERROR is not None, f"bellwether not importable in this environment: {_IMPORT_ERROR}")
class CircuitBreakerTest(unittest.TestCase):
    """Bellwether can never take the live system down: any exception, or a
    synthetic-only bitcoin_analysis provenance, must raise
    BellwetherCircuitBreakerOpen -- never propagate the original exception,
    never return a usable-looking output."""

    def test_exception_from_orchestrator_trips_the_breaker(self) -> None:
        import nero_core.execution.bellwether_overlay as overlay_mod
        from unittest.mock import patch

        async def _boom():
            raise RuntimeError("simulated Bellwether failure")

        with patch.object(overlay_mod, "_run_bellwether_live", _boom):
            with self.assertRaises(overlay_mod.BellwetherCircuitBreakerOpen):
                overlay_mod.run_bellwether_with_circuit_breaker()

    def test_synthetic_only_bitcoin_read_trips_the_breaker(self) -> None:
        import nero_core.execution.bellwether_overlay as overlay_mod
        from unittest.mock import patch

        class _FakeProvenance:
            value = "synthetic"

        class _FakeOutput:
            provenance_breakdown = {"bitcoin_analysis": _FakeProvenance()}

        async def _fake_output():
            return _FakeOutput()

        with patch.object(overlay_mod, "_run_bellwether_live", _fake_output):
            with self.assertRaises(overlay_mod.BellwetherCircuitBreakerOpen):
                overlay_mod.run_bellwether_with_circuit_breaker()


@unittest.skipIf(_IMPORT_ERROR is not None, f"bellwether not importable in this environment: {_IMPORT_ERROR}")
class BuildRealMacroEventsTest(unittest.TestCase):
    """CC-1 directive (2026-08-07, "wire the 2 safest agents real"), Item 2e:
    build_real_macro_events must produce real MacroEvents from a genuine RSS
    match, and must NEVER pass through news_feed.py's own FALLBACK_HEADLINES
    (illustrative, not real) as if they were real events."""

    def test_live_result_produces_matching_macro_events(self) -> None:
        from unittest.mock import patch

        from nero_core.data_sources.news_feed import NewsFeedResult, NewsItem

        fake_item = NewsItem(
            title="Fed officials signal caution as markets reassess rate cut timing.",
            source="Reuters", link="https://example.com/1",
            published="Fri, 07 Aug 2026 12:00:00 GMT", tags=["Central Banks"],
        )
        fake_result = NewsFeedResult(headlines=[fake_item], status="live (1 matched)")

        with patch("nero_core.data_sources.news_feed.NewsFeedClient.load", return_value=fake_result):
            events = build_real_macro_events()

        self.assertGreater(len(events), 0)
        matching = [e for e in events if e.headline == fake_item.title]
        self.assertEqual(len(matching), 1)
        event = matching[0]
        self.assertEqual(event.source, "Reuters")
        self.assertEqual(str(event.url), fake_item.link)
        from bellwether.schemas import Category
        self.assertEqual(event.category, Category.MONETARY_POLICY)  # "Central Banks" -> MONETARY_POLICY

    def test_fallback_result_produces_zero_events_never_fabricated_ones(self) -> None:
        """The exact honesty requirement: a fallback/no-match result must
        mean zero real events for that asset, never news_feed.py's own
        FALLBACK_HEADLINES text passed through as if it were real."""
        from unittest.mock import patch

        from nero_core.data_sources.news_feed import FALLBACK_HEADLINES, NewsFeedResult, NewsItem

        fallback_item = NewsItem(
            title=FALLBACK_HEADLINES[0], source="Sample Macro Feed", link="",
            published="", tags=[],
        )
        fallback_result = NewsFeedResult(headlines=[fallback_item], status="fallback: no matching headlines")

        with patch("nero_core.data_sources.news_feed.NewsFeedClient.load", return_value=fallback_result):
            events = build_real_macro_events()

        headlines = {e.headline for e in events}
        self.assertNotIn(FALLBACK_HEADLINES[0], headlines)
        self.assertEqual(events, [])

    def test_duplicate_headline_across_both_assets_is_deduped(self) -> None:
        from unittest.mock import patch

        from nero_core.data_sources.news_feed import NewsFeedResult, NewsItem

        shared_item = NewsItem(
            title="Shared macro headline appearing in both asset queries.",
            source="CNBC", link="", published="", tags=[],
        )
        shared_result = NewsFeedResult(headlines=[shared_item], status="live (1 matched)")

        with patch("nero_core.data_sources.news_feed.NewsFeedClient.load", return_value=shared_result):
            events = build_real_macro_events()

        matching = [e for e in events if e.headline == shared_item.title]
        self.assertEqual(len(matching), 1)  # GOLD and BTC both surfaced it -- only one MacroEvent, not two

    def test_unmapped_category_tag_defaults_to_other_not_guessed(self) -> None:
        from unittest.mock import patch

        from nero_core.data_sources.news_feed import NewsFeedResult, NewsItem

        item = NewsItem(title="Some commodity headline.", source="MarketWatch Economy",
                        link="", published="", tags=["Commodities"])
        result = NewsFeedResult(headlines=[item], status="live (1 matched)")

        with patch("nero_core.data_sources.news_feed.NewsFeedClient.load", return_value=result):
            events = build_real_macro_events()

        from bellwether.schemas import Category
        matching = [e for e in events if e.headline == item.title]
        self.assertEqual(matching[0].category, Category.OTHER)

    def test_unparseable_pubdate_falls_back_to_default_factory_not_a_crash(self) -> None:
        from unittest.mock import patch

        from nero_core.data_sources.news_feed import NewsFeedResult, NewsItem

        item = NewsItem(title="Headline with a malformed pubDate.", source="Reuters",
                        link="", published="not-a-real-date", tags=[])
        result = NewsFeedResult(headlines=[item], status="live (1 matched)")

        with patch("nero_core.data_sources.news_feed.NewsFeedClient.load", return_value=result):
            events = build_real_macro_events()  # must not raise

        matching = [e for e in events if e.headline == item.title]
        self.assertEqual(len(matching), 1)
        self.assertIsNotNone(matching[0].published_at)


if __name__ == "__main__":
    unittest.main()
