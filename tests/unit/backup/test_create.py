# -*- coding: utf-8 -*-
from __future__ import annotations

import threading
import zipfile
from types import SimpleNamespace

import pytest

from qwenpaw.backup._ops import create as create_module
from qwenpaw.backup._ops.create import BackupCancelled
from qwenpaw.backup._ops.create_helpers import add_agent_workspaces
from qwenpaw.backup.models import BackupMeta, BackupScope


def test_successful_create_atomically_publishes_archive(
    tmp_path,
    monkeypatch,
):
    destination = tmp_path / "backup.zip"
    meta = BackupMeta(
        name="complete",
        scope=BackupScope(
            include_agents=False,
            include_global_config=False,
            include_secrets=False,
            include_skill_pool=False,
        ),
    )
    events: list[dict] = []

    monkeypatch.setattr(create_module, "BACKUP_DIR", tmp_path)
    monkeypatch.setattr(create_module, "zip_path", lambda _id: destination)
    monkeypatch.setattr(
        create_module,
        "load_config",
        lambda: SimpleNamespace(agents=SimpleNamespace(profiles={})),
    )

    result = create_module.create_backup(
        meta,
        [],
        events.append,
        threading.Event(),
    )

    assert result.id == meta.id
    assert destination.is_file()
    assert not destination.with_suffix(".tmp").exists()
    with zipfile.ZipFile(destination) as archive:
        assert "meta.json" in archive.namelist()
    assert events[-1] == {"type": "saving", "percent": 90}


def test_workspace_cancel_is_checked_between_files(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "a.txt").write_text("a", encoding="utf-8")
    (workspace / "b.txt").write_text("b", encoding="utf-8")
    stop_event = threading.Event()
    written: list[str] = []

    class RecordingZip:
        def write(self, _path, arcname):
            written.append(arcname)
            stop_event.set()

    completed = add_agent_workspaces(
        RecordingZip(),
        [("agent-1", SimpleNamespace(workspace_dir=str(workspace)))],
        stop_event=stop_event,
    )

    assert completed is False
    assert len(written) == 1


def test_cancelled_create_removes_temp_and_final_archive(
    tmp_path,
    monkeypatch,
):
    destination = tmp_path / "backup.zip"
    stop_event = threading.Event()
    meta = BackupMeta(
        name="cancelled",
        scope=BackupScope(
            include_agents=False,
            include_global_config=False,
            include_secrets=False,
            include_skill_pool=False,
        ),
    )

    monkeypatch.setattr(create_module, "BACKUP_DIR", tmp_path)
    monkeypatch.setattr(create_module, "zip_path", lambda _id: destination)
    monkeypatch.setattr(
        create_module,
        "load_config",
        lambda: SimpleNamespace(agents=SimpleNamespace(profiles={})),
    )

    def cancel_during_collection(*_args, **_kwargs):
        stop_event.set()
        return []

    monkeypatch.setattr(
        create_module,
        "add_files_to_zip",
        cancel_during_collection,
    )

    with pytest.raises(BackupCancelled):
        create_module.create_backup(meta, [], lambda _event: None, stop_event)

    assert not destination.exists()
    assert not destination.with_suffix(".tmp").exists()


def test_cancelled_during_signing_removes_temp_and_final_archive(
    tmp_path,
    monkeypatch,
):
    destination = tmp_path / "backup.zip"
    stop_event = threading.Event()
    meta = BackupMeta(
        name="cancelled-during-signing",
        scope=BackupScope(
            include_agents=False,
            include_global_config=False,
            include_secrets=False,
            include_skill_pool=False,
        ),
    )

    monkeypatch.setattr(create_module, "BACKUP_DIR", tmp_path)
    monkeypatch.setattr(create_module, "zip_path", lambda _id: destination)
    monkeypatch.setattr(
        create_module,
        "load_config",
        lambda: SimpleNamespace(agents=SimpleNamespace(profiles={})),
    )

    def cancel_during_signing(_src_zip, signed_meta, *, dest_zip):
        dest_zip.write_bytes(b"published")
        stop_event.set()
        return signed_meta

    monkeypatch.setattr(
        create_module,
        "replace_meta_with_local_signature",
        cancel_during_signing,
    )

    with pytest.raises(BackupCancelled):
        create_module.create_backup(meta, [], lambda _event: None, stop_event)

    assert not destination.exists()
    assert not destination.with_suffix(".tmp").exists()
