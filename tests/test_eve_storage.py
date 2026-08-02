from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from nero_core.eve import storage


class _TempPathsTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        tmp_root = Path(self._tmpdir.name)
        self.hypotheses_path = tmp_root / "eve_hypotheses.json"
        self.ledger_path = tmp_root / "eve_budget_ledger.json"
        self.sessions_dir = tmp_root / "eve_sessions"
        self._patches = [
            patch.object(storage, "DEFAULT_HYPOTHESES_PATH", self.hypotheses_path),
            patch.object(storage, "DEFAULT_BUDGET_LEDGER_PATH", self.ledger_path),
            patch.object(storage, "EVE_SESSIONS_DIR", self.sessions_dir),
        ]
        for p in self._patches:
            p.start()

    def tearDown(self) -> None:
        for p in self._patches:
            p.stop()
        self._tmpdir.cleanup()


class AllowlistTest(_TempPathsTestCase):
    def test_write_to_hypotheses_path_allowed(self) -> None:
        storage.atomic_write_json_list(self.hypotheses_path, [{"a": 1}])
        self.assertEqual(json.loads(self.hypotheses_path.read_text()), [{"a": 1}])

    def test_write_to_ledger_path_allowed(self) -> None:
        storage.atomic_write_json_list(self.ledger_path, [{"b": 2}])
        self.assertEqual(json.loads(self.ledger_path.read_text()), [{"b": 2}])

    def test_write_to_session_record_path_allowed(self) -> None:
        path = storage.session_record_path("sess-1")
        storage.atomic_write_json_dict(path, {"session_id": "sess-1"})
        self.assertTrue(path.exists())
        self.assertEqual(path.parent.resolve(), self.sessions_dir.resolve())

    def test_write_outside_allowlist_rejected(self) -> None:
        rogue_path = Path(self._tmpdir.name) / "some_other_file.json"
        with self.assertRaises(storage.DisallowedWritePathError):
            storage.atomic_write_json_list(rogue_path, [{"x": 1}])

    def test_write_to_research_agent_style_path_rejected(self) -> None:
        rogue_path = Path(self._tmpdir.name) / "agent_hypotheses.json"
        with self.assertRaises(storage.DisallowedWritePathError):
            storage.atomic_write_json_list(rogue_path, [{"x": 1}])

    def test_write_to_nested_subdirectory_of_sessions_dir_rejected(self) -> None:
        rogue_path = self.sessions_dir / "nested" / "sess-1.json"
        with self.assertRaises(storage.DisallowedWritePathError):
            storage.atomic_write_json_dict(rogue_path, {"a": 1})


class AtomicWriteTest(_TempPathsTestCase):
    def test_no_leftover_tmp_files_after_write(self) -> None:
        storage.atomic_write_json_list(self.hypotheses_path, [{"a": 1}])
        leftovers = list(self.hypotheses_path.parent.glob("*.tmp"))
        self.assertEqual(leftovers, [])

    def test_write_creates_parent_directory(self) -> None:
        self.assertFalse(self.sessions_dir.exists())
        storage.atomic_write_json_dict(storage.session_record_path("sess-2"), {"session_id": "sess-2"})
        self.assertTrue(self.sessions_dir.exists())


class ReadJsonListTest(_TempPathsTestCase):
    def test_missing_file_returns_empty_list(self) -> None:
        self.assertEqual(storage.read_json_list(self.hypotheses_path), [])

    def test_corrupted_file_returns_empty_list(self) -> None:
        self.hypotheses_path.parent.mkdir(parents=True, exist_ok=True)
        self.hypotheses_path.write_text("{not valid json")
        self.assertEqual(storage.read_json_list(self.hypotheses_path), [])

    def test_non_list_json_returns_empty_list(self) -> None:
        self.hypotheses_path.parent.mkdir(parents=True, exist_ok=True)
        self.hypotheses_path.write_text(json.dumps({"not": "a list"}))
        self.assertEqual(storage.read_json_list(self.hypotheses_path), [])


class AppendJsonListTest(_TempPathsTestCase):
    def test_append_to_missing_file_creates_it(self) -> None:
        storage.append_json_list(self.hypotheses_path, [{"a": 1}])
        self.assertEqual(storage.read_json_list(self.hypotheses_path), [{"a": 1}])

    def test_append_preserves_existing_entries(self) -> None:
        storage.append_json_list(self.hypotheses_path, [{"a": 1}])
        storage.append_json_list(self.hypotheses_path, [{"b": 2}])
        self.assertEqual(storage.read_json_list(self.hypotheses_path), [{"a": 1}, {"b": 2}])

    def test_empty_new_items_is_a_no_op(self) -> None:
        storage.append_json_list(self.hypotheses_path, [{"a": 1}])
        mtime_before = self.hypotheses_path.stat().st_mtime_ns
        storage.append_json_list(self.hypotheses_path, [])
        mtime_after = self.hypotheses_path.stat().st_mtime_ns
        self.assertEqual(mtime_before, mtime_after)


class SessionRecordDictTest(_TempPathsTestCase):
    def test_read_json_dict_roundtrip(self) -> None:
        path = storage.session_record_path("sess-3")
        storage.atomic_write_json_dict(path, {"session_id": "sess-3", "turns": []})
        self.assertEqual(storage.read_json_dict(path), {"session_id": "sess-3", "turns": []})

    def test_read_json_dict_missing_file_returns_none(self) -> None:
        self.assertIsNone(storage.read_json_dict(storage.session_record_path("missing")))


if __name__ == "__main__":
    unittest.main()
