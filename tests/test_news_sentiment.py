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


class ParsePublishedIso8601Test(unittest.TestCase):
    """Regression coverage for the 2026-07-28 live validation finding (see
    docs/site_data/news_llm_live_validation.md): Yahoo Finance's RSS feed returns
    ISO8601 pubDates (e.g. "2026-07-28T11:40:31Z"), which parsedate_to_datetime
    (RFC822-only) cannot parse -- every Yahoo headline was silently excluded from
    the lookahead-eligible set regardless of true age. Confirmed via live fetch
    (Step 0d of this task) that of the 5 configured sources, CNBC and CoinDesk both
    return RFC822 dates (unaffected); Yahoo Finance returns ISO8601 (affected);
    Reuters and MarketWatch Economy could not be fetched at all at check time (DNS
    failure / 403, both unrelated to timestamp format) so their format could not be
    confirmed -- 1 of 5 configured sources is confirmed affected, 2 of 5 confirmed
    unaffected, 2 of 5 unconfirmed due to unrelated connectivity issues."""

    def test_iso8601_with_z_suffix_parses_and_is_utc(self) -> None:
        parsed = parse_published("2026-07-28T11:40:31Z")
        self.assertEqual(parsed, datetime(2026, 7, 28, 11, 40, 31, tzinfo=timezone.utc))

    def test_iso8601_with_non_utc_offset_resolves_to_correct_utc_instant(self) -> None:
        # 14:40:31+02:00 is the same instant as 12:40:31Z.
        parsed = parse_published("2026-07-28T14:40:31+02:00")
        self.assertEqual(parsed, datetime(2026, 7, 28, 12, 40, 31, tzinfo=timezone.utc))

    def test_iso8601_with_fractional_seconds_parses(self) -> None:
        parsed = parse_published("2026-07-28T11:40:31.123456Z")
        self.assertEqual(parsed, datetime(2026, 7, 28, 11, 40, 31, 123456, tzinfo=timezone.utc))

    def test_naive_iso8601_timestamp_is_treated_as_unparseable_not_assumed_utc(self) -> None:
        # No offset and no "Z" at all. Assuming UTC (or local) here would risk a
        # lookahead leak if the guess is wrong -- excluding is the safe failure
        # mode, matching the existing "unparseable -> exclude" contract.
        parsed = parse_published("2026-07-28T11:40:31")
        self.assertIsNone(parsed)

    def test_unparseable_after_both_parsers_returns_none(self) -> None:
        self.assertIsNone(parse_published("definitely not a timestamp"))

    def test_unparseable_timestamp_is_logged_with_raw_value(self) -> None:
        with self.assertLogs("nero_core.strategies.news_sentiment", level="WARNING") as captured:
            parse_published("definitely not a timestamp")

        self.assertTrue(any("definitely not a timestamp" in line for line in captured.output))

    def test_naive_iso8601_timestamp_is_logged_with_raw_value(self) -> None:
        with self.assertLogs("nero_core.strategies.news_sentiment", level="WARNING") as captured:
            parse_published("2026-07-28T11:40:31")

        self.assertTrue(any("2026-07-28T11:40:31" in line for line in captured.output))


class SelectEligibleHeadlinesIso8601BoundaryTest(unittest.TestCase):
    """Bug 2 boundary coverage using ISO8601 timestamps specifically (the existing
    SelectEligibleHeadlinesTest class above already covers the RFC822 boundary)."""

    def test_iso8601_headline_just_inside_the_buffer_is_included(self) -> None:
        just_old_enough = (NOW - timedelta(hours=2, minutes=1)).isoformat().replace("+00:00", "Z")
        headlines = [_item("iso news", just_old_enough)]

        eligible = select_eligible_headlines(headlines, NOW, min_publication_age_hours=2.0)

        self.assertEqual(len(eligible), 1)

    def test_iso8601_headline_just_outside_the_buffer_is_excluded(self) -> None:
        just_too_recent = (NOW - timedelta(hours=1, minutes=59)).isoformat().replace("+00:00", "Z")
        headlines = [_item("iso news", just_too_recent)]

        eligible = select_eligible_headlines(headlines, NOW, min_publication_age_hours=2.0)

        self.assertEqual(eligible, [])


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

        self.assertEqual(result.source, "keyword (no gemini key configured)")
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

        self.assertEqual(result.source, "keyword (gemini call failed)")

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
