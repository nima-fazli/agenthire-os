"""Build a static portfolio from the verified product; never start or modify its stack."""

import argparse
import hashlib
import json
import re
import subprocess
import tempfile
from html.parser import HTMLParser
from pathlib import Path

from scripts.design_acceptance import verify_browser_report
from scripts.release_acceptance import PENDING, validate_benchmark
from scripts.release_contract import browser_fingerprint, fingerprint, regular_file
from scripts.source_bundle import LIMIT, _git, checked_path

BASELINE = {
    "commit": "e331343bdd0384e2e246db4c0770636a1532f064",
    "source_sha256": "02edce9c435fe62a8569b3821e2a466379d985b175eddc781e08cffeeeeacbdd",
    "file_count": 425,
    "release_id": "release-179262e8765d476fa2bf2e504a3a5b0f",
    "acceptance_sha256": "bcda1f8893439813c7e48f17dfba279eafbddffa517591c8194f480ca2debe67",
    "checkpoint_sha256": "86e4c508e74cd4518e2ed7621517cd818f3cb032ddb29f7d461fb8d11f359e72",
}
FILES = ("docs/portfolio/index.html", "docs/portfolio/README.md",
         "scripts/portfolio_build.py", "tests/test_portfolio_build.py")


def require(condition, code):
    if not condition:
        raise ValueError(code)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def encoded(value):
    return (json.dumps(value, sort_keys=True, ensure_ascii=True, allow_nan=False, indent=2) + "\n").encode()


def document(path):
    require(path.is_file() and not any(p.is_symlink() or p.is_junction()
            for p in (path, *path.parents)), "unsafe_portfolio_document")
    require(path.stat().st_size <= 2 * 1024 * 1024, "portfolio_document_too_large")
    return path.read_bytes()


def snapshot(root, baseline):
    require(Path(_git(root, "rev-parse", "--show-toplevel").stdout.decode().strip()).resolve() == root,
            "portfolio_repository_root_required")
    _git(root, "merge-base", "--is-ancestor", baseline["commit"], "HEAD")
    product = set()
    for entry in _git(root, "ls-tree", "-r", "-z", baseline["commit"]).stdout.split(b"\0"):
        if entry:
            metadata, name = entry.split(b"\t", 1)
            mode, kind, _ = metadata.split()
            require(kind == b"blob" and mode in {b"100644", b"100755"}, "unsafe_product_tree")
            product.add(checked_path(name.decode("utf-8")))
    require(len(product) == baseline["file_count"], "product_inventory_mismatch")
    changed = set()
    for args in (("diff", "--name-only", "--no-renames", "-z", baseline["commit"], "--"),
                 ("ls-files", "--others", "--exclude-standard", "-z"),
                 ("diff", "--cached", "--name-only", "-z")):
        changed.update(name.decode("utf-8") for name in _git(root, *args).stdout.split(b"\0") if name)
    require(changed <= set(FILES), "unrelated_portfolio_source_changes")
    require(fingerprint(root, product) == baseline["source_sha256"], "verified_product_changed")
    names = product | set(FILES)
    require(sum(regular_file(root, name).stat().st_size for name in names) <= LIMIT, "portfolio_source_too_large")
    return {"product_commit": baseline["commit"], "product_source_sha256": baseline["source_sha256"],
            "portfolio_source_sha256": fingerprint(root, names), "source_file_count": len(names),
            "repository_head": _git(root, "rev-parse", "HEAD").stdout.decode().strip()}


def verified_source(root, baseline=BASELINE):
    before = snapshot(root, baseline)
    directory = root.parent / "AgentHire_OS_Release_Reports" / baseline["release_id"]
    checkpoint_raw = document(directory / f"checkpoint-{baseline['commit']}.json")
    release_raw = document(directory / "release.json")
    require(sha(checkpoint_raw) == baseline["checkpoint_sha256"]
            and sha(release_raw) == baseline["acceptance_sha256"], "portfolio_receipt_hash_mismatch")
    checkpoint, release = json.loads(checkpoint_raw), json.loads(release_raw)
    require(checkpoint.get("version") == "release-local-checkpoint-v1"
            and checkpoint.get("commit") == baseline["commit"]
            and checkpoint.get("committed_content_verified") is True
            and checkpoint.get("working_tree_clean") is True, "verified_checkpoint_required")
    for value in (checkpoint, release):
        require(value.get("local_verified") is True and value.get("stage_complete") is False
                and value.get("external_pending") == PENDING, "local_evidence_scope_mismatch")
        require(value["source"]["source_sha256"] == baseline["source_sha256"]
                and value["source"]["file_count"] == baseline["file_count"], "receipt_product_mismatch")
    require(release.get("status") == "local_verified" and release.get("executed") is True
            and release.get("private_environment_unchanged") is True, "successful_release_receipt_required")
    for key, filename in (("browser_report", "browser.json"), ("workload_report", "workload.json")):
        require(sha(document(directory / filename)) == release[key]["sha256"]
                and checkpoint[key]["sha256"] == release[key]["sha256"], "portfolio_child_report_mismatch")
    verify_browser_report(directory / "browser.json", browser_fingerprint(root))
    workload = json.loads(document(directory / "workload.json"))
    validate_benchmark(workload)
    browser = json.loads(document(directory / "browser.json"))
    evidence = {"version": "portfolio-evidence-v1", "scope": "owner_executed_local_verification",
                "product_commit": baseline["commit"], "product_source_sha256": baseline["source_sha256"],
                "product_file_count": baseline["file_count"], "verified_at": release["finished_at"],
                "recorded_console_results": {"windows_python_passed": 1943, "windows_platform_skips": 5,
                    "docker_python_passed": 1948, "native_client_passed": 80, "isolated_ci_checks_passed": 35},
                "browser": {"engine": browser["browser"], "checks_passed": len(browser["checks"])},
                "workload": {key: workload["measurement"][key] for key in
                    ("items", "concurrency", "completed", "source_kind", "cleanup")},
                "receipt_sha256": {"acceptance": baseline["acceptance_sha256"],
                    "checkpoint": baseline["checkpoint_sha256"], "browser": release["browser_report"]["sha256"],
                    "workload": release["workload_report"]["sha256"]},
                "stage6_complete": False, "external_pending": PENDING.copy(),
                "live_model_quality_repeated": False, "video_required": False}
    return before, evidence


