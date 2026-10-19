import io
import json
import subprocess
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.core.backup_store import BackupStore, read_json
from app.core.recovery_archive import export_objects
from scripts import backup_run as module
from scripts import backup_smoke
from tests.test_backup_store import complete_backup
from tests.test_recovery_archive import objects

SOURCE, TARGET = "agenthire-ci-" + "a" * 32, "agenthire-ci-" + "b" * 32


class Runner:
    def __init__(self, archive=b"", failure=None, *, source=SOURCE):
        self.archive, self.failure, self.source = archive, failure, source
        self.calls, self.started, self.audits = [], [], {}
        self.records = []
        services = ["api", "extraction-worker", "extraction-worker"]
        if source == "agenthire-os": services.append("embedding-worker")
        for index, service in enumerate(services):
            self.records.append({"id": str(index + 1) * 64, "project": source, "service": service,
                                 "image": "sha256:" + "e" * 64, "running": True, "health": "healthy"})

    def __call__(self, command, **options):
        command = tuple(command)
        self.calls.append(command)
        value = b""
        if command[0] == "git":
            value = ("main" if "--show-current" in command else module.BASELINE if "rev-parse" in command else "").encode()
        elif command[:3] == ("docker", "compose", "version"):
            return SimpleNamespace(returncode=0, stdout="5.5.1")
        elif command[1] in {"container", "volume", "network"}:
            occupied = (self.failure == "occupied-source" and self.source in command[-3]
                        or self.failure == "occupied-target" and TARGET in command[-3])
            return SimpleNamespace(returncode=0, stdout="occupied" if occupied else "")
        elif command[1] == "inspect":
            record = next(row for row in self.records if row["id"] == command[-1])
            value = json.dumps(record).encode()
        elif command[1] == "start":
            self.started.append(command[-1])
            if self.failure == "resume" and command[-1] == self.records[1]["id"]:
                return SimpleNamespace(returncode=9, stdout=b"PRIVATE", stderr=b"PRIVATE")
            record = next(row for row in self.records if row["id"] == command[-1])
            record.update(running=True, health="healthy")
        else:
            assert "--project-name" in command
            project = command[command.index("--project-name") + 1]
            assert project in {self.source, TARGET}
            assert Path(command[command.index("--env-file") + 1]).is_file()
            if project.startswith("agenthire-ci-"):
                assert options["env"]["AGENTHIRE_POSTGRES_PASSWORD"] != "HOST-PRIVATE"
            if self.failure == "build" and project == self.source and "build" in command:
                return SimpleNamespace(returncode=7, stdout=b"PRIVATE", stderr=b"PRIVATE")
            if "stop" in command:
                for row in self.records:
                    row.update(running=False, health="unhealthy")
            elif "ps" in command:
                active = [row["id"] for row in self.records if row["service"] == command[-1] and row["running"]]
                if self.failure == "writers" and not active and command[-1] == "api":
                    active = [self.records[0]["id"]]
                value = "\n".join(active).encode()
            elif "--version" in command:
                value = b"pg_dump (PostgreSQL) 18.6\n"
            elif "pg_dump" in command:
                if self.failure == "timeout": raise subprocess.TimeoutExpired(command, 1)
                if self.failure == "interrupt": raise KeyboardInterrupt
                if self.failure == "dump": return SimpleNamespace(returncode=7, stdout=b"PRIVATE", stderr=b"PRIVATE")
                options["stdout"].write(b"PGDMP-synthetic-retained-dump")
            elif module.IDENTITY_CODE in command:
                value = ("e" * 64).encode()
            elif "scripts.backup_objects" in command:
                action = command[command.index("scripts.backup_objects") + 1]
                if action == "export": options["stdout"].write(self.archive)
                elif action == "audit":
                    self.audits[project] = self.audits.get(project, 0) + 1
                    changed = (self.failure == "changed-source" and project == self.source and self.audits[project] >= 3
                               or self.failure == "fingerprint" and project == TARGET)
                    value = json.dumps({"status": "passed", "settings_identity": ("f" if self.failure == "settings" else "e") * 64,
                                        "dump_connection": {"database": "app-db", "user": "app-user"},
                                        "database": {"fingerprint": ("f" if changed else "a") * 64, "rows": 10}}).encode()
                else:
                    if action == "import": assert options["stdin"].read() == self.archive
                    value = json.dumps({"status": "passed", "objects": 2, "database_catalog_matches": True}).encode()
            elif "psql" in command:
                value = b"1" if self.failure == "target" else b"0"
            elif "pg_restore" in command:
                if self.failure == "restore": return SimpleNamespace(returncode=7, stdout=b"PRIVATE", stderr=b"PRIVATE")
                assert options["stdin"].read().startswith(b"PGDMP")
                assert "--single-transaction" in command and "--exit-on-error" in command
                assert "--clean" not in command and "--create" not in command
            elif "alembic" in command and "current" in command:
                value = b"0017_access_sessions (head)"
            elif "scripts.recovery_fixture" in command:
                value = b'{"status":"passed"}'
            elif "down" in command:
                if (self.failure == "cleanup" and project == TARGET
                        or self.failure == "source-cleanup" and project == self.source):
                    return SimpleNamespace(returncode=7, stdout=b"PRIVATE", stderr=b"PRIVATE")
            elif "up" in command and "api" in command and project == TARGET and self.failure == "api":
                return SimpleNamespace(returncode=7, stdout=b"PRIVATE", stderr=b"PRIVATE")
        return SimpleNamespace(returncode=0, stdout=value, stderr=b"")


