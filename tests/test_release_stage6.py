"""Release boundaries and failure paths, runnable without application dependencies."""

import copy
import hashlib
import io
import json
import os
import subprocess
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from scripts import release_acceptance as acceptance
from scripts import release_contract as contract
from scripts.ci_plan import CLIENT_TESTS
from scripts.design_acceptance import BROWSER_CHECKS

ROOT = Path(__file__).resolve().parents[1]


def workload():
    phase = {"samples": 4, "p50_ms": 1, "p95_ms": 2, "max_ms": 3, "failed": 0}
    return {"version": "benchmark-run-v1", "status": "passed", "kind": "workflow", "run_id": "a" * 32,
            "elapsed_seconds": 4, "diagnostic": None, "own_container_stop_requested": False,
            "resources": {"samples": 2, "metric": "docker_stats_memory_usage", "exact_peak": False,
                          "services": {name: {"replicas": count, "limit_bytes": 1024,
                          "sampled_memory_max_bytes": 512, "sampled_cpu_max_percent": 5.0}
                          for name, count in (("api", 1), ("postgres", 1), ("extraction-worker", 2))}},
            "measurement": {"version": "workload-benchmark-v1", "status": "passed", "run_id": "a" * 32,
                            "corpus_kind": "synthetic_pdf", "source_kind": "http_real_worker", "items": 4,
                            "concurrency": 2, "completed": 4, "queued_observed": 1, "running_observed": 1,
                            "cleanup": "completed", "diagnostic": None, "models_checked": False,
                            "phases": {name: phase.copy() for name in ("workflow", "request_to_completion", "retrieval")}}}


class ReleaseContractTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="agenthire-release-test-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.write("README.md", "Accepted base.\n")
        self.write("app/core/fixture.py", "accepted = True\n")
        self.git("init", "--quiet", "--initial-branch=main")
        self.git("add", ".")
        self.git("-c", "user.name=Release Test", "-c", "user.email=test@example.invalid",
                 "-c", "commit.gpgsign=false", "commit", "--quiet", "-m", "accepted fixture")
        base = self.git("rev-parse", "HEAD")
        patched = patch.object(contract, "BASE", base)
        patched.start()
        self.addCleanup(patched.stop)
        self.write("README.md", "Local release candidate.\n")
        self.write("docs/release.md", "Local scope only.\n")
        files = ["README.md", "docs/release.md", contract.MANIFEST]
        self.manifest = {"version": "release-stage-6-v1", "base_commit": base, "files": files,
                         "sha256": {name: contract.digest(self.root / name) for name in files if name != contract.MANIFEST}}
        self.store_manifest()

    def write(self, name, text):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    def git(self, *args):
        env = {k: v for k, v in os.environ.items() if not k.upper().startswith("GIT_")}
        # Match the contract reader so host line-ending rules cannot alter fixture blobs.
        env.update(GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull)
        return subprocess.run(["git", *args], cwd=self.root, env=env, check=True, capture_output=True,
                              text=True, timeout=30).stdout.strip()

    def store_manifest(self):
        self.write(contract.MANIFEST, json.dumps(self.manifest))

    def test_full_source_includes_unchanged_base_and_new_files(self):
        value = contract.load_manifest(self.root)
        snapshot = contract.source_snapshot(self.root, value)
        self.assertEqual(snapshot["file_count"], 4)
        self.assertFalse(snapshot["working_tree_clean"])
        self.assertEqual(len(snapshot["source_sha256"]), 64)

    def test_git_fixture_isolated_from_host_autocrlf_with_crlf_files(self):
        host_config = self.root / "host.gitconfig"
        host_config.write_text("[core]\n    autocrlf = true\n", encoding="utf-8")
        original_run = subprocess.run

        def host_run(command, **options):
            env = dict(options.get("env", os.environ))
            env.setdefault("GIT_CONFIG_GLOBAL", str(host_config))
            env.setdefault("GIT_CONFIG_NOSYSTEM", "1")
            options["env"] = env
            return original_run(command, **options)

        fixture = ReleaseContractTests("test_full_source_includes_unchanged_base_and_new_files")

        def windows_write(name, text):
            path = fixture.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(text.replace("\r\n", "\n").replace("\n", "\r\n").encode("utf-8"))

        fixture.write = windows_write
        with patch.object(subprocess, "run", side_effect=host_run):
            try:
                fixture.setUp()
                value = contract.load_manifest(fixture.root)
                snapshot = contract.source_snapshot(fixture.root, value)
                self.assertEqual(snapshot["file_count"], 4)
                self.assertEqual((fixture.root / "app/core/fixture.py").read_bytes(), b"accepted = True\r\n")
            finally:
                fixture.doCleanups()

    def test_delivery_rejects_changed_content(self):
        self.write("docs/release.md", "Changed without an updated delivery.\n")
        with self.assertRaisesRegex(ValueError, "release_source_mismatch"):
            contract.load_manifest(self.root)

    def test_canonical_digest_survives_bom_and_windows_newlines(self):
        before = contract.fingerprint(self.root, self.manifest["files"])
        target = self.root / "README.md"
        raw = target.read_bytes().replace(b"\r\n", b"\n")
        target.write_bytes(b"\xef\xbb\xbf" + raw.replace(b"\n", b"\r\n"))
        contract.load_manifest(self.root)
        self.assertEqual(before, contract.fingerprint(self.root, self.manifest["files"]))

    def test_unrelated_tracked_and_untracked_changes_are_rejected(self):
        for name in ("app/core/fixture.py", "docs/foreign.md"):
            with self.subTest(name=name):
                previous = (self.root / name).read_bytes() if (self.root / name).exists() else None
                self.write(name, "Unrelated edit.\n")
                with self.assertRaisesRegex(ValueError, "unrelated_release_source_changes"):
                    contract.source_snapshot(self.root, self.manifest)
                if previous is None:
                    (self.root / name).unlink()
                else:
                    (self.root / name).write_bytes(previous)

    def test_private_and_unsafe_manifest_paths_are_rejected(self):
        original = copy.deepcopy(self.manifest)
        for name in (".env", "../outside.py", "app\\outside.py", "/absolute.py", "docs/../outside.py"):
            with self.subTest(name=name):
                self.manifest = copy.deepcopy(original)
                self.manifest["files"][0] = name
                self.manifest["sha256"][name] = self.manifest["sha256"].pop("README.md")
                self.store_manifest()
                with self.assertRaises(ValueError):
                    contract.load_manifest(self.root)

    def test_missing_hash_and_duplicate_paths_are_rejected(self):
        original = copy.deepcopy(self.manifest)
        for duplicate in (False, True):
            with self.subTest(duplicate=duplicate):
                self.manifest = copy.deepcopy(original)
                if duplicate:
                    self.manifest["files"].append("README.md")
                else:
                    self.manifest["sha256"].pop("README.md")
                self.store_manifest()
                with self.assertRaisesRegex(ValueError, "invalid_release_file_list"):
                    contract.load_manifest(self.root)

    def test_other_branch_is_rejected(self):
        self.git("switch", "--quiet", "-c", "unrelated")
        with self.assertRaisesRegex(ValueError, "accepted_stage5_main_required"):
            contract.source_snapshot(self.root, self.manifest)


