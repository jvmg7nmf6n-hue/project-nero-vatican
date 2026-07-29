"""Added after a real incident during this branch's own development (2026-07-29):
`env | grep` was run to check whether an Anthropic API key was configured, and it
printed the FULL key value into the session transcript instead of just its
presence/absence -- CLAUDE.md's "never read/print/copy secrets" rule, broken by
accident. The safe way to check for an env var's presence is `"VAR" in os.environ`
or `bool(os.environ.get("VAR"))` -- NEVER print/log/echo the value itself, and
never pipe a raw `env`/`printenv` dump through a filter as a "just checking if
it's set" step, since the match line still contains the value.

This file adds the structural guarantees that incident exposed as untested:

1. STATIC -- no .py file under nero_core/research_agent/ contains a `print(`
   call or imports `logging` at all (verified via `ast`, not a text scan, for
   the same reason test_research_agent_no_auto_wire.py uses ast: a substring
   scan would misflag this very docstring, which names `print(` in prose).
   This package has zero console/log output surface by design -- there is
   nowhere for a secret to leak to via output at all, structurally, not just
   by care in each call site.

2. DYNAMIC -- hypothesis_gen.py is the only research_agent module that ever
   receives `api_key`. Across every realistic failure path (connection error,
   bad HTTP status, malformed JSON, no text block in the response) and the
   success path, the key is sent ONLY as the `x-api-key` request header (spied
   on directly) and never appears anywhere in the function's own returned
   data (hypotheses, duplicates, errors) or in what actually gets persisted to
   disk.
"""
from __future__ import annotations

import ast
import json
import shutil
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import requests

from nero_core.research_agent.hypothesis_gen import generate_hypotheses, persist_hypotheses
from nero_core.research_agent.scanner import ScanFinding

RESEARCH_AGENT_DIR = Path(__file__).resolve().parents[1] / "nero_core" / "research_agent"
FAKE_SECRET = "sk-ant-TESTSECRET-4f9a2b7c-do-not-leak-this"
NOW = datetime(2026, 7, 29, tzinfo=timezone.utc)


class _FakeResponse:
    def __init__(self, payload: dict, status_ok: bool = True) -> None:
        self._payload = payload
        self._status_ok = status_ok

    def raise_for_status(self) -> None:
        if not self._status_ok:
            raise requests.HTTPError("400 Client Error: Bad Request for url: https://api.anthropic.com/v1/messages")

    def json(self) -> dict:
        return self._payload


def _finding() -> ScanFinding:
    return ScanFinding("extreme_zscore", "BTC", "1h", "BTC/1h extreme z-score", 3.0, 40.0, "measured note", NOW.isoformat())


def _flatten_for_leak_check(result) -> str:
    """Everything a caller could plausibly display, log, or persist from a
    GenerationRunResult -- concatenated into one string to grep for the secret."""
    return json.dumps({"hypotheses": result.hypotheses, "duplicates_skipped": result.duplicates_skipped, "errors": result.errors})


class StaticNoOutputSurfaceTest(unittest.TestCase):
    def test_no_research_agent_source_file_prints_or_imports_logging(self) -> None:
        py_files = sorted(RESEARCH_AGENT_DIR.glob("*.py"))
        self.assertGreater(len(py_files), 0)

        offenders: dict[str, list[str]] = {}
        for path in py_files:
            tree = ast.parse(path.read_text(), filename=str(path))
            hits: list[str] = []
            for node in ast.walk(tree):
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "print":
                    hits.append("print(...) call")
                elif isinstance(node, ast.Import):
                    if any(alias.name == "logging" for alias in node.names):
                        hits.append("import logging")
                elif isinstance(node, ast.ImportFrom) and node.module == "logging":
                    hits.append("from logging import ...")
            if hits:
                offenders[path.name] = hits

        self.assertEqual(offenders, {}, f"research_agent must have zero console/log output surface: {offenders}")


