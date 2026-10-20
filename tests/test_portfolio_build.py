"""Exercise product provenance, isolated publishing and the real UI exporter."""

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts import portfolio_build as portfolio
from scripts.design_acceptance import BROWSER_CHECKS
from tests.test_release_stage6 import workload

ROOT = Path(__file__).resolve().parents[1]
PREVIEW = b"<html><head>connect-src 'none'</head><body>Synthetic records</body></html>"


class PortfolioTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="agenthire-portfolio-test-")
        self.addCleanup(temporary.cleanup)
        self.folder = Path(temporary.name).resolve()
        self.root = self.folder / "agenthire-os"
        self.root.mkdir()
        source = {"README.md": b"Accepted product.\n", "app/main.py": b"accepted = True\n",
                  "scripts/fixtures/design_stage5_manifest.json": portfolio.encoded({
                      "feature_files": ["README.md"], "test_files": ["app/main.py"]})}
        assets = ROOT / "app/web/assets"
        source.update({path.relative_to(ROOT).as_posix(): path.read_bytes()
                       for path in assets.iterdir() if path.is_file()})
        source["scripts/design_browser.mjs"] = (ROOT / "scripts/design_browser.mjs").read_bytes()
        for name, data in source.items():
            target = self.root / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
        self.git("init", "--quiet", "--initial-branch=main")
        self.git("config", "user.name", "Portfolio Test")
        self.git("config", "user.email", "test@example.invalid")
        self.git("config", "commit.gpgsign", "false")
        self.git("config", "core.autocrlf", "false")
        self.git("add", ".")
        self.git("commit", "--quiet", "-m", "accepted fixture")
        commit = self.git("rev-parse", "HEAD")
        self.baseline = {**portfolio.BASELINE, "commit": commit, "file_count": len(source),
                         "source_sha256": portfolio.fingerprint(self.root, source)}
        for name in portfolio.FILES:
            target = self.root / name
            target.parent.mkdir(parents=True, exist_ok=True)
            data = (ROOT / name).read_bytes().replace(portfolio.BASELINE["commit"].encode(), commit.encode())
            target.write_bytes(data)
        (self.root / ".git/info/exclude").write_text(".env\n", encoding="utf-8")
        (self.root / ".env").write_bytes(b"PRIVATE_TEST_TOKEN=preserve\n")
        self.reports = self.folder / "AgentHire_OS_Release_Reports" / self.baseline["release_id"]
        self.reports.mkdir(parents=True)
        browser = {"version": "design-browser-v1", "source_kind": "browser_synthetic_fixture",
                   "source_sha256": portfolio.browser_fingerprint(self.root), "status": "passed",
                   "cleanup": "completed", "browser": "Chrome/test", "diagnostic": None,
                   "checks": [{"name": name, "passed": True} for name in sorted(BROWSER_CHECKS)]}
        children = {}
        for key, value in (("browser", browser), ("workload", workload())):
            path = self.reports / (key + ".json")
            path.write_bytes(portfolio.encoded(value))
            children[key + "_report"] = {"path": str(path), "sha256": portfolio.sha(path.read_bytes())}
        evidence = {"local_verified": True, "stage_complete": False, "external_pending": portfolio.PENDING.copy(),
                    "source": {"source_sha256": self.baseline["source_sha256"], "file_count": len(source)}, **children}
        release = {**evidence, "status": "local_verified", "executed": True,
                   "private_environment_unchanged": True, "finished_at": "2026-10-21T00:00:00Z"}
        checkpoint = {**evidence, "version": "release-local-checkpoint-v1", "commit": commit,
                      "committed_content_verified": True, "working_tree_clean": True}
        for key, name, value in (("acceptance_sha256", "release.json", release),
                ("checkpoint_sha256", f"checkpoint-{commit}.json", checkpoint)):
            path = self.reports / name
            path.write_bytes(portfolio.encoded(value))
            self.baseline[key] = portfolio.sha(path.read_bytes())
        self.output = self.folder / "published"

    def git(self, *arguments):
        env = {key: value for key, value in os.environ.items() if not key.upper().startswith("GIT_")}
        env.update(GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull)
        return subprocess.run(["git", "-C", str(self.root), *arguments], env=env,
                              capture_output=True, text=True, check=True, timeout=30).stdout.strip()

    def build(self, *, execute=True):
        return portfolio.build(self.root, self.output, execute=execute, baseline=self.baseline)

    def test_plan_starts_no_export_and_creates_no_output(self):
        with patch.object(portfolio, "export_preview", side_effect=AssertionError("export must not run")):
            result = self.build(execute=False)
        self.assertEqual(result["status"], "plan")
        self.assertFalse(self.output.exists())

    def test_build_is_reproducible_and_public_artifacts_exclude_private_reports(self):
        with patch.object(portfolio, "export_preview", return_value=PREVIEW):
            first, second = self.build(), self.build()
        self.assertEqual(first, second)
        site = Path(first["index"]).parent
        manifest = json.loads((site / "manifest.json").read_bytes())
        for name, expected in manifest["artifacts"].items():
            self.assertEqual(portfolio.sha((site / name).read_bytes()), expected)
        for path in site.iterdir():
            self.assertNotIn(b"PRIVATE_TEST_TOKEN", path.read_bytes())
            self.assertNotIn(str(self.reports).encode(), path.read_bytes())
        self.assertFalse(json.loads((site / "evidence.json").read_bytes())["video_required"])
        self.assertEqual((self.root / ".env").read_bytes(), b"PRIVATE_TEST_TOKEN=preserve\n")

    def test_product_and_unrelated_source_edits_are_rejected(self):
        for name in ("app/main.py", "docs/foreign.md"):
            with self.subTest(name=name):
                path = self.root / name
                before = path.read_bytes() if path.exists() else None
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b"Unexpected change.\n")
                with self.assertRaisesRegex(ValueError, "unrelated_portfolio_source_changes"):
                    self.build()
                if before is None:
                    path.unlink()
                else:
                    path.write_bytes(before)

    def test_unrelated_index_only_edit_is_rejected(self):
        path = self.root / "README.md"
        before = path.read_bytes()
        path.write_bytes(b"Unrelated staged change.\n")
        self.git("add", "--", "README.md")
        path.write_bytes(before)
        with self.assertRaisesRegex(ValueError, "unrelated_portfolio_source_changes"):
            self.build()

    def test_modified_receipt_is_rejected_before_export(self):
        (self.reports / "release.json").write_bytes(b"{}\n")
        with self.assertRaisesRegex(ValueError, "portfolio_receipt_hash_mismatch"):
            self.build()
        self.assertFalse(self.output.exists())

    def test_output_inside_source_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "portfolio_output_must_be_outside_git"):
            portfolio.build(self.root, self.root / "published", baseline=self.baseline)

    def test_modified_generated_artifact_is_preserved_and_rejected(self):
        with patch.object(portfolio, "export_preview", return_value=PREVIEW):
            result = self.build()
            path = Path(result["index"]).parent / "workspace.html"
            path.write_bytes(b"Changed artifact.\n")
            with self.assertRaisesRegex(ValueError, "generated_portfolio_changed"):
                self.build()
            self.assertEqual(path.read_bytes(), b"Changed artifact.\n")

    def test_source_change_during_export_prevents_publication(self):
        def export(_root, _output):
            path = self.root / "docs/portfolio/README.md"
            path.write_bytes(path.read_bytes() + b"Concurrent edit.\n")
            return PREVIEW

        with (
            patch.object(portfolio, "export_preview", side_effect=export),
            self.assertRaisesRegex(ValueError, "portfolio_source_changed_during_build"),
        ):
            self.build()
        self.assertEqual(list(self.output.glob("site-*")), [])

    def test_page_rejects_scripts_video_external_links_and_broken_anchors(self):
        raw = (ROOT / "docs/portfolio/index.html").read_bytes()
        for changed in (raw + b"<script>throw 1</script>", raw + b"<video></video>",
                raw.replace(b'href="workspace.html"', b'href="https://example.com"', 1),
                raw.replace(b'href="#workflow"', b'href="#missing"', 1)):
            with self.subTest(changed=changed[-40:]), self.assertRaises(ValueError):
                portfolio.validate_page(changed, portfolio.BASELINE["commit"])

    def test_presentation_fingerprint_accepts_bom_and_windows_newlines(self):
        before = portfolio.snapshot(self.root, self.baseline)
        for name in portfolio.FILES:
            path = self.root / name
            raw = path.read_bytes().removeprefix(b"\xef\xbb\xbf").replace(b"\r\n", b"\n")
            path.write_bytes(b"\xef\xbb\xbf" + raw.replace(b"\n", b"\r\n"))
        self.assertEqual(portfolio.snapshot(self.root, self.baseline), before)

    def test_real_exporter_bundles_the_product_ui_without_network_access(self):
        result = self.build()
        raw = (Path(result["index"]).parent / "workspace.html").read_bytes()
        self.assertIn(b"Open synthetic workspace", raw)
        self.assertIn(b"Alex Morgan", raw)
        self.assertIn(b"connect-src 'none'", raw)


if __name__ == "__main__":
    unittest.main()
