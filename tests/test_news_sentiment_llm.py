from __future__ import annotations

import json
import unittest
from dataclasses import fields
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import requests

from nero_core.data_sources.news_feed import NewsItem
from nero_core.strategies.news_sentiment import STRATEGY_VERSION as V1_STRATEGY_VERSION
from nero_core.strategies.news_sentiment_llm import (
    STRATEGY_ID,
    STRATEGY_VERSION,
    HeadlineAnalysis,
    LLMNewsParameters,
    analyze_headline,
    analyze_sentiment_llm,
    calibration_status_for,
    register_llm_variant,
)
from nero_core.strategies.registry import StrategyAlreadyRegisteredError, StrategyRegistry

NOW = datetime(2026, 7, 17, 12, 0, tzinfo=timezone.utc)
PARAMS = LLMNewsParameters()


def _item(title: str, hours_old: float = 5.0) -> NewsItem:
    published = (NOW - timedelta(hours=hours_old)).strftime("%a, %d %b %Y %H:%M:%S %z")
    return NewsItem(title=title, source="Test", link="", published=published, tags=[])


def _mock_response(payload: dict) -> MagicMock:
    resp = MagicMock()
    resp.raise_for_status = MagicMock()
    resp.json.return_value = {"content": [{"text": json.dumps(payload)}]}
    return resp


def _claude_payload(
    impact_on_gold: str = "BULLISH",
    impact_on_btc: str = "BULLISH",
    confidence: float = 0.9,
    surprise_score: float = 0.8,
    reasoning: str = "Test reasoning.",
) -> dict:
    return {
        "impact_on_gold": impact_on_gold,
        "impact_on_btc": impact_on_btc,
        "confidence": confidence,
        "surprise_score": surprise_score,
        "reasoning": reasoning,
    }


class HonestyGateConfidenceTest(unittest.TestCase):
    """Gate (a): confidence < confidence_gate -> NO_SIGNAL, biases forced NEUTRAL."""

    def test_low_confidence_forces_no_signal_and_neutral_biases(self) -> None:
        payload = _claude_payload(impact_on_gold="BULLISH", impact_on_btc="BULLISH", confidence=0.3, surprise_score=0.9)
        with patch("nero_core.strategies.news_sentiment_llm.requests.post", return_value=_mock_response(payload)):
            result = analyze_headline(_item("Fed cuts rates"), NOW, api_key="fake-key", params=PARAMS)

        self.assertEqual(result.signal_type, "NO_SIGNAL")
        self.assertEqual(result.impact_on_gold, "NEUTRAL")
        self.assertEqual(result.impact_on_btc, "NEUTRAL")

    def test_confidence_exactly_at_gate_boundary_is_not_gated(self) -> None:
        payload = _claude_payload(confidence=PARAMS.confidence_gate, surprise_score=0.9)
        with patch("nero_core.strategies.news_sentiment_llm.requests.post", return_value=_mock_response(payload)):
            result = analyze_headline(_item("Gold rallies"), NOW, api_key="fake-key", params=PARAMS)

        self.assertEqual(result.signal_type, "SIGNAL")
        self.assertEqual(result.impact_on_gold, "BULLISH")


class HonestyGateSurpriseTest(unittest.TestCase):
    """Gate (b): surprise_score < surprise_gate -> biases forced NEUTRAL, independent of confidence."""

    def test_low_surprise_forces_neutral_biases_despite_high_confidence(self) -> None:
        payload = _claude_payload(impact_on_gold="BEARISH", impact_on_btc="BEARISH", confidence=0.95, surprise_score=0.02)
        with patch("nero_core.strategies.news_sentiment_llm.requests.post", return_value=_mock_response(payload)):
            result = analyze_headline(_item("Expected CPI print matches forecast"), NOW, api_key="fake-key", params=PARAMS)

        self.assertEqual(result.impact_on_gold, "NEUTRAL")
        self.assertEqual(result.impact_on_btc, "NEUTRAL")
        self.assertEqual(result.signal_type, "NO_SIGNAL")
        self.assertGreaterEqual(result.confidence, 0.6)  # confidence itself is untouched by the surprise gate


