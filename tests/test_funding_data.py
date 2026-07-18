from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import pandas as pd
import requests

from nero_core.data_sources.funding_data import (
    FUNDING_ASSETS,
    FundingDataUnavailableError,
    history_depth_report,
    load_funding_history,
)

EIGHT_HOURS_MS = 8 * 3_600_000


def _settlement(funding_time_ms: int, rate: float) -> dict[str, object]:
    return {"symbol": "BTCUSDT", "fundingTime": funding_time_ms, "fundingRate": str(rate), "markPrice": "50000.0"}


def _make_page(start_ms: int, count: int, rate: float = 0.0001) -> list[dict[str, object]]:
    return [_settlement(start_ms + i * EIGHT_HOURS_MS, rate) for i in range(count)]


class FundingDataTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.cache_dir = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)


class LoadFundingHistoryPaginationTest(FundingDataTestCase):
    def test_stops_pagination_on_a_short_page(self) -> None:
        first_page = _make_page(0, 3)
        second_page = _make_page(3 * EIGHT_HOURS_MS, 2)  # shorter than the (patched) limit -> stop here

        mock_responses = [MagicMock(json=MagicMock(return_value=first_page)), MagicMock(json=MagicMock(return_value=second_page))]
        for r in mock_responses:
            r.raise_for_status = MagicMock()

        with patch("nero_core.data_sources.funding_data.BINANCE_FUNDING_MAX_LIMIT", 3), \
             patch("nero_core.data_sources.funding_data.requests.get", side_effect=mock_responses):
            result = load_funding_history("BTC", cache_dir=self.cache_dir, use_cache=False)

        self.assertEqual(len(result.settlements), 5)
        self.assertEqual(result.asset, "BTC")
        self.assertFalse(result.from_cache)
        self.assertTrue(result.source.startswith("NATIVE:"))

    def test_stops_pagination_on_an_empty_page(self) -> None:
        first_page = _make_page(0, 3)
        with patch("nero_core.data_sources.funding_data.BINANCE_FUNDING_MAX_LIMIT", 3), \
             patch(
                 "nero_core.data_sources.funding_data.requests.get",
                 side_effect=[
                     MagicMock(json=MagicMock(return_value=first_page), raise_for_status=MagicMock()),
                     MagicMock(json=MagicMock(return_value=[]), raise_for_status=MagicMock()),
                 ],
             ):
            result = load_funding_history("BTC", cache_dir=self.cache_dir, use_cache=False)

        self.assertEqual(len(result.settlements), 3)

    def test_network_error_raises_funding_data_unavailable(self) -> None:
        with patch("nero_core.data_sources.funding_data.requests.get", side_effect=requests.exceptions.ConnectionError("down")):
            with self.assertRaises(FundingDataUnavailableError):
                load_funding_history("BTC", cache_dir=self.cache_dir, use_cache=False)

    def test_empty_response_raises_funding_data_unavailable(self) -> None:
        with patch(
            "nero_core.data_sources.funding_data.requests.get",
            return_value=MagicMock(json=MagicMock(return_value=[]), raise_for_status=MagicMock()),
        ):
            with self.assertRaises(FundingDataUnavailableError):
                load_funding_history("BTC", cache_dir=self.cache_dir, use_cache=False)

    def test_settlement_time_is_stored_verbatim_not_derived(self) -> None:
        page = _make_page(1_700_000_000_000, 2, rate=-0.0005)
        with patch("nero_core.data_sources.funding_data.BINANCE_FUNDING_MAX_LIMIT", 1000), \
             patch(
                 "nero_core.data_sources.funding_data.requests.get",
                 return_value=MagicMock(json=MagicMock(return_value=page), raise_for_status=MagicMock()),
             ):
            result = load_funding_history("BTC", cache_dir=self.cache_dir, use_cache=False)

        self.assertEqual(list(result.settlements["settlement_time"]), [1_700_000_000_000, 1_700_000_000_000 + EIGHT_HOURS_MS])
        self.assertEqual(list(result.settlements["funding_rate"]), [-0.0005, -0.0005])

    def test_duplicate_settlements_across_pages_are_dropped(self) -> None:
        overlapping_first = _make_page(0, 3)
        overlapping_second = _make_page(2 * EIGHT_HOURS_MS, 2)  # re-includes the last item of the first page
        with patch("nero_core.data_sources.funding_data.BINANCE_FUNDING_MAX_LIMIT", 3), \
             patch(
                 "nero_core.data_sources.funding_data.requests.get",
                 side_effect=[
                     MagicMock(json=MagicMock(return_value=overlapping_first), raise_for_status=MagicMock()),
                     MagicMock(json=MagicMock(return_value=overlapping_second), raise_for_status=MagicMock()),
                 ],
             ):
            result = load_funding_history("BTC", cache_dir=self.cache_dir, use_cache=False)

        self.assertEqual(len(result.settlements), 4)  # 0, 1, 2, 3 (index 2 deduplicated)


