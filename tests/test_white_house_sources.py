from __future__ import annotations

import unittest
from unittest.mock import Mock, patch

from nero_core.macro_policy.white_house_sources import fetch_source_snapshot, list_official_sources


class WhiteHouseSourcesTest(unittest.TestCase):
    def test_source_registry_contains_official_sources(self) -> None:
        sources = list_official_sources()
        names = {source.name for source in sources}

        self.assertIn("White House Briefing Room", names)
        self.assertIn("GovInfo Presidential Documents", names)
        self.assertIn("American Presidency Project", names)
        self.assertIn("Biden White House Archive", names)

    def test_fetch_source_snapshot_counts_relevant_links(self) -> None:
        # No live network call — requests.get is mocked, matching the "no live calls in
        # tests" constraint for this audit task.
        html = """
        <html><body>
          <a href="/briefing-room/presidential-actions/test">Strategic Bitcoin Reserve announcement</a>
          <a href="/briefing-room/statements/test">A ceremonial event</a>
        </body></html>
        """
        response = Mock()
        response.text = html
        response.raise_for_status.return_value = None

        with patch("nero_core.macro_policy.white_house_sources.requests.get", return_value=response):
            frame = fetch_source_snapshot(max_links_per_source=5)

        self.assertEqual(set(frame["status"]), {"ok"})
        self.assertGreaterEqual(int(frame["relevant_links"].sum()), 1)
        self.assertTrue(frame["sample_relevant_text"].astype(str).str.contains("Bitcoin Reserve").any())

    def test_fetch_source_snapshot_reports_errors_without_raising(self) -> None:
        import requests as requests_module

        with patch(
            "nero_core.macro_policy.white_house_sources.requests.get",
            side_effect=requests_module.exceptions.Timeout("timed out"),
        ):
            frame = fetch_source_snapshot()

        self.assertEqual(set(frame["status"]), {"error"})
        self.assertTrue((frame["error"] == "Timeout").all())

    def test_extract_links_deduplicates_and_resolves_relative_urls(self) -> None:
        from nero_core.macro_policy.white_house_sources import _extract_links

        html = """
        <a href="/briefing-room/a">First link</a>
        <a href="/briefing-room/a">First link</a>
        <a href="https://example.com/full">Full URL link</a>
        """

        links = _extract_links(html, "https://www.whitehouse.gov/", limit=10)

        self.assertEqual(len(links), 2)
        self.assertEqual(links[0]["url"], "https://www.whitehouse.gov/briefing-room/a")
        self.assertEqual(links[1]["url"], "https://example.com/full")


if __name__ == "__main__":
    unittest.main()