class DynamicApiKeyNeverLeaksTest(unittest.TestCase):
    def test_key_is_sent_only_as_the_x_api_key_header(self) -> None:
        payload = {
            "content": [{"type": "text", "text": json.dumps({
                "hypothesis_name": "X", "mechanism": "m", "entry_rule": "e", "structured_entry_rule": None,
                "exit_rule": "x", "stop_rule": "s", "structured_exit_plan": None, "asset": "BTC", "timeframe": "1h",
                "differs_from_graveyard": "d", "expected_frequency_claim": 10.0,
            })}],
            "usage": {"input_tokens": 10, "output_tokens": 10},
        }
        with patch("nero_core.research_agent.hypothesis_gen.requests.post", return_value=_FakeResponse(payload)) as mock_post:
            generate_hypotheses([_finding()], [], FAKE_SECRET, now=NOW)

        call_kwargs = mock_post.call_args.kwargs
        self.assertEqual(call_kwargs["headers"]["x-api-key"], FAKE_SECRET)
        # nowhere else in the request -- not the URL, not the JSON body
        self.assertNotIn(FAKE_SECRET, mock_post.call_args.args[0] if mock_post.call_args.args else "")
        self.assertNotIn(FAKE_SECRET, json.dumps(call_kwargs["json"]))

    def test_key_absent_from_result_on_connection_error(self) -> None:
        with patch(
            "nero_core.research_agent.hypothesis_gen.requests.post",
            side_effect=requests.exceptions.ConnectionError("Failed to establish a new connection: [Errno 111] refused"),
        ):
            result = generate_hypotheses([_finding()], [], FAKE_SECRET, now=NOW)

        self.assertEqual(len(result.errors), 1)
        self.assertNotIn(FAKE_SECRET, _flatten_for_leak_check(result))

    def test_key_absent_from_result_on_bad_http_status(self) -> None:
        with patch("nero_core.research_agent.hypothesis_gen.requests.post", return_value=_FakeResponse({}, status_ok=False)):
            result = generate_hypotheses([_finding()], [], FAKE_SECRET, now=NOW)

        self.assertEqual(len(result.errors), 1)
        self.assertNotIn(FAKE_SECRET, _flatten_for_leak_check(result))

    def test_key_absent_from_result_on_malformed_json_response(self) -> None:
        payload = {"content": [{"type": "text", "text": "not valid json at all"}], "usage": {}}
        with patch("nero_core.research_agent.hypothesis_gen.requests.post", return_value=_FakeResponse(payload)):
            result = generate_hypotheses([_finding()], [], FAKE_SECRET, now=NOW)

        self.assertEqual(len(result.errors), 1)
        self.assertNotIn(FAKE_SECRET, _flatten_for_leak_check(result))

    def test_key_absent_from_result_on_no_text_block(self) -> None:
        payload = {"content": [{"type": "thinking", "thinking": "..."}], "usage": {}}
        with patch("nero_core.research_agent.hypothesis_gen.requests.post", return_value=_FakeResponse(payload)):
            result = generate_hypotheses([_finding()], [], FAKE_SECRET, now=NOW)

        self.assertEqual(len(result.errors), 1)
        self.assertNotIn(FAKE_SECRET, _flatten_for_leak_check(result))

    def test_key_absent_from_the_persisted_file_on_disk(self) -> None:
        payload = {
            "content": [{"type": "text", "text": json.dumps({
                "hypothesis_name": "X", "mechanism": "m", "entry_rule": "e", "structured_entry_rule": None,
                "exit_rule": "x", "stop_rule": "s", "structured_exit_plan": None, "asset": "BTC", "timeframe": "1h",
                "differs_from_graveyard": "d", "expected_frequency_claim": 10.0,
            })}],
            "usage": {"input_tokens": 10, "output_tokens": 10},
        }
        tmp = Path(tempfile.mkdtemp())
        try:
            path = tmp / "agent_hypotheses.json"
            with patch("nero_core.research_agent.hypothesis_gen.requests.post", return_value=_FakeResponse(payload)):
                result = generate_hypotheses([_finding()], [], FAKE_SECRET, now=NOW)
            persist_hypotheses(result.hypotheses, path)

            self.assertNotIn(FAKE_SECRET, path.read_text())
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
