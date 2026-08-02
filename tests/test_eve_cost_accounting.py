from __future__ import annotations

import unittest
from datetime import datetime, timezone

from nero_core.eve.cost import (
    CostParameters,
    call_cost_usd,
    call_cost_usd_with_tools,
    pricing_staleness_warning,
    usage_token_breakdown,
    web_search_count,
)


class UsageTokenBreakdownTest(unittest.TestCase):
    def test_missing_fields_default_to_zero(self) -> None:
        self.assertEqual(
            usage_token_breakdown({}),
            {"input_tokens": 0, "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0, "output_tokens": 0},
        )

    def test_reads_all_four_fields(self) -> None:
        usage = {"input_tokens": 100, "cache_creation_input_tokens": 50, "cache_read_input_tokens": 25, "output_tokens": 10}
        self.assertEqual(usage_token_breakdown(usage), usage)


class CallCostUsdTest(unittest.TestCase):
    def test_input_and_output_only_matches_simple_formula(self) -> None:
        usage = {"input_tokens": 1_000_000, "output_tokens": 1_000_000}
        params = CostParameters()
        expected = params.input_cost_per_mtok + params.output_cost_per_mtok
        self.assertAlmostEqual(call_cost_usd(usage, params), expected, places=6)

    def test_cache_creation_billed_at_1_25x_input_rate(self) -> None:
        usage = {"cache_creation_input_tokens": 1_000_000}
        params = CostParameters()
        expected = params.input_cost_per_mtok * 1.25
        self.assertAlmostEqual(call_cost_usd(usage, params), expected, places=6)

    def test_cache_read_billed_at_0_1x_input_rate(self) -> None:
        usage = {"cache_read_input_tokens": 1_000_000}
        params = CostParameters()
        expected = params.input_cost_per_mtok * 0.1
        self.assertAlmostEqual(call_cost_usd(usage, params), expected, places=6)

    def test_all_four_fields_sum_correctly(self) -> None:
        usage = {
            "input_tokens": 1_000_000,
            "cache_creation_input_tokens": 1_000_000,
            "cache_read_input_tokens": 1_000_000,
            "output_tokens": 1_000_000,
        }
        params = CostParameters()
        expected = (
            params.input_cost_per_mtok
            + params.input_cost_per_mtok * params.cache_write_multiplier
            + params.input_cost_per_mtok * params.cache_read_multiplier
            + params.output_cost_per_mtok
        )
        self.assertAlmostEqual(call_cost_usd(usage, params), expected, places=6)

    def test_ignoring_cache_fields_would_understate_cost(self) -> None:
        # The whole point of this module's existence over hypothesis_gen's
        # own _call_cost_usd: a call with heavy cache usage costs strictly
        # more than input_tokens+output_tokens alone would suggest.
        usage_no_cache = {"input_tokens": 100, "output_tokens": 100}
        usage_with_cache = dict(usage_no_cache, cache_creation_input_tokens=500_000, cache_read_input_tokens=500_000)
        self.assertGreater(call_cost_usd(usage_with_cache), call_cost_usd(usage_no_cache))


class WebSearchCostTest(unittest.TestCase):
    def test_web_search_count_zero_when_absent(self) -> None:
        self.assertEqual(web_search_count({}), 0)

    def test_web_search_count_reads_server_tool_use(self) -> None:
        self.assertEqual(web_search_count({"server_tool_use": {"web_search_requests": 3}}), 3)

    def test_call_cost_usd_with_tools_adds_search_fee(self) -> None:
        usage = {"server_tool_use": {"web_search_requests": 2}}
        params = CostParameters()
        self.assertAlmostEqual(
            call_cost_usd_with_tools(usage, params), call_cost_usd(usage, params) + 2 * params.web_search_cost_per_search, places=6
        )


class PricingStalenessWarningTest(unittest.TestCase):
    def test_none_before_expiry(self) -> None:
        self.assertIsNone(pricing_staleness_warning(datetime(2026, 8, 1, tzinfo=timezone.utc)))

    def test_none_after_expiry_if_rate_already_updated(self) -> None:
        updated = CostParameters(input_cost_per_mtok=3.00, output_cost_per_mtok=15.00)
        self.assertIsNone(pricing_staleness_warning(datetime(2026, 9, 1, tzinfo=timezone.utc), updated))

    def test_warns_after_expiry_if_rate_unchanged(self) -> None:
        warning = pricing_staleness_warning(datetime(2026, 9, 1, tzinfo=timezone.utc))
        self.assertIsNotNone(warning)
        self.assertIn("INTRODUCTORY_RATE_EXPIRY", warning)


if __name__ == "__main__":
    unittest.main()