class Page(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.ids, self.links, self.language, self.policy = set(), [], None, ""

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        require(tag not in {"script", "video", "iframe", "object", "embed"}, "unsupported_portfolio_embed")
        require(not any(name.startswith("on") for name, _ in attrs), "portfolio_event_handler_rejected")
        if tag == "html":
            self.language = (values.get("lang"), values.get("dir"))
        if "id" in values:
            require(values["id"] not in self.ids, "duplicate_portfolio_anchor")
            self.ids.add(values["id"])
        if tag == "meta" and values.get("http-equiv", "").lower() == "content-security-policy":
            self.policy = values.get("content", "")
        for name, value in attrs:
            if name in {"href", "src", "action", "srcset"}:
                require(tag == "a" and name == "href" and value, "external_portfolio_resource_rejected")
                self.links.append(value)


def validate_page(raw, commit):
    text = raw.decode("utf-8-sig")
    page = Page()
    page.feed(text)
    require(page.language == ("en", "ltr") and commit in text, "portfolio_identity_mismatch")
    require("connect-src 'none'" in page.policy and "script-src 'none'" in page.policy,
            "portfolio_network_policy_required")
    require(not re.search(r"@import\b|url\s*\(", text, re.IGNORECASE), "external_portfolio_style_rejected")
    require({"product", "workflow", "architecture", "verification", "decisions"} <= page.ids,
            "portfolio_sections_missing")
    for link in page.links:
        require(link[1:] in page.ids if link.startswith("#") else link in
                {"workspace.html", "README.md", "evidence.json", "manifest.json"}, "broken_portfolio_link")


def export_preview(root, output):
    version = subprocess.run(["node", "--version"], capture_output=True, text=True,
                             check=True, timeout=15).stdout.strip()
    require(re.fullmatch(r"v24\.[0-9]+\.[0-9]+", version), "node24_required")
    subprocess.run(["node", str(root / "scripts/design_browser.mjs"), "--export", str(output)],
                   cwd=root, stdin=subprocess.DEVNULL, capture_output=True, check=True, timeout=60)
    raw = document(output)
    require(b"connect-src 'none'" in raw and b"Synthetic records" in raw, "synthetic_preview_required")
    return raw


def build(root, output_parent=None, *, execute=False, baseline=BASELINE):
    root = Path(root).resolve()
    parent = Path(output_parent or root.parent / "AgentHire_OS_Portfolio").absolute()
    require(not any(p.is_symlink() or p.is_junction() for p in (parent, *parent.parents)), "unsafe_portfolio_output")
    parent = parent.resolve()
    require(not parent.is_relative_to(root), "portfolio_output_must_be_outside_git")
    before, evidence = verified_source(root, baseline)
    page = document(root / "docs/portfolio/index.html")
    validate_page(page, baseline["commit"])
    result = {"status": "plan", "executed": False, "source": before,
              "output_parent": str(parent), "video_required": False, "hosted_release_complete": False}
    if not execute:
        return result
    parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".portfolio-build-", dir=parent) as temporary:
        staging = Path(temporary)
        artifacts = {"index.html": page, "README.md": document(root / "docs/portfolio/README.md"),
                     "evidence.json": encoded(evidence), "workspace.html": export_preview(root, staging / "workspace.html")}
        manifest = {"version": "portfolio-artifacts-v1", "source": before, "video_required": False,
                    "artifacts": {name: sha(data) for name, data in sorted(artifacts.items())}}
        payload = encoded(manifest)
        artifacts["manifest.json"] = payload
        for name, data in artifacts.items():
            (staging / name).write_bytes(data)
        require(verified_source(root, baseline)[0] == before, "portfolio_source_changed_during_build")
        output = parent / ("site-" + sha(payload))
        if output.exists():
            require(output.is_dir() and not output.is_symlink() and not output.is_junction(), "unsafe_existing_portfolio")
            require({path.name for path in output.iterdir()} == set(artifacts), "unexpected_generated_portfolio_files")
            require(all(document(output / name) == data for name, data in artifacts.items()), "generated_portfolio_changed")
        else:
            staging.rename(output)
    result.update(status="built", executed=True, index=str(output / "index.html"),
                  manifest={"path": str(output / "manifest.json"), "sha256": sha(payload)})
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--output-parent", type=Path)
    args = parser.parse_args(argv)
    try:
        print(json.dumps(build(Path.cwd(), args.output_parent, execute=args.execute), indent=2))
        return 0
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as error:
        diagnostic = str(error) if isinstance(error, ValueError) else type(error).__name__
        print(json.dumps({"status": "failed", "diagnostic": diagnostic}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
