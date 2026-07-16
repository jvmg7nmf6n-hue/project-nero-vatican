from __future__ import annotations

import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from nero_core.config import load_dotenv


class LoadDotenvTest(unittest.TestCase):
    def test_loads_key_value_pairs_from_file(self) -> None:
        with TemporaryDirectory() as tmp:
            env_path = Path(tmp) / ".env"
            env_path.write_text("FOO_TEST_KEY=some-value\n# a comment\n\nBAR_TEST_KEY=other\n")

            with patch.dict(os.environ, {}, clear=False):
                os.environ.pop("FOO_TEST_KEY", None)
                os.environ.pop("BAR_TEST_KEY", None)
                load_dotenv(env_path)
                self.assertEqual(os.environ.get("FOO_TEST_KEY"), "some-value")
                self.assertEqual(os.environ.get("BAR_TEST_KEY"), "other")

    def test_does_not_override_an_already_set_real_environment_variable(self) -> None:
        with TemporaryDirectory() as tmp:
            env_path = Path(tmp) / ".env"
            env_path.write_text("FOO_TEST_KEY=from-dotenv\n")

            with patch.dict(os.environ, {"FOO_TEST_KEY": "from-real-env"}):
                load_dotenv(env_path)
                self.assertEqual(os.environ["FOO_TEST_KEY"], "from-real-env")

    def test_missing_file_is_a_silent_noop(self) -> None:
        missing = Path("this/path/does/not/exist/.env")
        load_dotenv(missing)  # must not raise


if __name__ == "__main__":
    unittest.main()
