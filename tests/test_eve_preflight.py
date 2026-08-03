from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

import requests

from nero_core.eve import preflight


class CheckApiKeyTest(unittest.TestCase):
    def test_empty_key_fails_fast_with_no_network_call(self) -> None:
        with patch.object(preflight.requests, "post") as mock_post:
            result = preflight.check_api_key("")

        mock_post.assert_not_called()
        self.assertFalse(result.ok)
        self.assertIn("empty/unset", result.reason)

    def test_a_2xx_response_is_ok(self) -> None:
        mock_response = MagicMock(status_code=200, ok=True)
        with patch.object(preflight.requests, "post", return_value=mock_response) as mock_post:
            result = preflight.check_api_key("sk-real-key")

        mock_post.assert_called_once()
        self.assertTrue(result.ok)
        self.assertEqual(result.reason, "ok")

    def test_a_minimal_request_body_is_sent_max_tokens_one_no_tools(self) -> None:
        mock_response = MagicMock(status_code=200, ok=True)
        with patch.object(preflight.requests, "post", return_value=mock_response) as mock_post:
            preflight.check_api_key("sk-real-key")

        _, kwargs = mock_post.call_args
        body = kwargs["json"]
        self.assertEqual(body["max_tokens"], 1)
        self.assertNotIn("tools", body)
        self.assertNotIn("system", body)

    def test_401_is_reported_as_a_stale_or_invalid_key(self) -> None:
        mock_response = MagicMock(status_code=401, ok=False)
        with patch.object(preflight.requests, "post", return_value=mock_response):
            result = preflight.check_api_key("stale-key")

        self.assertFalse(result.ok)
        self.assertIn("401", result.reason)
        self.assertIn("stale/invalid", result.reason)

    def test_403_and_429_are_also_treated_as_rejected_before_token_processing(self) -> None:
        for status in (403, 429):
            with self.subTest(status=status):
                mock_response = MagicMock(status_code=status, ok=False)
                with patch.object(preflight.requests, "post", return_value=mock_response):
                    result = preflight.check_api_key("some-key")
                self.assertFalse(result.ok)
                self.assertIn(str(status), result.reason)

    def test_a_5xx_response_fails_with_its_own_distinct_reason(self) -> None:
        mock_response = MagicMock(status_code=500, ok=False, text="internal server error")
        with patch.object(preflight.requests, "post", return_value=mock_response):
            result = preflight.check_api_key("some-key")

        self.assertFalse(result.ok)
        self.assertIn("500", result.reason)
        self.assertNotIn("stale/invalid", result.reason)

    def test_a_network_error_fails_loudly_never_treated_as_ok(self) -> None:
        with patch.object(preflight.requests, "post", side_effect=requests.exceptions.ConnectionError("down")):
            result = preflight.check_api_key("some-key")

        self.assertFalse(result.ok)
        self.assertIn("network error", result.reason)
        self.assertIn("ConnectionError", result.reason)

    def test_a_timeout_fails_loudly(self) -> None:
        with patch.object(preflight.requests, "post", side_effect=requests.exceptions.Timeout("timed out")):
            result = preflight.check_api_key("some-key")

        self.assertFalse(result.ok)
        self.assertIn("Timeout", result.reason)


if __name__ == "__main__":
    unittest.main()
