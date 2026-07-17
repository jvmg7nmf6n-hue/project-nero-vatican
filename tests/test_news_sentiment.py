from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import requests

from nero_core.data_sources.news_feed import NewsItem
from nero_core.strategies.news_sentiment import (
    STRATEGY_ID,
    STRATEGY_VERSION,
    NewsSentimentParameters,
    analyze_sentiment,
    parse_published,
    register_default_variant,
    select_eligible_headlines,
)
from nero_core.strategies.registry import StrategyAlreadyRegisteredError, StrategyRegistry

NOW = datetime(2026, 7, 17, 12, 0, tzinfo=timezone.utc)


def _item(title: str, published: str) -> NewsItem:
    return NewsItem(title=title, source="Test", link="", published=published, tags=[])


def _rfc822(dt: datetime) -> str:
    return dt.strftime("%a, %d %b %Y %H:%M:%S %z")


class ParsePublishedTest(unittest.TestCase):
    def test_parses_valid_rfc822_date(self) -> None:
        parsed = parse_published("Fri, 17 Jul 2026 09:00:00 GMT")
        self.assertEqual(parsed, datetime(2026, 7, 17, 9, 0, tzinfo=timezone.utc))

    def test_empty_string_returns_none(self) -> None:
        self.assertIsNone(parse_published(""))

    def test_malformed_string_returns_none_not_a_guess(self) -> None:
        self.assertIsNone(parse_published("not a real date"))


class SelectEligibleHeadlinesTest(unittest.TestCase):
    def test_headline_older_than_buffer_is_included(self) -> None:
        old_enough = _rfc822(NOW - timedelta(hours=3))
        headlines = [_item("old news", old_enough)]

        eligible = select_eligible_headlines(headlines, NOW, min_publication_age_hours=2.0)

        self.assertEqual(len(eligible), 1)

    def test_headline_newer_than_buffer_is_excluded(self) -> None:
        too_recent = _rfc822(NOW - timedelta(hours=1))
        headlines = [_item("breaking news", too_recent)]

        eligible = select_eligible_headlines(headlines, NOW, min_publication_age_hours=2.0)

        self.assertEqual(eligible, [])

    def test_headline_exactly_at_the_buffer_boundary_is_included(self) -> None:
        exactly_at_cutoff = _rfc822(NOW - timedelta(hours=2))
        headlines = [_item("boundary news", exactly_at_cutoff)]

        eligible = select_eligible_headlines(headlines, NOW, min_publication_age_hours=2.0)

        self.assertEqual(len(eligible), 1)

    def test_unparseable_published_timestamp_is_excluded(self) -> None:
        headlines = [_item("mystery timing", "garbage")]

        eligible = select_eligible_headlines(headlines, NOW, min_publication_age_hours=2.0)

        self.assertEqual(eligible, [])

    def test_naive_now_raises(self) -> None:
        with self.assertRaises(ValueError):
            select_eligible_headlines([], datetime(2026, 7, 17, 12, 0))


class AnalyzeSentimentTest(unittest.TestCase):
    def test_no_eligible_headlines_returns_neutral_with_explanatory_reasoning(self) -> None:
        too_recent = [_item("just published", _rfc822(NOW - timedelta(minutes=30)))]

        result = analyze_sentiment(too_recent, "GOLD", NOW, gemini_api_key="")

        self.assertEqual(result.signal_type, "NEUTRAL")
        self.assertEqual(result.source, "no eligible headlines")
        self.assertIn("lookahead", result.summary.lower())

    def test_local_fallback_used_when_no_api_key(self) -> None:
        headlines = [_item("gold price surge rally record high", _rfc822(NOW - timedelta(hours=5)))]

        result = analyze_sentiment(headlines, "GOLD", NOW, gemini_api_key="")

        self.assertEqual(result.source, "local")
        self.assertEqual(result.signal_type, "BUY_BIAS")
        self.assertGreater(result.confidence, 0)

    def test_negative_keywords_produce_sell_bias_locally(self) -> None:
        headlines = [_item("crash selloff collapse crash weak bearish", _rfc822(NOW - timedelta(hours=5)))]

        result = analyze_sentiment(headlines, "BTC", NOW, gemini_api_key="")

        self.assertEqual(result.signal_type, "SELL_BIAS")

    def test_gemini_error_falls_back_to_local(self) -> None:
        headlines = [_item("gold price surge rally", _rfc822(NOW - timedelta(hours=5)))]

        with patch("nero_core.strategies.news_sentiment.requests.post", side_effect=requests.exceptions.ConnectionError("boom")):
            result = analyze_sentiment(headlines, "GOLD", NOW, gemini_api_key="fake-key")

        self.assertEqual(result.source, "local fallback after Gemini error")

    def test_confidence_scales_with_score_magnitude(self) -> None:
        strong = [_item("surge jump rise gain record high breakout rally strong bullish", _rfc822(NOW - timedelta(hours=5)))]
        weak = [_item("gold price update", _rfc822(NOW - timedelta(hours=5)))]

        strong_result = analyze_sentiment(strong, "GOLD", NOW, gemini_api_key="")
        weak_result = analyze_sentiment(weak, "GOLD", NOW, gemini_api_key="")

        self.assertGreaterEqual(strong_result.confidence, weak_result.confidence)

    def test_custom_thresholds_are_respected(self) -> None:
        params = NewsSentimentParameters(bullish_score_threshold=100, bearish_score_threshold=-100)
        headlines = [_item("gold price surge rally record high", _rfc822(NOW - timedelta(hours=5)))]

        result = analyze_sentiment(headlines, "GOLD", NOW, gemini_api_key="", params=params)

        self.assertEqual(result.signal_type, "NEUTRAL")


class RegistrationTest(unittest.TestCase):
    def test_register_default_variant_uses_correct_id_and_version(self) -> None:
        registry = StrategyRegistry()

        variant = register_default_variant(registry)

        self.assertEqual(variant.strategy_id, STRATEGY_ID)
        self.assertEqual(variant.version, STRATEGY_VERSION)
        self.assertEqual(variant.version, "news-sentiment-v1.0.0")

    def test_registering_twice_is_rejected(self) -> None:
        registry = StrategyRegistry()
        register_default_variant(registry)

        with self.assertRaises(StrategyAlreadyRegisteredError):
            register_default_variant(registry)


if __name__ == "__main__":
    unittest.main()