@pytest.fixture
def setup(tmp_path, monkeypatch):
    repository = tmp_path / "repo"
    repository.mkdir()
    (repository / ".env").write_text("PRIVATE-HOST-ENVIRONMENT\n")
    source = tmp_path / "objects"
    source.mkdir()
    archive = io.BytesIO()
    export_objects(source, objects(source), archive)
    store = BackupStore(tmp_path / "vault", repository)
    store.initialize()
    monkeypatch.setattr(module, "repository_root", lambda path: repository)
    monkeypatch.setattr(backup_smoke, "repository_root", lambda path: repository)
    monkeypatch.setattr(module, "new_project_name", lambda: TARGET)
    monkeypatch.setattr(backup_smoke, "new_project_name", lambda: SOURCE)
    monkeypatch.setenv("AGENTHIRE_POSTGRES_PASSWORD", "HOST-PRIVATE")
    return repository, store, archive.getvalue()


@pytest.mark.parametrize("failure", [None, "dump", "timeout", "interrupt", "writers", "changed-source", "resume"])
def test_normal_capture_preserves_original_writers_and_failed_journal(setup, failure, capsys):
    repository, store, archive = setup
    runner = Runner(archive, failure, source="agenthire-os")
    code = module.main(["capture", "--store", str(store.root), "--execute"], runner=runner)
    text = capsys.readouterr().out
    result = json.loads(text)
    assert code == (0 if failure is None else 130 if failure == "interrupt" else 1)
    assert "PRIVATE" not in text
    assert (repository / ".env").read_text() == "PRIVATE-HOST-ENVIRONMENT\n"
    assert set(runner.started) == {row["id"] for row in runner.records}
    assert not any("down" in command or "--volumes" in command for command in runner.calls)
    assert (store.root / "journal.json").exists() == (failure == "resume")
    if failure is None:
        assert result["source_resume"] == "completed" and result["retained_backup"] is True
        assert len(store.inventories()) == 1
        assert (store.root / result["backup_id"] / "source.env").read_text() == "PRIVATE-HOST-ENVIRONMENT\n"
    elif failure != "resume":
        assert result["source_resume"] == "completed"
        assert not store.inventories()
    if failure == "resume":
        journal = read_json(store.root / "journal.json")
        assert len(journal["writers"]) == 4
        runner.failure = None
        assert module.main(["resume", "--store", str(store.root), "--execute"], runner=runner) == 0
        assert not (store.root / "journal.json").exists()


@pytest.mark.parametrize("action", ["init", "capture", "restore", "resume"])
def test_plan_does_not_launch_process_or_create_store(setup, action, capsys):
    repository, store, _ = setup
    destination = store.root.parent / "not-created"
    before = set(repository.parent.iterdir())
    arguments = [action, "--store", str(destination)]
    if action == "restore": arguments += ["--backup", "plan-only"]
    assert module.main(arguments, runner=lambda *args, **kwargs: pytest.fail("plan launched a process")) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "plan"
    assert set(repository.parent.iterdir()) == before


