from __future__ import annotations

import unittest

import pandas as pd

from nero_core.macro_policy.white_house_impact import (
    classify_white_house_text,
    format_white_house_impact_report,
    score_white_house_impact,
)


class WhiteHouseImpactTest(unittest.TestCase):
    def test_classifies_crypto_policy_text(self) -> None:
        tags = classify_white_house_text("President announces strategic bitcoin reserve and stablecoin framework.")

        self.assertIn("strategic_bitcoin_reserve", tags)
        self.assertIn("crypto_friendly_policy", tags)
        self.assertIn("policy_clarity", tags)

    def test_classifies_no_tags_for_unrelated_text(self) -> None:
        tags = classify_white_house_text("The president toured a local school and read a book to students.")

        self.assertEqual(tags, set())

    def test_crypto_friendly_policy_scores_btc_impact(self) -> None:
        events = pd.DataFrame(
            [
                {
                    "date": "2025-03-06",
                    "headline": "Strategic Bitcoin Reserve established",
                    "tags": "crypto_friendly_policy|strategic_bitcoin_reserve|institutional_legitimacy|structural_adoption",
                    "btc_impact_score": 86,
                    "gold_impact_score": 15,
                    "confidence": 0.78,
                },
                {
                    "date": "2025-01-23",
                    "headline": "Digital financial technology order",
                    "tags": "crypto_friendly_policy|policy_clarity|anti_cbdc|regulatory_framework",
                    "btc_impact_score": 78,
                    "gold_impact_score": 12,
                    "confidence": 0.72,
                },
            ]
        )

        result = score_white_house_impact("White House announces strategic bitcoin reserve and digital asset framework", events)

        self.assertGreaterEqual(result.btc_average_impact, 70)
        self.assertLess(result.gold_average_impact, 35)
        self.assertIn("BTC-specific", " ".join(result.notes))
        self.assertIn("NERO White House Market Impact", format_white_house_impact_report(result))

    def test_geopolitical_sanctions_scores_gold_impact(self) -> None:
        events = pd.DataFrame(
            [
                {
                    "date": "2022-02-24",
                    "headline": "Russia sanctions after Ukraine invasion",
                    "tags": "sanctions|war|geopolitical_risk|risk_off|safe_haven|oil_supply_risk",
                    "btc_impact_score": 55,
                    "gold_impact_score": 70,
                    "confidence": 0.65,
                }
            ]
        )

        result = score_white_house_impact("President announces sanctions after geopolitical conflict and war risk", events)

        self.assertGreaterEqual(result.gold_average_impact, 65)
        self.assertIn("safe haven", " ".join(result.notes))
        self.assertIn("sanctions", result.query_tags)

    def test_no_matching_tags_returns_neutral_result(self) -> None:
        events = pd.DataFrame(
            [{"date": "2022-02-24", "headline": "Russia sanctions", "tags": "sanctions|war", "btc_impact_score": 55, "gold_impact_score": 70, "confidence": 0.65}]
        )

        result = score_white_house_impact("The weather today is sunny with a light breeze.", events)

        self.assertEqual(result.matched_events, 0)
        self.assertEqual(result.btc_direction, "neutral")
        self.assertEqual(result.confidence, 0.0)

    def test_empty_event_memory_returns_neutral_result(self) -> None:
        result = score_white_house_impact("strategic bitcoin reserve announcement", pd.DataFrame())

        self.assertEqual(result.matched_events, 0)
        self.assertIn("No matching tags or memory events available.", result.notes)

    def test_no_similar_event_in_memory_returns_zero_matches(self) -> None:
        # memory only has unrelated tags -> Jaccard similarity is 0 for every row.
        events = pd.DataFrame(
            [{"date": "2021-01-01", "headline": "Unrelated event", "tags": "tariff|inflation_risk", "btc_impact_score": 10, "gold_impact_score": 10, "confidence": 0.5}]
        )

        result = score_white_house_impact("strategic bitcoin reserve announcement", events)

        self.assertEqual(result.matched_events, 0)
        self.assertIn("No similar White House memory event found.", result.notes)


if __name__ == "__main__":
    unittest.main()
