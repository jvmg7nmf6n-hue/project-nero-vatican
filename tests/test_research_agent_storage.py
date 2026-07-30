from __future__ import annotations

import io
import shutil
import tempfile
import unittest
from contextlib import redirect_stderr
from pathlib import Path

from nero_core.research_agent.storage import append_json_list, read_json_list


class ReadJsonListTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp())
        self.path = self.tmp / "data.json"

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_missing_file_returns_empty_list_silently(self) -> None:
        # A missing file is a genuinely benign state (nothing has ever been
        # written yet) -- must NOT print anything.
        err = io.StringIO()
        with redirect_stderr(err):
            result = read_json_list(self.path)
        self.assertEqual(result, [])
        self.assertEqual(err.getvalue(), "")

    def test_valid_file_round_trips_silently(self) -> None:
        self.path.write_text('[{"a": 1}]')
        err = io.StringIO()
        with redirect_stderr(err):
            result = read_json_list(self.path)
        self.assertEqual(result, [{"a": 1}])
        self.assertEqual(err.getvalue(), "")

    def test_corrupted_file_prints_a_loud_error_and_degrades_to_empty(self) -> None:
        # Item #9 from the diagnostics audit: previously this silently
        # returned [] with zero indication anything was wrong -- a corrupted
        # agent_hypotheses.json looked identical to "no history yet,"
        # defeating duplicate detection with no trace.
        self.path.write_text("{not valid json")
        err = io.StringIO()
        with redirect_stderr(err):
            result = read_json_list(self.path)

        self.assertEqual(result, [])
        self.assertIn("ERROR", err.getvalue())
        self.assertIn(str(self.path), err.getvalue())
        self.assertIn("corrupted", err.getvalue())

    def test_non_list_json_returns_empty_list_silently(self) -> None:
        # Valid JSON, wrong shape (e.g. a dict instead of a list) -- not a
        # parse failure, so no ERROR line; this is a pre-existing, unrelated
        # contract (data if isinstance(data, list) else []).
        self.path.write_text('{"not": "a list"}')
        err = io.StringIO()
        with redirect_stderr(err):
            result = read_json_list(self.path)
        self.assertEqual(result, [])
        self.assertEqual(err.getvalue(), "")


class AppendJsonListTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp())
        self.path = self.tmp / "data.json"

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_empty_new_items_never_creates_the_file(self) -> None:
        append_json_list(self.path, [])
        self.assertFalse(self.path.exists())

    def test_appends_to_existing_content(self) -> None:
        append_json_list(self.path, [{"a": 1}])
        append_json_list(self.path, [{"a": 2}])
        self.assertEqual(read_json_list(self.path), [{"a": 1}, {"a": 2}])

    def test_appending_to_a_corrupted_file_prints_the_same_loud_error(self) -> None:
        self.path.write_text("{not valid json")
        err = io.StringIO()
        with redirect_stderr(err):
            append_json_list(self.path, [{"a": 1}])

        self.assertIn("ERROR", err.getvalue())
        self.assertIn("corrupted", err.getvalue())
        # The corrupted content is gone -- append_json_list reads (getting [])
        # then overwrites with just the new item. This is documented, existing
        # behavior; the point of this test is that it no longer happens
        # silently.
        self.assertEqual(read_json_list(self.path), [{"a": 1}])


if __name__ == "__main__":
    unittest.main()