class CalibrationStatusTest(unittest.TestCase):
    """Gate (c): calibration_status is always present and honest about the 50-prediction threshold."""

    def test_calibration_status_always_present_on_every_analysis(self) -> None:
        payload = _claude_payload()
        with patch("nero_core.strategies.news_sentiment_llm.requests.post", return_value=_mock_response(payload)):
            result = analyze_headline(_item("Gold rallies"), NOW, api_key="fake-key", params=PARAMS)

        self.assertEqual(result.calibration_status, "uncalibrated")

    def test_calibration_status_helper_below_threshold(self) -> None:
        self.assertEqual(calibration_status_for(49, threshold=50), "uncalibrated")

    def test_calibration_status_helper_at_threshold(self) -> None:
        self.assertEqual(calibration_status_for(50, threshold=50), "calibrated")

    def test_no_probability_field_is_published_only_confidence_and_calibration_status(self) -> None:
        payload = _claude_payload()
        with patch("nero_core.strategies.news_sentiment_llm.requests.post", return_value=_mock_response(payload)):
            result = analyze_headline(_item("Gold rallies"), NOW, api_key="fake-key", params=PARAMS)

        field_names = {f.name for f in fields(HeadlineAnalysis)}
        self.assertNotIn("probability", field_names)
        self.assertIn("calibration_status", field_names)


class LookaheadBufferTest(unittest.TestCase):
    """Gate (d): lookahead buffer is reused (not reimplemented) and logged per row."""

    def test_publication_age_hours_is_logged_and_matches_headline_age(self) -> None:
        payload = _claude_payload()
        with patch("nero_core.strategies.news_sentiment_llm.requests.post", return_value=_mock_response(payload)):
            result = analyze_headline(_item("Gold rallies", hours_old=5.0), NOW, api_key="fake-key", params=PARAMS)

        self.assertAlmostEqual(result.publication_age_hours, 5.0, places=2)

    def test_aggregate_excludes_headlines_newer_than_buffer(self) -> None:
        too_recent = [_item("breaking gold news", hours_old=0.5)]
        payload = _claude_payload()
        with patch("nero_core.strategies.news_sentiment_llm.requests.post", return_value=_mock_response(payload)):
            result = analyze_sentiment_llm(too_recent, "GOLD", NOW, api_key="fake-key", params=PARAMS)

        self.assertEqual(result.signal_type, "NEUTRAL")
        self.assertEqual(result.source, "no eligible headlines")
        self.assertEqual(result.headline_analyses, ())

    def test_aggregate_includes_headlines_older_than_buffer(self) -> None:
        old_enough = [_item("gold news", hours_old=5.0)]
        payload = _claude_payload()
        with patch("nero_core.strategies.news_sentiment_llm.requests.post", return_value=_mock_response(payload)):
            result = analyze_sentiment_llm(old_enough, "GOLD", NOW, api_key="fake-key", params=PARAMS)

        self.assertEqual(len(result.headline_analyses), 1)


class NoHistoricalMatchesTest(unittest.TestCase):
    """Gate (e): historical_matches must never appear anywhere in this module's output."""

    def test_headline_analysis_has_no_historical_matches_field(self) -> None:
        field_names = {f.name for f in fields(HeadlineAnalysis)}
        self.assertNotIn("historical_matches", field_names)

    def test_analyze_headline_output_has_no_historical_matches_field(self) -> None:
        payload = _claude_payload()
        with patch("nero_core.strategies.news_sentiment_llm.requests.post", return_value=_mock_response(payload)):
            result = analyze_headline(_item("Gold rallies"), NOW, api_key="fake-key", params=PARAMS)

        self.assertFalse(hasattr(result, "historical_matches"))


class ApiErrorHandlingTest(unittest.TestCase):
    def test_network_error_produces_honest_no_signal_not_a_guess(self) -> None:
        with patch(
            "nero_core.strategies.news_sentiment_llm.requests.post",
            side_effect=requests.exceptions.ConnectionError("boom"),
        ):
            result = analyze_headline(_item("Gold rallies"), NOW, api_key="fake-key", params=PARAMS)

        self.assertEqual(result.signal_type, "NO_SIGNAL")
        self.assertEqual(result.impact_on_gold, "NEUTRAL")
        self.assertEqual(result.impact_on_btc, "NEUTRAL")
        self.assertTrue(result.source.startswith("error:"))
        self.assertEqual(result.calibration_status, "uncalibrated")

    def test_malformed_json_produces_honest_no_signal(self) -> None:
        resp = MagicMock()
        resp.raise_for_status = MagicMock()
        resp.json.return_value = {"content": [{"text": "not json at all"}]}
        with patch("nero_core.strategies.news_sentiment_llm.requests.post", return_value=resp):
            result = analyze_headline(_item("Gold rallies"), NOW, api_key="fake-key", params=PARAMS)

        self.assertEqual(result.signal_type, "NO_SIGNAL")
        self.assertTrue(result.source.startswith("error:"))


