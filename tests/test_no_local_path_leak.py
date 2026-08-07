"""CC-1 directive (path-leak fix, 2026-08-07): regression guard for the
forward_trial.json path leak (nero_core.research_agent.trial.TrialRecord
used to embed an absolute local filesystem path -- see
tools/strip_forward_trial_path_leak_20260807.py for the one-time cleanup of
the already-committed file, and trial.py's own updated docstring for the
code-side fix).

Scans EVERY JSON file under docs/site_data/ (recursively -- eve_sessions/,
candles/, etc. included, not just the top level) for any string matching an
absolute local-filesystem-path shape: a Windows drive-letter path
(`C:\\Users\\...`, in either raw or JSON-escaped backslash form) or a Unix
home-directory path (`/home/<user>/...`, `/Users/<user>/...`). This is a
real, machine-identifying detail that must never be serialized into a
publicly-committed file -- matching the discipline this repo already
applies to secrets (never repr()/print() a real value).
"""
from __future__ import annotations

import json
import re
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SITE_DATA_DIR = REPO_ROOT / "docs" / "site_data"

# Windows: a drive letter followed by \Users\ or /Users/ (raw or JSON-escaped
# backslashes). Unix: /home/<user>/ or /Users/<user>/ (macOS).
_LOCAL_PATH_PATTERNS = [
    re.compile(r"[A-Za-z]:\\{1,2}Users\\{1,2}[^\\\"]+", re.IGNORECASE),
    re.compile(r"[A-Za-z]:/Users/[^/\"]+", re.IGNORECASE),
    re.compile(r"/home/[^/\"]+/"),
    re.compile(r"/Users/[^/\"]+/"),
]


def _find_leaked_paths(text: str) -> list[str]:
    matches: list[str] = []
    for pattern in _LOCAL_PATH_PATTERNS:
        matches.extend(m.group(0) for m in pattern.finditer(text))
    return matches


class NoLocalFilesystemPathLeakTest(unittest.TestCase):
    def test_no_json_file_under_site_data_contains_a_local_filesystem_path(self) -> None:
        if not SITE_DATA_DIR.exists():
            self.skipTest(f"{SITE_DATA_DIR} does not exist in this checkout")

        offenders: dict[str, list[str]] = {}
        for path in SITE_DATA_DIR.rglob("*.json"):
            text = path.read_text(encoding="utf-8", errors="replace")
            leaks = _find_leaked_paths(text)
            if leaks:
                offenders[str(path.relative_to(REPO_ROOT))] = leaks

        self.assertEqual(
            offenders, {},
            f"Local filesystem path(s) leaked into publicly-committed JSON: {offenders}",
        )

    def test_the_detector_itself_actually_catches_a_known_leak_shape(self) -> None:
        """Guards against this test silently doing nothing -- proves the
        regex actually matches the exact real leak this directive fixed
        (C:\\Users\\HP\\Documents\\Codex\\project-nero-vatican\\data\\
        repair_lab_forward_tracking.db, JSON-escaped) before trusting the
        empty result above."""
        sample = json.dumps({
            "forward_tracking_db_ref": "C:\\Users\\HP\\Documents\\Codex\\project-nero-vatican\\data\\repair_lab_forward_tracking.db",
        })
        self.assertTrue(_find_leaked_paths(sample), "detector failed to catch the known real leak shape")

    def test_the_detector_does_not_false_positive_on_ordinary_site_data_content(self) -> None:
        sample = json.dumps({
            "asset": "BTC", "strategy": "ORDERFLOW_IMBALANCE",
            "note": "Users of this strategy should expect frequent entries.",
            "path_like_but_not_local": "docs/site_data/candles/BTC_4h.json",
        })
        self.assertEqual(_find_leaked_paths(sample), [])


if __name__ == "__main__":
    unittest.main()
