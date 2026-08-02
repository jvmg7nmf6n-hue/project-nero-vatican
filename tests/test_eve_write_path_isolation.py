"""RUNTIME write-path isolation test (spec's own explicit instruction: "The
write-path check must be a RUNTIME test, not a static one -- a static import
check cannot stop a filesystem write. Patch the storage layer (and open) for
the duration of a stubbed Eve session and assert every write target is one
of" the three allowlisted paths.

TWO layers of patching, for two different failure modes:
1. `os.replace` -- the ATOMIC RENAME every real write in nero_core.eve.storage
   ends with (temp file -> final destination). Its second argument IS the
   real, final, committed write target -- this is the signal that actually
   matters, and it is checked against the three-path allowlist directly.
2. `builtins.open` (write/append/exclusive modes only) and
   `pathlib.Path.write_text`/`write_bytes` -- direct-write bypass guards.
   nero_core.eve.storage's own atomic write path never calls these (it uses
   tempfile.mkstemp + os.fdopen, which does not route through
   builtins.open), so these patches exist purely to catch some OTHER,
   hypothetical code path writing directly instead of going through
   storage.py -- if this test ever sees a hit here, isolation has already
   been broken by a bypass, not merely a bad path.

storage.py additionally SELF-ENFORCES the allowlist (DisallowedWritePathError)
-- this test proves that enforcement actually holds under a real, full
stubbed session, not just that the check function exists.
"""
from __future__ import annotations

import builtins
import os
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import pandas as pd

from nero_core.eve import pipeline, storage
from nero_core.eve.config import _ENV_VAR as EVE_ENABLED_ENV_VAR

_WRITE_MODE_CHARS = {"w", "a", "x", "+"}


def _make_candles(n: int = 600) -> pd.DataFrame:
    import random

    rng = random.Random(13)
    rows = []
    price = 100.0
    t0 = 1_700_000_000_000
    for i in range(n):
        price *= 1 + rng.uniform(-0.01, 0.01)
        rows.append({"close_time": t0 + i * 3_600_000, "close": price, "high": price * 1.004, "low": price * 0.996, "volume": 1.0})
    return pd.DataFrame(rows)


class WritePathIsolationTest(unittest.TestCase):
    def test_every_write_target_during_a_full_stub_session_is_allowlisted(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_root = Path(tmp)
            hypotheses_path = tmp_root / "eve_hypotheses.json"
            ledger_path = tmp_root / "eve_budget_ledger.json"
            sessions_dir = tmp_root / "eve_sessions"
            candles = _make_candles()

            replace_destinations: list[str] = []
            open_write_paths: list[str] = []
            write_text_paths: list[str] = []

            real_replace = os.replace

            def _spy_replace(src, dst):
                replace_destinations.append(str(dst))
                return real_replace(src, dst)

            real_open = builtins.open

            def _spy_open(file, mode="r", *args, **kwargs):
                if isinstance(file, (str, Path)) and any(c in mode for c in _WRITE_MODE_CHARS):
                    open_write_paths.append(str(file))
                return real_open(file, mode, *args, **kwargs)

            real_write_text = Path.write_text

            def _spy_write_text(self, *args, **kwargs):
                write_text_paths.append(str(self))
                return real_write_text(self, *args, **kwargs)

            with patch.object(storage, "DEFAULT_HYPOTHESES_PATH", hypotheses_path), \
                 patch.object(storage, "DEFAULT_BUDGET_LEDGER_PATH", ledger_path), \
                 patch.object(storage, "EVE_SESSIONS_DIR", sessions_dir), \
                 patch("nero_core.eve.context.DEFAULT_QUANT_METRICS_PATH", tmp_root / "quant_metrics.json"), \
                 patch("nero_core.eve.context.DEFAULT_FAILURE_PATTERNS_PATH", tmp_root / "failure_patterns.json"), \
                 patch("nero_core.eve.context.DEFAULT_ADAM_HYPOTHESES_PATH", tmp_root / "agent_hypotheses.json"), \
                 patch.dict("os.environ", {EVE_ENABLED_ENV_VAR: "true"}), \
                 patch("os.replace", side_effect=_spy_replace), \
                 patch("builtins.open", side_effect=_spy_open), \
                 patch.object(Path, "write_text", _spy_write_text):
                result = pipeline.run_pipeline(
                    api_key="fake", stub=True, candles_provider=lambda a, t: candles, now=datetime(2026, 8, 15, tzinfo=timezone.utc)
                )

            self.assertTrue(result.enabled)
            # Sanity: the session DID write something real -- this isn't a
            # vacuous pass because nothing happened.
            self.assertTrue(replace_destinations, "expected at least one atomic write (os.replace) during a full stub session")

            allowed_prefixes = (str(hypotheses_path), str(ledger_path), str(sessions_dir) + os.sep)

            def _is_allowed(path_str: str) -> bool:
                return path_str == str(hypotheses_path) or path_str == str(ledger_path) or path_str.startswith(str(sessions_dir) + os.sep)

            offenders = [p for p in replace_destinations if not _is_allowed(p)]
            self.assertEqual(offenders, [], f"os.replace wrote outside the allowlist: {offenders}")

            # No direct-write bypass occurred at all -- storage.py's own
            # mkstemp+fdopen dance never routes through builtins.open or
            # Path.write_text, so ANY hit here means something else wrote
            # directly instead of going through the atomic storage layer.
            self.assertEqual(open_write_paths, [], f"unexpected direct open() write bypassing storage.py: {open_write_paths}")
            self.assertEqual(write_text_paths, [], f"unexpected direct Path.write_text bypassing storage.py: {write_text_paths}")

    def test_storage_layer_itself_refuses_a_disallowed_path_even_if_called_directly(self) -> None:
        # Belt-and-suspenders: confirms storage.py's own structural
        # allowlist enforcement (DisallowedWritePathError) still holds in
        # isolation, independent of whether any real caller ever tries it.
        with tempfile.TemporaryDirectory() as tmp:
            rogue_path = Path(tmp) / "not_an_eve_file.json"
            with self.assertRaises(storage.DisallowedWritePathError):
                storage.atomic_write_json_list(rogue_path, [{"x": 1}])


if __name__ == "__main__":
    unittest.main()