class LoadFundingHistoryCachingTest(FundingDataTestCase):
    def test_writes_cache_after_a_live_fetch(self) -> None:
        page = _make_page(0, 4)
        with patch(
            "nero_core.data_sources.funding_data.requests.get",
            return_value=MagicMock(json=MagicMock(return_value=page), raise_for_status=MagicMock()),
        ):
            load_funding_history("ETH", cache_dir=self.cache_dir, use_cache=False)

        self.assertTrue((self.cache_dir / "ETH_funding.csv").exists())

    def test_second_call_reads_cache_without_hitting_network(self) -> None:
        page = _make_page(0, 4)
        with patch(
            "nero_core.data_sources.funding_data.requests.get",
            return_value=MagicMock(json=MagicMock(return_value=page), raise_for_status=MagicMock()),
        ):
            load_funding_history("SOL", cache_dir=self.cache_dir, use_cache=True)

        def _explode(*_args, **_kwargs):
            raise AssertionError("must not hit the network when a cache exists")

        with patch("nero_core.data_sources.funding_data.requests.get", side_effect=_explode):
            result = load_funding_history("SOL", cache_dir=self.cache_dir, use_cache=True)

        self.assertTrue(result.from_cache)
        self.assertEqual(len(result.settlements), 4)

    def test_force_refresh_bypasses_the_cache(self) -> None:
        first_page = _make_page(0, 4)
        with patch(
            "nero_core.data_sources.funding_data.requests.get",
            return_value=MagicMock(json=MagicMock(return_value=first_page), raise_for_status=MagicMock()),
        ):
            load_funding_history("BNB", cache_dir=self.cache_dir, use_cache=True)

        second_page = _make_page(0, 6)
        with patch(
            "nero_core.data_sources.funding_data.requests.get",
            return_value=MagicMock(json=MagicMock(return_value=second_page), raise_for_status=MagicMock()),
        ):
            result = load_funding_history("BNB", cache_dir=self.cache_dir, use_cache=False)

        self.assertEqual(len(result.settlements), 6)
        self.assertFalse(result.from_cache)


class StartTimeAlwaysSentRegressionTest(FundingDataTestCase):
    """Regression guard: verified empirically against the real endpoint that omitting
    `startTime` (or sending 0) makes fapi/v1/fundingRate return only its most-recent
    ~500-record window instead of full history — silently truncating every asset's
    history to ~166 days regardless of how many pages this module thinks it fetched.
    A real, early `startTime` (e.g. 2019-01-01) correctly returns from that symbol's
    actual earliest record forward. This test guards that `startTime` is ALWAYS present
    in the request, never omitted, on every page including the first."""

    def test_every_page_request_includes_a_nonzero_start_time(self) -> None:
        captured_params: list[dict[str, object]] = []

        def _capture(url, params=None, timeout=None):
            captured_params.append(dict(params))
            mock = MagicMock()
            mock.raise_for_status = MagicMock()
            mock.json = MagicMock(return_value=_make_page(0, 2))
            return mock

        with patch("nero_core.data_sources.funding_data.requests.get", side_effect=_capture):
            load_funding_history("BTC", cache_dir=self.cache_dir, use_cache=False)

        self.assertGreaterEqual(len(captured_params), 1)
        for params in captured_params:
            self.assertIn("startTime", params)
            self.assertGreater(params["startTime"], 0)


class CacheRoundTripMixedPrecisionRegressionTest(FundingDataTestCase):
    """Regression guard: real Binance fundingTime values carry millisecond-precision
    sub-second components that don't always land on an exact second (e.g.
    "...16:00:00.003000+00:00" vs "...08:00:00+00:00" once trailing zero microseconds
    get trimmed on CSV write) — a single fixed-format datetime parse on cache read
    rejects the mix outright. Caught by running the real sweep tool against a freshly
    written real cache before committing."""

    def test_cache_with_mixed_fractional_second_precision_reads_back_cleanly(self) -> None:
        cache_path = self.cache_dir / "BTC_funding.csv"
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(
            "settlement_time,settlement_date,funding_rate\n"
            "1704067200000,2024-01-01 00:00:00+00:00,0.0001\n"
            "1704096000003,2024-01-01 08:00:00.003000+00:00,0.0002\n"
            "1704124800000,2024-01-01 16:00:00+00:00,-0.0001\n",
            encoding="utf-8",
        )

        def _explode(*_args, **_kwargs):
            raise AssertionError("must not hit the network when a cache exists")

        with patch("nero_core.data_sources.funding_data.requests.get", side_effect=_explode):
            result = load_funding_history("BTC", cache_dir=self.cache_dir, use_cache=True)

        self.assertEqual(len(result.settlements), 3)
        self.assertTrue(result.from_cache)


class UnsupportedAssetTest(unittest.TestCase):
    def test_unsupported_asset_raises(self) -> None:
        with self.assertRaises(FundingDataUnavailableError):
            load_funding_history("DOGE")

    def test_all_four_required_assets_are_supported(self) -> None:
        self.assertEqual(set(FUNDING_ASSETS), {"BTC", "ETH", "SOL", "BNB"})


class HistoryDepthReportTest(unittest.TestCase):
    def test_reports_span_and_count(self) -> None:
        settlements = pd.DataFrame(
            {
                "settlement_time": [0, EIGHT_HOURS_MS],
                "settlement_date": pd.to_datetime([0, EIGHT_HOURS_MS], unit="ms", utc=True),
                "funding_rate": [0.0001, -0.0002],
            }
        )
        text = history_depth_report("BTC", settlements)
        self.assertIn("BTC", text)
        self.assertIn("2 settlements", text)

    def test_handles_empty_settlements(self) -> None:
        empty = pd.DataFrame(columns=["settlement_time", "settlement_date", "funding_rate"])
        text = history_depth_report("BTC", empty)
        self.assertIn("0 settlements", text)


if __name__ == "__main__":
    unittest.main()
