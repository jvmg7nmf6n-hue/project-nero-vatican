from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import tools.correct_range_mean_reversion_draft_20260806 as corrector


class CorrectRangeMeanReversionDraftTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp())
        self.path = self.tmp / "graveyard_distillation_drafts.json"

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _write(self, entry: dict) -> None:
        self.path.write_text(json.dumps([entry]), encoding="utf-8")

    def _pending_entry(self, **overrides) -> dict:
        entry = {
            "name": "RANGE_MEAN_REVERSION_GRAVEYARD",
            "family": "Range Mean Reversion",
            "failure_pattern": "sample-too-thin",
            "why_it_died": "original flawed text",
            "fixable": False,
            "source_doc": "eve-origin graveyard review",
            "covers": ["PAXG_PEG_REVERSION", "BTC_VOL_EXPANSION_BREAKOUT", "SOL_TREND_ALIGNED_PULLBACK", "PAXG_PREMIUM_FADE_DYNAMIC_EXIT"],
            "review_status": "pending_human_approval",
        }
        entry.update(overrides)
        return entry

    def test_corrects_the_why_it_died_text_and_fixable_flag(self) -> None:
        self._write(self._pending_entry())
        with patch.object(corrector, "DRAFTS_PATH", self.path):
            changed = corrector.correct()

        self.assertTrue(changed)
        drafts = json.loads(self.path.read_text(encoding="utf-8"))
        entry = drafts[0]
        self.assertEqual(entry["why_it_died"], corrector.CORRECTED_WHY_IT_DIED)
        self.assertIn("Three of the four", entry["why_it_died"])
        self.assertTrue(entry["fixable"])
        self.assertIn("correction_provenance", entry)
        self.assertEqual(entry["correction_provenance"]["original_fixable"], False)
        # Still pending -- this script never approves anything.
        self.assertEqual(entry["review_status"], "pending_human_approval")

    def test_idempotent_second_run_is_a_noop(self) -> None:
        self._write(self._pending_entry())
        with patch.object(corrector, "DRAFTS_PATH", self.path):
            first = corrector.correct()
            second = corrector.correct()

        self.assertTrue(first)
        self.assertFalse(second)

    def test_refuses_to_correct_an_already_decided_entry(self) -> None:
        self._write(self._pending_entry(review_status="approved"))
        with patch.object(corrector, "DRAFTS_PATH", self.path):
            with self.assertRaises(RuntimeError):
                corrector.correct()

    def test_missing_target_entry_is_a_noop_not_an_error(self) -> None:
        self._write(self._pending_entry(name="SOME_OTHER_ENTRY"))
        with patch.object(corrector, "DRAFTS_PATH", self.path):
            changed = corrector.correct()
        self.assertFalse(changed)

    def test_missing_file_is_a_noop_not_an_error(self) -> None:
        missing_path = self.tmp / "does_not_exist.json"
        with patch.object(corrector, "DRAFTS_PATH", missing_path):
            changed = corrector.correct()
        self.assertFalse(changed)


if __name__ == "__main__":
    unittest.main()