@pytest.mark.parametrize("failure", [None, "occupied-target", "target", "restore", "fingerprint", "api", "cleanup"])
def test_restore_owns_only_fresh_target_and_records_success_after_cleanup(setup, tmp_path, failure, monkeypatch):
    repository, store, archive = setup
    with zipfile.ZipFile(io.BytesIO(archive)) as original:
        timestamp = original.getinfo("objects.json").date_time
    shifted = (*timestamp[:5], (timestamp[5] + 2) % 60)
    with monkeypatch.context() as clock:
        clock.setattr(zipfile, "time", SimpleNamespace(time=lambda: 0, localtime=lambda _: shifted))
        identity = complete_backup(store, tmp_path)
    retained_archive = (store.root / identity / "documents.zip").read_bytes()
    assert retained_archive != archive
    with zipfile.ZipFile(io.BytesIO(archive)) as original, zipfile.ZipFile(io.BytesIO(retained_archive)) as retained:
        assert original.namelist() == retained.namelist()
        assert {name: original.read(name) for name in original.namelist()} == {
            name: retained.read(name) for name in retained.namelist()}
    runner = Runner(retained_archive, failure)
    report = {}
    if failure is None:
        module.restore(store, identity, repository, report, runner=runner)
        assert report["status"] == "passed" and report["cleanup"] == "completed"
        assert list((store.root / "receipts").iterdir())
    else:
        with pytest.raises((ValueError, module.BackupFailure)):
            module.restore(store, identity, repository, report, runner=runner)
        assert not list((store.root / "receipts").iterdir())
    cleanup = [command for command in runner.calls if "down" in command]
    assert len(cleanup) == (0 if failure == "occupied-target" else 1)
    assert all(TARGET in command for command in cleanup)
    assert not any("start" in command or "stop" in command for command in runner.calls)
    assert store.verify(identity)["backup_id"] == identity


def test_corrupted_backup_is_rejected_before_docker(setup, tmp_path):
    repository, store, _ = setup
    identity = complete_backup(store, tmp_path)
    (store.root / identity / "database.dump").write_bytes(b"corrupt")
    with pytest.raises(ValueError):
        module.restore(store, identity, repository, {}, runner=lambda *args, **kwargs: pytest.fail("corrupt backup reached Docker"))


def test_changed_runtime_configuration_aborts_before_stopping_writers(setup, capsys):
    _repository, store, archive = setup
    runner = Runner(archive, "settings", source="agenthire-os")
    assert module.main(["capture", "--store", str(store.root), "--execute"], runner=runner) == 1
    assert not any("stop" in command for command in runner.calls)
    assert not store.inventories()
    assert not (store.root / "journal.json").exists()
    assert "PRIVATE" not in capsys.readouterr().out


def test_capture_resumes_from_memory_even_when_pause_journal_is_damaged(setup, capsys):
    _repository, store, archive = setup
    original = Runner(archive, source="agenthire-os")
    def runner(command, **options):
        value = original(command, **options)
        if "pg_dump" in command and "--version" not in command:
            (store.root / "journal.json").write_text("damaged-journal")
        return value
    assert module.main(["capture", "--store", str(store.root), "--execute"], runner=runner) == 1
    result = json.loads(capsys.readouterr().out)
    assert result["source_resume"] == "completed"
    assert len(original.started) == 4
    assert all(row["running"] for row in original.records)
    assert (store.root / "journal.json").exists()


def test_dump_uses_the_api_database_role_and_name(setup, capsys):
    _repository, store, archive = setup
    runner = Runner(archive, source="agenthire-os")
    assert module.main(["capture", "--store", str(store.root), "--execute"], runner=runner) == 0
    dumped = next(call for call in runner.calls if "pg_dump" in call and "--version" not in call)
    assert "--username=app-user" in dumped and "--dbname=app-db" in dumped
    assert "sh" not in dumped and "-c" not in dumped
    text = capsys.readouterr().out
    assert "app-user" not in text and "app-db" not in text


def test_pre_upgrade_capture_uses_the_accepted_helper_image_without_build(setup):
    repository, store, archive = setup
    runner = Runner(archive, source="agenthire-os")
    source = module.normal_runtime(repository, runner=runner)
    identity = module.capture(store, source, repository / ".env", module.BASELINE, "normal", {}, prepare=False)
    assert store.verify(identity)["backup_id"] == identity
    assert not any("build" in command for command in runner.calls)
    assert set(runner.started) == {row["id"] for row in runner.records}