class NoApiKeyTest(unittest.TestCase):
    def test_no_api_key_returns_neutral_without_calling_claude_or_falling_back_to_keywords(self) -> None:
        headlines = [_item("gold price surge rally record high", hours_old=5.0)]
        with patch("nero_core.strategies.news_sentiment_llm.requests.post") as mock_post:
            result = analyze_sentiment_llm(headlines, "GOLD", NOW, api_key="", params=PARAMS)

        mock_post.assert_not_called()
        self.assertEqual(result.signal_type, "NEUTRAL")
        self.assertEqual(result.source, "no api key")


class AggregationTest(unittest.TestCase):
    def test_majority_bullish_produces_buy_bias(self) -> None:
        headlines = [_item("gold headline one"), _item("gold headline two"), _item("gold headline three")]
        responses = [
            _mock_response(_claude_payload(impact_on_gold="BULLISH", confidence=0.9, surprise_score=0.8)),
            _mock_response(_claude_payload(impact_on_gold="BULLISH", confidence=0.9, surprise_score=0.8)),
            _mock_response(_claude_payload(impact_on_gold="BEARISH", confidence=0.9, surprise_score=0.8)),
        ]
        with patch("nero_core.strategies.news_sentiment_llm.requests.post", side_effect=responses):
            result = analyze_sentiment_llm(headlines, "GOLD", NOW, api_key="fake-key", params=PARAMS)

        self.assertEqual(result.signal_type, "BUY_BIAS")

    def test_tie_produces_neutral(self) -> None:
        headlines = [_item("gold headline one"), _item("gold headline two")]
        responses = [
            _mock_response(_claude_payload(impact_on_gold="BULLISH", confidence=0.9, surprise_score=0.8)),
            _mock_response(_claude_payload(impact_on_gold="BEARISH", confidence=0.9, surprise_score=0.8)),
        ]
        with patch("nero_core.strategies.news_sentiment_llm.requests.post", side_effect=responses):
            result = analyze_sentiment_llm(headlines, "GOLD", NOW, api_key="fake-key", params=PARAMS)

        self.assertEqual(result.signal_type, "NEUTRAL")

    def test_gated_headlines_do_not_contribute_to_aggregate_direction(self) -> None:
        headlines = [_item("gold headline one"), _item("gold headline two")]
        responses = [
            _mock_response(_claude_payload(impact_on_gold="BULLISH", confidence=0.3, surprise_score=0.8)),  # gated out
            _mock_response(_claude_payload(impact_on_gold="BEARISH", confidence=0.9, surprise_score=0.8)),
        ]
        with patch("nero_core.strategies.news_sentiment_llm.requests.post", side_effect=responses):
            result = analyze_sentiment_llm(headlines, "GOLD", NOW, api_key="fake-key", params=PARAMS)

        self.assertEqual(result.signal_type, "SELL_BIAS")
        self.assertEqual(len(result.headline_analyses), 2)


class RegistrationTest(unittest.TestCase):
    def test_register_llm_variant_uses_same_strategy_id_as_v1(self) -> None:
        from nero_core.strategies.news_sentiment import STRATEGY_ID as V1_STRATEGY_ID

        registry = StrategyRegistry()
        variant = register_llm_variant(registry)

        self.assertEqual(variant.strategy_id, V1_STRATEGY_ID)
        self.assertEqual(variant.strategy_id, STRATEGY_ID)

    def test_llm_variant_is_a_new_version_not_a_mutation_of_v1(self) -> None:
        self.assertNotEqual(STRATEGY_VERSION, V1_STRATEGY_VERSION)

    def test_registering_twice_is_rejected(self) -> None:
        registry = StrategyRegistry()
        register_llm_variant(registry)

        with self.assertRaises(StrategyAlreadyRegisteredError):
            register_llm_variant(registry)

    def test_both_versions_can_coexist_on_the_same_registry(self) -> None:
        from nero_core.strategies.news_sentiment import register_default_variant

        registry = StrategyRegistry()
        register_default_variant(registry)
        register_llm_variant(registry)

        versions = {v.version for v in registry.list_versions(STRATEGY_ID)}
        self.assertEqual(versions, {V1_STRATEGY_VERSION, STRATEGY_VERSION})


if __name__ == "__main__":
    unittest.main()
