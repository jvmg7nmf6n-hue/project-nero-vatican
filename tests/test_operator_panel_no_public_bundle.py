"""CC-1 directive, item 3d: the Local Operator Panel must NEVER ship in the
public site bundle -- this is the hard guard + its own test. The panel
(tools/operator_panel/) is a physically separate directory/language
(Python/FastAPI) from website/ (TypeScript/Next.js), which already makes
accidental inclusion structurally near-impossible (a Next.js build cannot
bundle a `.py` file) -- but the directive asks for an EXPLICIT guard, so
this test proves the boundary directly rather than relying on that
structural fact alone: zero string references to this package anywhere
under website/, and website/'s own build inputs (package.json, next.config)
never mention it either."""
from __future__ import annotations

import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
WEBSITE_DIR = REPO_ROOT / "website"
OPERATOR_PANEL_DIR = REPO_ROOT / "tools" / "operator_panel"

NEEDLES = ("operator_panel", "operator-panel")


class OperatorPanelNeverInPublicBundleTest(unittest.TestCase):
    def test_operator_panel_directory_exists(self) -> None:
        # Sanity check the guard is testing something real, not a typo'd
        # path that would make every assertion below vacuously true.
        self.assertTrue(OPERATOR_PANEL_DIR.is_dir())
        self.assertTrue((OPERATOR_PANEL_DIR / "app.py").is_file())

    def test_zero_references_anywhere_under_website(self) -> None:
        offenders = []
        for path in WEBSITE_DIR.rglob("*"):
            if not path.is_file():
                continue
            if "node_modules" in path.parts or ".next" in path.parts:
                continue
            try:
                text = path.read_text(encoding="utf-8", errors="ignore")
            except (UnicodeDecodeError, OSError):
                continue
            for needle in NEEDLES:
                if needle in text:
                    offenders.append((str(path.relative_to(REPO_ROOT)), needle))
        self.assertEqual(offenders, [], f"operator panel referenced inside website/: {offenders}")

    def test_website_package_json_has_no_fastapi_or_uvicorn_dependency(self) -> None:
        package_json = WEBSITE_DIR / "package.json"
        text = package_json.read_text(encoding="utf-8")
        self.assertNotIn("fastapi", text.lower())
        self.assertNotIn("uvicorn", text.lower())

    def test_operator_panel_requirements_file_is_separate_from_main_requirements(self) -> None:
        # item 3a's own maintenance-cost note: fastapi/uvicorn must live in
        # their own requirements file, never merged into the main
        # requirements.txt every CI workflow/the public site's own tooling
        # installs.
        main_requirements = (REPO_ROOT / "requirements.txt").read_text(encoding="utf-8").lower()
        self.assertNotIn("fastapi", main_requirements)
        self.assertNotIn("uvicorn", main_requirements)
        panel_requirements = REPO_ROOT / "requirements-operator-panel.txt"
        self.assertTrue(panel_requirements.is_file())
        panel_text = panel_requirements.read_text(encoding="utf-8").lower()
        self.assertIn("fastapi", panel_text)
        self.assertIn("uvicorn", panel_text)

    def test_no_github_workflow_deploys_or_serves_the_operator_panel(self) -> None:
        workflows_dir = REPO_ROOT / ".github" / "workflows"
        offenders = []
        for path in workflows_dir.glob("*.yml"):
            text = path.read_text(encoding="utf-8", errors="ignore")
            for needle in NEEDLES:
                if needle in text:
                    offenders.append((str(path.relative_to(REPO_ROOT)), needle))
        self.assertEqual(offenders, [], f"a workflow references the operator panel: {offenders}")


if __name__ == "__main__":
    unittest.main()