@pytest.mark.parametrize("failure", [None, "build", "stop", "migration", "drift"])
def test_stage3_upgrade_resumes_the_right_schema_and_never_resets_normal_data(tmp_path, monkeypatch, failure):
    from scripts import access_acceptance as stage

    class Source:
        def __init__(self):
            self.head, self.calls, self.resumed = stage.OLD_HEAD, [], False
        def writers(self):
            return [{"service": service} for service in ("api", "extraction-worker", "extraction-worker")]
        def stopped(self, records):
            assert len(records) == 3
        def resume(self, records):
            assert self.head == stage.OLD_HEAD and len(records) == 3
            self.resumed = True
        def call(self, command, **options):
            self.calls.append(command)
            if failure == "build" and "build" in command:
                raise stage.BackupFailure("build_failed")
            if failure == "stop" and "stop" in command:
                raise stage.BackupFailure("stop_failed")
            if "upgrade" in command:
                if failure == "migration":
                    raise stage.BackupFailure("migration_failed")
                self.head = stage.HEAD
            if failure == "drift" and "check" in command:
                raise stage.BackupFailure("drift_failed")
            return ""
    source = Source()
    monkeypatch.setattr(stage, "database_head", lambda source: source.head)
    monkeypatch.setattr(stage, "database_query", lambda source, sql: "0")
    monkeypatch.setattr(stage, "run", lambda *args: None)
    receipt = {"writers": source.writers()}
    if failure:
        with pytest.raises(stage.BackupFailure):
            stage.normal_upgrade(tmp_path, source, receipt, stage.OLD_HEAD)
    else:
        stage.normal_upgrade(tmp_path, source, receipt, stage.OLD_HEAD)
    assert not any("down" in command or "--volumes" in command or "downgrade" in command for command in source.calls)
    started = [command for command in source.calls if "up" in command]
    if failure in {"stop", "migration"}:
        assert source.resumed and not started
    elif failure == "build":
        assert not source.resumed and not started
    else:
        assert source.head == stage.HEAD and not source.resumed
        assert len(started) == 1 and "extraction-worker=2" in started[0]


def test_stage3_retry_requires_a_verified_pre_migration_receipt_before_building(setup, monkeypatch):
    from scripts import access_acceptance as stage
    repository, store, _ = setup
    monkeypatch.setattr(stage, "database_head", lambda source: stage.HEAD)
    with pytest.raises(FileNotFoundError):
        stage.pre_migration_backup(repository, SimpleNamespace(), store)
    assert store.inventories() == []


def stage3_source_fixture(root):
    from scripts import access_acceptance as stage
    names = [f"app/fixture_{number}.py" for number in range(39)] + [stage.MANIFEST]
    for name in names[:-1]:
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("value = 1\n", encoding="utf-8")
    manifest = {"version": "access-stage-3-v1", "base_commit": stage.BASE,
                "feature_files": names[:30], "test_files": names[30:],
                "sha256": {name: stage.digest(root / name) for name in names[:-1]}}
    target = root / stage.MANIFEST
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(manifest), encoding="utf-8")
    return stage, manifest, target


def test_stage3_plan_validates_complete_copied_source_without_launching_commands(tmp_path, monkeypatch, capsys):
    stage, manifest, _ = stage3_source_fixture(tmp_path)
    monkeypatch.setattr(stage, "__file__", str(tmp_path / "scripts/access_acceptance.py"))
    monkeypatch.setattr(stage, "run", lambda *_: pytest.fail("plan launched a process"))
    monkeypatch.setattr(stage, "capture", lambda *_: pytest.fail("plan inspected native state"))
    assert stage.main([]) == 0
    assert json.loads(capsys.readouterr().out)["executed"] is False
    (tmp_path / manifest["feature_files"][0]).write_text("wrong code\n")
    assert stage.main([]) == 2
    assert "file_content_mismatch" in capsys.readouterr().out


def test_stage3_manifest_rejects_private_files_before_reading_them(tmp_path):
    stage, manifest, target = stage3_source_fixture(tmp_path)
    replaced = manifest["feature_files"].pop()
    manifest["feature_files"].append(".env")
    del manifest["sha256"][replaced]
    manifest["sha256"][".env"] = "a" * 64
    target.write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="private_tracked_file"):
        stage.load_manifest(tmp_path)