class ReleaseEvidenceTests(unittest.TestCase):
    def test_foreign_compose_and_model_overrides_cannot_redirect_normal_checks(self):
        original = {"PATH": "keep", "DOCKER_CONTEXT": "desktop-linux", "COMPOSE_FILE": "foreign.yaml",
                    "AGENTHIRE_SEMANTIC_ENABLED": "true", "AGENTHIRE_JWT_SECRET": "private",
                    "AGENTHIRE_BROWSER_BINARY": "installed-browser"}
        with patch.dict(os.environ, original, clear=True):
            value = acceptance.environment(ROOT)
            self.assertEqual(dict(os.environ), original)
        self.assertEqual(value["COMPOSE_PROJECT_NAME"], "agenthire-os")
        self.assertEqual(value["COMPOSE_FILE"], str(ROOT / "compose.yaml"))
        self.assertEqual(value["DOCKER_CONTEXT"], "desktop-linux")
        self.assertEqual(value["AGENTHIRE_BROWSER_BINARY"], "installed-browser")
        self.assertNotIn("AGENTHIRE_JWT_SECRET", value)
        self.assertNotIn("AGENTHIRE_SEMANTIC_ENABLED", value)

    def test_client_inventory_cannot_omit_a_suite(self):
        observed = {path.relative_to(ROOT).as_posix() for path in (ROOT / "tests").glob("*.test.mjs")}
        self.assertEqual(set(CLIENT_TESTS), observed)

    def test_plan_has_no_process_or_file_side_effects(self):
        output = io.StringIO()
        with patch.object(acceptance, "source_snapshot", side_effect=AssertionError("Git must not run")), \
                patch.object(subprocess, "run", side_effect=AssertionError("process must not run")), redirect_stdout(output):
            self.assertEqual(acceptance.main([]), 0)
        report = json.loads(output.getvalue())
        self.assertFalse(report["executed"])
        self.assertFalse(report["stage_complete"])
        self.assertEqual(report["external_pending"], acceptance.PENDING)

    def test_failure_output_does_not_disclose_private_command_details(self):
        output = io.StringIO()
        with patch.object(acceptance, "source_snapshot", side_effect=RuntimeError("private-detail")), redirect_stdout(output):
            self.assertEqual(acceptance.main(["--execute"]), 2)
        self.assertNotIn("private-detail", output.getvalue())
        self.assertFalse(json.loads(output.getvalue())["local_verified"])

    def test_workload_requires_real_worker_cleanup_and_complete_resource_evidence(self):
        acceptance.validate_benchmark(workload())
        mutations = [lambda v: v.update(status="incomplete"),
                     lambda v: v.update(own_container_stop_requested=True),
                     lambda v: v["measurement"].update(source_kind="fixture"),
                     lambda v: v["measurement"].update(cleanup="attention_required"),
                     lambda v: v["measurement"].update(items=3),
                     lambda v: v["measurement"]["phases"]["workflow"].update(failed=1),
                     lambda v: v["resources"].update(exact_peak=True),
                     lambda v: v["resources"]["services"].pop("api"),
                     lambda v: v["resources"]["services"]["extraction-worker"].update(replicas=1),
                     lambda v: v["resources"]["services"]["api"].update(sampled_cpu_max_percent=float("nan"))]
        for index, mutation in enumerate(mutations):
            with self.subTest(mutation=index):
                value = workload()
                mutation(value)
                with self.assertRaises(ValueError):
                    acceptance.validate_benchmark(value)

    def test_report_writes_are_exclusive_and_hash_exact_bytes(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "report.json"
            saved = acceptance.save_report(path, {"stage_complete": False})
            self.assertEqual(saved["sha256"], hashlib.sha256(path.read_bytes()).hexdigest())
            with self.assertRaises(FileExistsError):
                acceptance.save_report(path, {})

    def test_normal_stack_is_checked_after_a_failed_gate(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / ".env").write_text("private=preserve\n", encoding="utf-8")
            calls = []

            def run(_root, name, _args, _timeout, _env, *, capture=False):
                calls.append(name)
                if name == "native-python":
                    raise RuntimeError("tests failed")
                return "v24.1.0" if name == "node-version" else None

            report = {"checks": [], "stage_complete": False}
            with self.assertRaisesRegex(RuntimeError, "tests failed"):
                acceptance.execute(root, root, report, {}, run=run)
            self.assertEqual(calls[-1], "normal-stack-after")
            self.assertNotIn("local-workload", calls)
            self.assertEqual(report["active_check"], "native-python")
            self.assertTrue(report["private_environment_unchanged"])

    def test_private_configuration_change_cannot_be_accepted(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            private = root / ".env"
            private.write_text("private=original\n", encoding="utf-8")

            def run(_root, name, _args, _timeout, _env, *, capture=False):
                if name == "native-python":
                    private.write_text("private=concurrently-edited\n", encoding="utf-8")
                    raise RuntimeError("tests failed")
                return "v24.1.0" if name == "node-version" else None

            report = {"checks": [], "stage_complete": False}
            with self.assertRaisesRegex(ValueError, "private_environment_changed"):
                acceptance.execute(root, root, report, {}, run=run)
            self.assertEqual(report["active_check"], "private-environment-stability")
            self.assertFalse(report.get("local_verified", False))

    def test_local_success_cannot_complete_hosted_stage(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / ".env").write_text("private=preserve\n", encoding="utf-8")
            report = {"checks": [], "source": {"source_sha256": "b" * 64}, "stage_complete": False,
                      "external_pending": acceptance.PENDING.copy()}

            def run(_root, name, _args, _timeout, _env, *, capture=False):
                if name == "real-browser-design":
                    browser = {"version": "design-browser-v1", "source_kind": "browser_synthetic_fixture",
                               "source_sha256": "a" * 64, "status": "passed", "cleanup": "completed",
                               "browser": "Chrome/test", "diagnostic": None,
                               "checks": [{"name": n, "passed": True} for n in sorted(BROWSER_CHECKS)]}
                    (root / "browser.json").write_text(json.dumps(browser), encoding="utf-8")
                return {"node-version": "v24.1.0", "local-workload": json.dumps(workload()),
                        "docker-engine-capacity": '{"cpus":2,"memory_bytes":4096}'}.get(name)

            with patch.object(acceptance, "browser_fingerprint", return_value="a" * 64), \
                    patch.object(acceptance, "source_snapshot", return_value=report["source"]), \
                    patch.object(acceptance, "load_manifest", return_value={}):
                acceptance.execute(root, root, report, {}, run=run, refresh=lambda _root: None)
            self.assertTrue(report["local_verified"])
            self.assertFalse(report["stage_complete"])
            self.assertEqual(report["external_pending"], acceptance.PENDING)


if __name__ == "__main__":
    unittest.main()
