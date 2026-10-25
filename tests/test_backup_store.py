import io
import json
import os
from types import SimpleNamespace

import pytest

from app.core import backup_store as module
from app.core.recovery_archive import export_objects
from scripts.backup_run import BASELINE
from tests.test_recovery_archive import objects


@pytest.fixture
def store(tmp_path):
    repository = tmp_path / "repository"
    repository.mkdir()
    value = module.BackupStore(tmp_path / "vault", repository)
    value.initialize()
    return value


def complete_backup(store, tmp_path):
    identity, directory = store.new(source_kind="synthetic", revision=BASELINE)
    source = tmp_path / identity
    source.mkdir()
    rows = objects(source)
    archive = io.BytesIO()
    export_objects(source, rows, archive)
    for name, data in {
        "database.dump": b"PGDMPsynthetic-owned-dump",
        "documents.zip": archive.getvalue(),
        "source.env": b"AGENTHIRE_ENVIRONMENT=test\n",
        "database.json": json.dumps({"fingerprint": "a" * 64}).encode(),
    }.items():
        with module.open_private(directory / name, "wb") as handle:
            handle.write(data)
    store.seal(identity)
    return identity


def test_private_store_roundtrip_and_no_overwrite(store, tmp_path):
    with store.locked():
        identity = complete_backup(store, tmp_path)
        assert store.verify(identity)["backup_id"] == identity
        assert store.inventories() == [identity]
    with pytest.raises(FileExistsError):
        store.initialize()
    with pytest.raises(FileExistsError):
        module.write_json(store.root / "store.json", {})


@pytest.mark.parametrize("name", ["database.dump", "documents.zip", "source.env", "database.json", "state.json"])
def test_any_component_corruption_blocks_acceptance(store, tmp_path, name):
    identity = complete_backup(store, tmp_path)
    (store.root / identity / name).write_bytes(b"changed-private-fixture")
    with pytest.raises(ValueError, match="integrity"):
        store.verify(identity)


def test_partial_bundle_is_not_listed_or_pruned(store, tmp_path):
    identity, directory = store.new(source_kind="synthetic", revision=BASELINE)
    assert directory.name == identity + ".partial"
    assert store.inventories() == []
    with pytest.raises(ValueError, match="interrupted"):
        store.prune(3, execute=True)
    with pytest.raises(ValueError, match="Incomplete"):
        store.seal(identity)


def test_retention_requires_restored_retained_backup_and_keeps_recent(store, tmp_path):
    identities = [complete_backup(store, tmp_path) for _ in range(4)]
    assert identities == sorted(identities)
    with pytest.raises(ValueError, match="restore"):
        store.prune(2, execute=True)
    store.receipt(identities[-1])
    plan = store.prune(2)
    assert plan == {"remove": identities[:2], "retain": identities[2:], "executed": False}
    assert store.inventories() == identities
    assert store.prune(2, execute=True)["executed"] is True
    assert store.inventories() == identities[2:]


def test_corrupt_old_backup_blocks_all_deletion(store, tmp_path):
    identities = [complete_backup(store, tmp_path) for _ in range(3)]
    store.receipt(identities[-1])
    (store.root / identities[0] / "database.dump").write_bytes(b"corrupt")
    with pytest.raises(ValueError):
        store.prune(2, execute=True)
    assert store.inventories() == identities


@pytest.mark.parametrize("keep", [True, 0, 1, 21, "3"])
def test_unsafe_retention_count_is_rejected(store, keep):
    with pytest.raises(ValueError, match="between"):
        store.prune(keep, execute=True)


@pytest.mark.parametrize("identity", ["../outside", "", "/absolute", "C:\\outside", "backup-unknown"])
def test_backup_identity_cannot_escape_store(store, identity):
    with pytest.raises(ValueError, match="identity"):
        store.verify(identity)


def test_repository_and_ancestor_destinations_are_rejected(tmp_path):
    repository = tmp_path / "repo"
    repository.mkdir()
    for destination in (repository, repository / "storage", tmp_path):
        with pytest.raises(ValueError, match="separate"):
            module.BackupStore(destination, repository)


def test_lock_is_exclusive_and_released(store):
    with store.locked(), pytest.raises(OSError), store.locked():
        pytest.fail("another operator acquired the lock")
    with store.locked():
        pass


def test_journal_blocks_capture_and_retention(store):
    module.write_json(store.root / "journal.json", {"owned": True})
    with pytest.raises(ValueError, match="Resume"):
        store.new(source_kind="normal", revision=BASELINE)
    with pytest.raises(ValueError, match="interrupted"):
        store.prune(3)


def test_hardlinked_backup_file_is_rejected(store, tmp_path):
    identity = complete_backup(store, tmp_path)
    os.link(store.root / identity / "source.env", tmp_path / "linked-secret.env")
    with pytest.raises(ValueError, match="Unsafe"):
        store.verify(identity)


def test_windows_acl_is_fail_closed_and_never_prints_credentials(tmp_path, monkeypatch):
    calls = []
    proxy = SimpleNamespace(name="nt", path=os.path, environ={"KEEP": "present"})
    monkeypatch.setattr(module, "os", proxy)
    def runner(command, **options):
        calls.append((command, options))
        return SimpleNamespace(returncode=0, stdout="private")
    assert module.private_directory(tmp_path, initialize=True, runner=runner) == tmp_path
    command, options = calls[0]
    assert command[:4] == ("powershell.exe", "-NoProfile", "-NonInteractive", "-Command")
    assert options["env"]["AGENTHIRE_PRIVATE_STORE"] == str(tmp_path)
    assert options["env"]["AGENTHIRE_PRIVATE_INIT"] == "1"
    with pytest.raises(ValueError, match="ACL"):
        module.private_directory(tmp_path, runner=lambda *args, **kwargs: SimpleNamespace(returncode=1, stdout="private-secret"))


@pytest.mark.parametrize("module_key", ["PSModulePath", "PSMODULEPATH", "psmodulepath"])
def test_windows_acl_isolates_inherited_powershell_7_modules(tmp_path, monkeypatch, module_key):
    inherited = {"KEEP": "present", module_key: r"C:\Program Files\PowerShell\7\Modules"}
    monkeypatch.setattr(module, "os", SimpleNamespace(name="nt", path=os.path, environ=inherited))

    def runner(command, **options):
        assert all(key.upper() != "PSMODULEPATH" for key in options["env"])
        assert options["env"]["KEEP"] == "present"
        assert options["env"]["AGENTHIRE_PRIVATE_INIT"] == "1"
        return SimpleNamespace(returncode=0, stdout="private")

    assert module.private_directory(tmp_path, initialize=True, runner=runner) == tmp_path
    assert inherited[module_key] == r"C:\Program Files\PowerShell\7\Modules"


def test_ambiguous_json_is_rejected_before_any_store_operation(store):
    (store.root / "store.json").write_text('{"format":"wrong","format":"agenthire-private-backup-v1","store_id":"' + "a" * 32 + '"}')
    with pytest.raises(ValueError, match="Duplicate"):
        store.check()
