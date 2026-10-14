import re

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.web import router as ui


@pytest.fixture
def client():
    return TestClient(app)


@pytest.mark.parametrize("path", ["/workspace", "/workspace/"])
def test_public_shell_is_local_and_contains_no_private_data(client, path):
    response = client.get(path)
    assert response.status_code == 200
    assert '<html lang="fa" dir="rtl">' in response.text
    assert 'id="shell"' in response.text and 'id="auth-view"' in response.text
    assert '<script type="module" src="/workspace/assets/app.mjs">' in response.text
    assert "https://" not in response.text and "http://" not in response.text
    assert not re.search(r"\bon[a-z]+\s*=", response.text)
    assert response.headers["cache-control"] == "no-store"
    assert "'unsafe-inline'" not in response.headers["content-security-policy"]
    assert "connect-src 'self'" in response.headers["content-security-policy"]
    assert "frame-ancestors 'none'" in response.headers["content-security-policy"]
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "DENY"
    assert response.headers["referrer-policy"] == "no-referrer"


@pytest.mark.parametrize("filename", sorted(ui.ASSETS))
def test_all_declared_assets_are_served_with_explicit_types_and_no_cache(client, filename):
    response = client.get(f"/workspace/assets/{filename}")
    assert response.status_code == 200 and response.content
    assert response.headers["content-type"].startswith(ui.ASSETS[filename])
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["x-content-type-options"] == "nosniff"


@pytest.mark.parametrize("filename", ["router.py", "private.pdf", "config.py", "missing.mjs", "..%2Frouter.py"])
def test_private_or_unknown_files_are_never_exposed(client, filename):
    response = client.get(f"/workspace/assets/{filename}")
    assert response.status_code == 404
    assert "from fastapi" not in response.text


def test_symlink_cannot_expose_file_outside_assets(tmp_path, monkeypatch):
    secret = tmp_path / "private.txt"
    secret.write_text("PRIVATE-SOURCE", encoding="utf-8")
    assets = tmp_path / "assets"
    assets.mkdir()
    path = assets / "app.mjs"
    path.touch()
    monkeypatch.setattr(ui, "ASSET_ROOT", assets)
    monkeypatch.setattr(ui.Path, "is_symlink", lambda self: self == path)
    response = ui.asset_response("app.mjs")
    assert response.status_code == 404
    assert b"PRIVATE-SOURCE" not in response.body


def test_ui_head_is_bodyless_and_routes_do_not_change_api_schema(client):
    response = client.head("/workspace/")
    assert response.status_code == 200 and not response.content
    paths = client.get("/openapi.json").json()["paths"]
    assert not any(path.startswith("/workspace") for path in paths)
    assert "/auth/login" in paths and "/organizations" in paths


def test_browser_module_graph_resolves_to_public_assets_only():
    for filename in ui.ASSETS:
        text = (ui.ASSET_ROOT / filename).read_text(encoding="utf-8")
        if filename.endswith(".mjs"):
            for dependency in re.findall(r'from "\./([^"]+)"', text):
                assert dependency in ui.ASSETS
            assert "innerHTML" not in text and "insertAdjacentHTML" not in text
            assert "localStorage" not in text and "sessionStorage" not in text
            assert "serviceWorker" not in text


@pytest.mark.parametrize("filename", ["api.mjs", "dom.mjs"])
def test_empty_asset_never_returns_success(tmp_path, monkeypatch, filename):
    (tmp_path / filename).touch()
    monkeypatch.setattr(ui, "ASSET_ROOT", tmp_path)
    assert ui.asset_response(filename).status_code == 404


def _assert_named_module_exports(asset_root, filenames):
    filenames = frozenset(filenames)
    import_pattern = r"""import\s*\{([^}]*)\}\s*from\s*["']\./([^"']+)["']"""
    export_pattern = (
        r"export\s+(?:async\s+)?(?:function|class|const|let|var)\s+([\w$]+)"
    )
    for filename in sorted(filenames):
        if not filename.endswith(".mjs"):
            continue
        text = (asset_root / filename).read_text(encoding="utf-8")
        for names, dependency in re.findall(import_pattern, text):
            assert dependency in filenames, f"{filename}: undeclared module {dependency}"
            target = (asset_root / dependency).read_text(encoding="utf-8")
            exports = set(re.findall(export_pattern, target))
            specifiers = names.strip().split(",")
            if not specifiers[-1].strip():
                specifiers.pop()
            imports = set()
            for specifier in specifiers:
                binding = re.fullmatch(
                    r"([\w$]+)(?:\s+as\s+[\w$]+)?", specifier.strip()
                )
                assert binding is not None, (
                    f"Malformed named import in {filename}: {specifier!r}"
                )
                imports.add(binding.group(1))
            missing = imports - exports
            assert not missing, (
                f"{filename}: {dependency} does not export {', '.join(sorted(missing))}"
            )


def test_named_module_imports_have_matching_exports():
    _assert_named_module_exports(ui.ASSET_ROOT, ui.ASSETS)


@pytest.mark.parametrize(
    ("source", "target"),
    [
        (
            'import { value } from "./dep.mjs";',
            "export function value() {}",
        ),
        (
            'import { value, } from "./dep.mjs";',
            "export const value = 1;",
        ),
        (
            'import {\n  value,\n  other,\n} from "./dep.mjs";',
            "export class value {}\nexport async function other() {}",
        ),
        (
            "import {\n  value\tas\n  localValue,\n} from\n './dep.mjs';",
            "export let value = 1;",
        ),
    ],
    ids=["single-line", "trailing-comma", "multiline", "multiline-alias"],
)
def test_named_import_scan_accepts_valid_formatting(tmp_path, source, target):
    (tmp_path / "entry.mjs").write_text(source, encoding="utf-8")
    (tmp_path / "dep.mjs").write_text(target, encoding="utf-8")
    _assert_named_module_exports(tmp_path, {"entry.mjs", "dep.mjs"})


@pytest.mark.parametrize(
    "specifiers",
    ["missing,", "value as localValue, missing as value,"],
)
def test_named_import_scan_still_rejects_missing_exports(tmp_path, specifiers):
    (tmp_path / "entry.mjs").write_text(
        f'import {{{specifiers}}} from "./dep.mjs";', encoding="utf-8"
    )
    (tmp_path / "dep.mjs").write_text("export const value = 1;", encoding="utf-8")
    with pytest.raises(AssertionError, match=r"dep\.mjs does not export missing"):
        _assert_named_module_exports(tmp_path, {"entry.mjs", "dep.mjs"})


@pytest.mark.parametrize("specifiers", ["value,,", ",value", "value as,"])
def test_named_import_scan_rejects_malformed_bindings(tmp_path, specifiers):
    (tmp_path / "entry.mjs").write_text(
        f'import {{{specifiers}}} from "./dep.mjs";', encoding="utf-8"
    )
    (tmp_path / "dep.mjs").write_text("export const value = 1;", encoding="utf-8")
    with pytest.raises(AssertionError, match="Malformed named import"):
        _assert_named_module_exports(tmp_path, {"entry.mjs", "dep.mjs"})
