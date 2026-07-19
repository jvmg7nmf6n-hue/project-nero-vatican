from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from tools.liquidation_predictor_data_audit import (
    check_binance_force_orders,
    check_coinalyze,
    check_existing_funding_pipeline,
    check_glassnode_whale_transfer,
    check_okx_liquidation_orders,
    check_whale_alert,
    format_report,
    run_audit,
)


def _response(status_code: int, text: str = "") -> MagicMock:
    m = MagicMock()
    m.status_code = status_code
    m.text = text
    return m


class IndividualCheckTest(unittest.TestCase):
    def test_binance_force_orders_verified_when_200(self) -> None:
        with patch("tools.liquidation_predictor_data_audit.requests.get", return_value=_response(200, "[]")):
            result = check_binance_force_orders()
        self.assertTrue(result.verified_free_and_usable)

    def test_binance_force_orders_not_verified_when_discontinued(self) -> None:
        with patch(
            "tools.liquidation_predictor_data_audit.requests.get",
            return_value=_response(400, '{"code":400,"msg":"The endpoint has been out of maintenance"}'),
        ):
            result = check_binance_force_orders()
        self.assertFalse(result.verified_free_and_usable)

    def test_okx_not_verified_on_connection_error(self) -> None:
        import requests

        with patch("tools.liquidation_predictor_data_audit.requests.get", side_effect=requests.exceptions.ConnectionError("dns fail")):
            result = check_okx_liquidation_orders()
        self.assertFalse(result.verified_free_and_usable)

    def test_coinalyze_not_verified_even_though_endpoint_exists(self) -> None:
        with patch(
            "tools.liquidation_predictor_data_audit.requests.get",
            return_value=_response(401, '{"message":"Invalid/Missing API key"}'),
        ):
            result = check_coinalyze()
        self.assertFalse(result.verified_free_and_usable)
        self.assertIn("401", result.detail)

    def test_existing_funding_pipeline_verified_when_200(self) -> None:
        with patch("tools.liquidation_predictor_data_audit.requests.get", return_value=_response(200, "[]")):
            result = check_existing_funding_pipeline()
        self.assertTrue(result.verified_free_and_usable)

    def test_glassnode_not_verified_when_auth_required(self) -> None:
        with patch("tools.liquidation_predictor_data_audit.requests.get", return_value=_response(401, "401 Authorization Required")):
            result = check_glassnode_whale_transfer()
        self.assertFalse(result.verified_free_and_usable)

    def test_whale_alert_not_verified_without_api_key(self) -> None:
        with patch(
            "tools.liquidation_predictor_data_audit.requests.get",
            return_value=_response(401, '{"result":"error","message":"required parameter: api_key"}'),
        ):
            result = check_whale_alert()
        self.assertFalse(result.verified_free_and_usable)


class RunAuditConclusionTest(unittest.TestCase):
    def test_reports_blocked_on_data_when_nothing_verifies(self) -> None:
        with patch("tools.liquidation_predictor_data_audit.requests.get", return_value=_response(404, "not found")):
            results = run_audit()
        report = format_report(results)
        self.assertIn("BLOCKED-ON-DATA", report)

    def test_reports_proceed_when_a_source_verifies(self) -> None:
        def _fake_get(url, params=None, timeout=None):
            if "allForceOrders" in url:
                return _response(200, "[]")
            return _response(404, "not found")

        with patch("tools.liquidation_predictor_data_audit.requests.get", side_effect=_fake_get):
            results = run_audit()
        report = format_report(results)
        self.assertIn("proceed to STEP 2", report)

    def test_bybit_reachability_sanity_check_never_counts_as_a_verified_liquidation_source(self) -> None:
        # Regression test for the exact bug this audit's own first live run caught:
        # the sanity check (a 200 on /v5/market/recent-trade, an ordinary trades
        # endpoint) must never flip the conclusion to "verified" on its own — only
        # every OTHER liquidation-specific endpoint 404ing/failing.
        def _fake_get(url, params=None, timeout=None):
            if "recent-trade" in url:
                return _response(200, '{"retCode":0}')
            return _response(404, "not found")

        with patch("tools.liquidation_predictor_data_audit.requests.get", side_effect=_fake_get):
            results = run_audit()
        report = format_report(results)
        self.assertIn("BLOCKED-ON-DATA", report)


if __name__ == "__main__":
    unittest.main()
