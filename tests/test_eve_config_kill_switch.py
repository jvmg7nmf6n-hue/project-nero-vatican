from __future__ import annotations

import unittest

from nero_core.eve.config import is_enabled


class IsEnabledTest(unittest.TestCase):
    def test_defaults_to_false_when_unset(self) -> None:
        self.assertFalse(is_enabled(env={}))

    def test_false_for_various_falsy_strings(self) -> None:
        for value in ("", "0", "false", "no", "off", "disabled", "garbage"):
            self.assertFalse(is_enabled(env={"EVE_ENABLED": value}), f"expected False for {value!r}")

    def test_true_for_various_truthy_strings_case_insensitive(self) -> None:
        for value in ("1", "true", "True", "TRUE", "yes", "YES", "on", "On"):
            self.assertTrue(is_enabled(env={"EVE_ENABLED": value}), f"expected True for {value!r}")


if __name__ == "__main__":
    unittest.main()
