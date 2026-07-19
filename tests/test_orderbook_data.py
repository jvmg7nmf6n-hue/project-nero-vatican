from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

from nero_core.data_sources.orderbook_data import (
    BINANCE_COM_DEPTH_URL,
    BINANCE_VISION_DEPTH_URL,
    OrderbookDataUnavailableError,
    fetch_and_cache_snapshot,
    fetch_orderbook_snapshot,
    insert_orderbook_snapshot,
    latest_orderbook_snapshot,
)

NOW = datetime(2026, 7, 19, 12, 0, tzinfo=timezone.utc)


def _depth_payload(bids=None, asks=None) -> dict:
    return {
        "bids": bids if bids is not None else [["100.0", "2.0"], ["99.9", "1.0"]],
        "asks": asks if asks is not None else [["100.1", "1.0"], ["100.2", "1.0"]],
    }


def _mock_response(payload: dict) -> MagicMock:
    m = MagicMock()
    m.raise_for_status.return_value = None
    m.json.return_value = payload
    return m


class DepthParsingTest(unittest.TestCase):
    def test_valid_payload_computes_correct_volumes_and_ratio(self) -> None:
        payload = _depth_payload(bids=[["100.0", "3.0"], ["99.9", "2.0"]], asks=[["100.1", "1.0"], ["100.2", "1.0"]])
        with patch("nero_core.data_sources.orderbook_data.requests.get", return_value=_mock_response(payload)):
            snapshot = fetch_orderbook_snapshot("BTCUSDT", now=NOW)

        self.assertEqual(snapshot.best_bid, 100.0)
        self.assertEqual(snapshot.best_ask, 100.1)
        self.assertEqual(snapshot.bid_vol_20, 5.0)
        self.assertEqual(snapshot.ask_vol_20, 2.0)
        self.assertEqual(snapshot.imbalance_ratio, 2.5)
        self.assertEqual(snapshot.source, "data-api.binance.vision")

    def test_empty_bids_falls_through_to_secondary_then_raises(self) -> None:
        with patch("nero_core.data_sources.orderbook_data.requests.get") as mock_get:
            mock_get.return_value = _mock_response(_depth_payload(bids=[], asks=[["1", "1"]]))
            with self.assertRaises(OrderbookDataUnavailableError):
                fetch_orderbook_snapshot("BTCUSDT", now=NOW)
            self.assertEqual(mock_get.call_count, 2)  # tried both endpoints

    def test_corrupt_payload_falls_through_to_secondary(self) -> None:
        good = _mock_response(_depth_payload())
        with patch("nero_core.data_sources.orderbook_data.requests.get", side_effect=[ValueError("bad json"), good]):
            snapshot = fetch_orderbook_snapshot("BTCUSDT", now=NOW)
        self.assertEqual(snapshot.source, "api.binance.com")


class DivideByZeroGuardTest(unittest.TestCase):
    def test_zero_ask_volume_yields_none_ratio_not_infinity(self) -> None:
        payload = _depth_payload(bids=[["100.0", "5.0"]], asks=[["100.1", "0.0"]])
        with patch("nero_core.data_sources.orderbook_data.requests.get", return_value=_mock_response(payload)):
            snapshot = fetch_orderbook_snapshot("BTCUSDT", now=NOW)
        self.assertIsNone(snapshot.imbalance_ratio)


class EndpointFallbackTest(unittest.TestCase):
    def test_primary_network_failure_falls_back_to_secondary(self) -> None:
        import requests

        good = _mock_response(_depth_payload())
        with patch(
            "nero_core.data_sources.orderbook_data.requests.get",
            side_effect=[requests.exceptions.ConnectionError("451 blocked"), good],
        ) as mock_get:
            snapshot = fetch_orderbook_snapshot("BTCUSDT", now=NOW)
        self.assertEqual(snapshot.source, "api.binance.com")
        first_call_url = mock_get.call_args_list[0].args[0]
        second_call_url = mock_get.call_args_list[1].args[0]
        self.assertEqual(first_call_url, BINANCE_VISION_DEPTH_URL)
        self.assertEqual(second_call_url, BINANCE_COM_DEPTH_URL)

    def test_both_endpoints_failing_raises_with_both_reasons(self) -> None:
        import requests

        with patch(
            "nero_core.data_sources.orderbook_data.requests.get",
            side_effect=requests.exceptions.ConnectionError("blocked"),
        ):
            with self.assertRaises(OrderbookDataUnavailableError) as ctx:
                fetch_orderbook_snapshot("BTCUSDT", now=NOW)
        self.assertIn("data-api.binance.vision", str(ctx.exception))
        self.assertIn("api.binance.com", str(ctx.exception))


class CacheTableTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self._tmp.name) / "test_truth_ledger.db"
        self.addCleanup(self._tmp.cleanup)

    def test_insert_and_retrieve_latest_snapshot(self) -> None:
        payload = _depth_payload()
        with patch("nero_core.data_sources.orderbook_data.requests.get", return_value=_mock_response(payload)):
            snapshot = fetch_and_cache_snapshot("BTCUSDT", now=NOW, db_path=self.db_path)

        latest = latest_orderbook_snapshot("BTCUSDT", db_path=self.db_path)
        self.assertIsNotNone(latest)
        self.assertEqual(latest.symbol, "BTCUSDT")
        self.assertEqual(latest.best_bid, snapshot.best_bid)
        self.assertEqual(latest.imbalance_ratio, snapshot.imbalance_ratio)

    def test_no_snapshot_returns_none(self) -> None:
        self.assertIsNone(latest_orderbook_snapshot("ETHUSDT", db_path=self.db_path))

    def test_multiple_inserts_keep_latest_by_timestamp(self) -> None:
        payload = _depth_payload()
        with patch("nero_core.data_sources.orderbook_data.requests.get", return_value=_mock_response(payload)):
            fetch_and_cache_snapshot("BTCUSDT", now=datetime(2026, 7, 19, 10, 0, tzinfo=timezone.utc), db_path=self.db_path)
            fetch_and_cache_snapshot("BTCUSDT", now=datetime(2026, 7, 19, 11, 0, tzinfo=timezone.utc), db_path=self.db_path)

        latest = latest_orderbook_snapshot("BTCUSDT", db_path=self.db_path)
        self.assertEqual(latest.timestamp, datetime(2026, 7, 19, 11, 0, tzinfo=timezone.utc))

    def test_fetch_and_cache_does_not_cache_on_failure(self) -> None:
        import requests

        with patch(
            "nero_core.data_sources.orderbook_data.requests.get",
            side_effect=requests.exceptions.ConnectionError("blocked"),
        ):
            with self.assertRaises(OrderbookDataUnavailableError):
                fetch_and_cache_snapshot("BTCUSDT", now=NOW, db_path=self.db_path)
        self.assertIsNone(latest_orderbook_snapshot("BTCUSDT", db_path=self.db_path))


if __name__ == "__main__":
    unittest.main()
