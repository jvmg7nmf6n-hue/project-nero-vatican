"""CC-1 overnight directive, Part 4: tests for
nero_core.execution.export_news_sentiment -- the all-time news_sentiment_log
export, scoped previously, never built, until this directive."""
from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from nero_core.execution.export_news_sentiment import build_news_sentiment_export, write_news_sentiment_export
from nero_core.truth_ledger.execution_log import insert_news_sentiment_log


class ExportNewsSentimentTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self._tmp.name) / "truth_ledger.db"
        self.addCleanup(self._tmp.cleanup)


class BuildNewsSentimentExportTest(ExportNewsSentimentTestCase):
    def test_real_row_is_exported_with_every_field(self) -> None:
        insert_news_sentiment_log(
            run_id="r1", asset="GOLD", strategy_version="news-sentiment-v1.0.0",
            fetch_timestamp=datetime(2026, 7, 18, 19, 39, 46, tzinfo=timezone.utc),
            signal_type="NEUTRAL", confidence=0.0, reasoning="score 0 from 9 eligible headlines",
            source="local", sentiment_score=0, db_path=self.db_path,
        )
        entries = build_news_sentiment_export(db_path=self.db_path)
        self.assertEqual(len(entries), 1)
        e = entries[0]
        self.assertEqual(e["asset"], "GOLD")
        self.assertEqual(e["strategy_version"], "news-sentiment-v1.0.0")
        self.assertEqual(e["signal_type"], "NEUTRAL")
        self.assertEqual(e["confidence"], 0.0)
        self.assertEqual(e["sentiment_score"], 0)
        self.assertEqual(e["source"], "local")
        self.assertIsNone(e["news_timestamp"])
        self.assertIn("2026-07-18", e["fetch_timestamp"])

    def test_empty_db_exports_an_empty_list_never_an_error(self) -> None:
        self.assertEqual(build_news_sentiment_export(db_path=self.db_path), [])

    def test_both_real_strategy_versions_are_included_together(self) -> None:
        """v1.0.0 (keyword) and v2.0.0-llm-claude run in parallel for direct
        comparison -- both must appear in the same export, never one
        silently excluded."""
        insert_news_sentiment_log(
            run_id="r1", asset="BTC", strategy_version="news-sentiment-v1.0.0",
            fetch_timestamp=datetime(2026, 8, 1, tzinfo=timezone.utc),
            signal_type="SELL_BIAS", confidence=0.6, reasoning="keyword", source="local",
            sentiment_score=-6, db_path=self.db_path,
        )
        insert_news_sentiment_log(
            run_id="r2", asset="BTC", strategy_version="news-sentiment-v2.0.0-llm-claude",
            fetch_timestamp=datetime(2026, 8, 2, tzinfo=timezone.utc),
            signal_type="NEUTRAL", confidence=0.0, reasoning="llm", source="claude", db_path=self.db_path,
        )
        entries = build_news_sentiment_export(db_path=self.db_path)
        versions = {e["strategy_version"] for e in entries}
        self.assertEqual(versions, {"news-sentiment-v1.0.0", "news-sentiment-v2.0.0-llm-claude"})


class WriteNewsSentimentExportTest(ExportNewsSentimentTestCase):
    def test_writes_schema_versioned_json(self) -> None:
        out_path = Path(self._tmp.name) / "news_sentiment.json"
        write_news_sentiment_export(output_path=out_path, db_path=self.db_path)
        payload = json.loads(out_path.read_text())
        self.assertEqual(payload["schema_version"], 1)
        self.assertIn("last_updated", payload)
        self.assertEqual(payload["entries"], [])

    def test_never_leaks_a_local_filesystem_path(self) -> None:
        insert_news_sentiment_log(
            run_id="r1", asset="GOLD", strategy_version="news-sentiment-v1.0.0",
            fetch_timestamp=datetime(2026, 8, 1, tzinfo=timezone.utc),
            signal_type="NEUTRAL", confidence=0.0, reasoning="x", source="local", db_path=self.db_path,
        )
        out_path = Path(self._tmp.name) / "news_sentiment.json"
        write_news_sentiment_export(output_path=out_path, db_path=self.db_path)
        raw_text = out_path.read_text()
        self.assertNotIn(str(self.db_path), raw_text)


if __name__ == "__main__":
    unittest.main()
