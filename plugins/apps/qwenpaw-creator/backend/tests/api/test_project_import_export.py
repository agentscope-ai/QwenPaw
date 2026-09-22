# -*- coding: utf-8 -*-
# pylint: disable=unused-argument,protected-access
"""Project archive export/import behavior and safety limits."""

from __future__ import annotations

import io
import hashlib
import json
import zipfile
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest

from api import project_routes
from api.example_routes import (
    _extract_example_archive,
)
from api.project_routes import _extract_archive_sanitized
from domain.errors import BadRequestError
from services.media_files import r2v_execution
from services.runtime_files import ProjectRuntimeSessionStore
from services.project_files.store import ProjectStore
from services.project_files import archive as project_archive
from services.project_files.models import IndexedFile

pytestmark = pytest.mark.unit

_CREATE_PAYLOAD = {
    "clientRequestId": "import-export-request-1",
    "name": "导入导出项目",
    "description": "归档往返",
    "scenario": "short_drama",
    "aspectRatio": "16:9",
    "resolution": "720P",
    "contentType": None,
}


async def _create_project(client) -> str:
    created = await client.post("/projects", json=_CREATE_PAYLOAD)
    assert created.status_code == 201
    return created.json()["projectId"]


async def _export(client, project_id):
    return await client.get(
        f"/projects/{project_id}/export",
        headers={"Idempotency-Key": uuid4().hex},
    )


async def _import(client, filename, archive):
    return await client.post(
        "/projects/import",
        headers={"Idempotency-Key": uuid4().hex},
        files={"file": (filename, archive, "application/zip")},
    )


@pytest.mark.parametrize("invalid_config", [False, True])
def test_archive_transfer_does_not_depend_on_current_model_settings(
    app,
    api_runtime_root,
    monkeypatch,
    run_scenario,
    invalid_config,
):
    config_path = api_runtime_root / "config" / "model_config.json"
    monkeypatch.setenv("CREATOR_MODEL_CONFIG_PATH", str(config_path))

    async def scenario(client):
        project_id = await _create_project(client)
        store = ProjectStore(api_runtime_root)
        before = store.read(project_id).project
        sessions = ProjectRuntimeSessionStore(api_runtime_root)
        session = sessions.get_project_session(project_id)
        stopped = sessions.hard_stop_session(project_id, session.session_id)
        exported = await _export(client, project_id)
        assert exported.status_code == 200
        deleted = await client.delete(
            f"/projects/{project_id}",
            headers={"Idempotency-Key": uuid4().hex},
        )
        assert deleted.status_code == 204
        config_path.parent.mkdir(exist_ok=True)
        config_path.write_text(
            json.dumps(
                {
                    "self_review": {
                        "sync_enabled": (
                            "legacy-invalid" if invalid_config else True
                        ),
                    },
                    "execution_authorization": {"mode": "allow_all"},
                },
            ),
        )
        config_before = config_path.read_bytes()
        imported = await _import(client, "backup.zip", exported.content)
        assert imported.status_code == 200, imported.text
        assert imported.json()["projectId"] == project_id
        assert store.read(project_id).project == before
        assert sessions.get_project_session_snapshot(project_id) == stopped
        assert config_path.read_bytes() == config_before
        reexported = await _export(client, project_id)
        assert reexported.status_code == 200, reexported.text
        if not invalid_config:
            listed = await client.get("/projects")
            assert listed.status_code == 200
            assert [item["projectId"] for item in listed.json()["items"]] == [
                project_id,
            ]

    run_scenario(app, scenario)


def test_export_does_not_cancel_sessions_or_consume_messages(
    app,
    api_runtime_root,
    run_scenario,
):
    async def scenario(client):
        project_id = await _create_project(client)
        runtime = ProjectRuntimeSessionStore(api_runtime_root)
        session = runtime.get_project_session(project_id)
        runtime.append_message(
            project_id,
            session.session_id,
            runtime.list_conversations(
                project_id,
                session.session_id,
            )[0].conversation_id,
            role="user",
            content_parts=[{"type": "text", "text": "待处理的指令"}],
        )
        before = runtime.get_project_session(project_id)
        exported = await _export(client, project_id)
        after = runtime.get_project_session(project_id)
        return exported, before, after

    exported, before, after = run_scenario(app, scenario)

    assert exported.status_code == 200
    # Export is a read: session status and the message queue are untouched.
    assert after.status == before.status
    assert after.status.value != "CANCELLED"
    assert after.last_consumed_message_seq == before.last_consumed_message_seq
    assert after.last_message_seq == before.last_message_seq


def test_veo_provider_key_is_absent_from_project_state_and_export(
    app,
    api_runtime_root,
    run_scenario,
) -> None:
    secret = "gm-export-secret"

    async def scenario(client):
        project_id = await _create_project(client)
        task_root = (
            api_runtime_root / project_id / "runtime" / "tasks" / "veo-1"
        )
        task_root.mkdir(parents=True)
        provider_result = r2v_execution._durable_provider_result(
            {
                "status": "SUCCEEDED",
                "result_url": (
                    f"https://video.example/result.mp4?key={secret}&alt=media"
                ),
                "download_auth": "x-goog-api-key",
            },
        )
        (task_root / "r2v-state.json").write_text(
            json.dumps({"provider_result": provider_result}),
            encoding="utf-8",
        )
        return await _export(client, project_id)

    exported = run_scenario(app, scenario)
    assert exported.status_code == 200
    with zipfile.ZipFile(io.BytesIO(exported.content)) as archive:
        assert all(
            secret.encode() not in archive.read(name)
            for name in archive.namelist()
        )


@pytest.mark.parametrize(
    "task_state",
    ["SUCCEEDED", "FAILED", "RUNNING", "unindexed", "missing", "corrupt"],
)
def test_export_omits_only_published_compose_scratch(
    app,
    api_runtime_root,
    run_scenario,
    task_state,
):
    async def scenario(client):
        project_id = await _create_project(client)
        store = ProjectStore(api_runtime_root)
        snapshot = store.read(project_id)
        project = snapshot.project.model_copy(deep=True)
        root = store.project_root(project_id)
        indexed = IndexedFile(
            file_id="film-file",
            kind="artifact_payload",
            relative_uri="assets/source:film/film.mp4",
            sha256=hashlib.sha256(b"film").hexdigest(),
            size_bytes=4,
            media_type="video/mp4",
            created_at=datetime.now(UTC),
        )
        project.assets.files_by_id[indexed.file_id] = indexed
        project.generation += 1
        (root / indexed.relative_uri).parent.mkdir(parents=True)
        (root / indexed.relative_uri).write_bytes(b"film")
        store.replace(project_id, project, expected_etag=snapshot.etag)
        task = root / "runtime/tasks/render/task.json"
        task.parent.mkdir(parents=True)
        result_file = indexed.model_dump(mode="json")
        if task_state == "unindexed":
            result_file["file_id"] = "not-in-project"
        if task_state == "missing":
            (root / indexed.relative_uri).unlink()
        task.write_text(
            "broken json"
            if task_state == "corrupt"
            else json.dumps(
                {
                    "status": (
                        task_state
                        if task_state in {"FAILED", "RUNNING"}
                        else "SUCCEEDED"
                    ),
                    "kind": "compose",
                    "result": {"indexedFile": result_file},
                },
            ),
        )
        scratch = root / "runtime/task-work/render/intermediate.mp4"
        scratch.parent.mkdir(parents=True)
        scratch.write_bytes(b"temporary duplicate")
        exported = await _export(client, project_id)
        assert exported.status_code == 200, exported.text
        with zipfile.ZipFile(io.BytesIO(exported.content)) as archive:
            assert (
                f"{project_id}/runtime/task-work/render/intermediate.mp4"
                in archive.namelist()
            ) is (task_state != "SUCCEEDED")
            assert (
                archive.read(f"{project_id}/project.json")
                == store.project_path(project_id).read_bytes()
            )
            assert (
                archive.read(f"{project_id}/runtime/tasks/render/task.json")
                == task.read_bytes()
            )
            if task_state != "missing":
                assert (
                    archive.read(f"{project_id}/{indexed.relative_uri}")
                    == b"film"
                )
        assert scratch.read_bytes() == b"temporary duplicate"
        await client.delete(
            f"/projects/{project_id}",
            headers={"Idempotency-Key": uuid4().hex},
        )
        imported = await _import(client, "roundtrip.zip", exported.content)
        if task_state == "missing":
            assert imported.status_code == 400
            assert not store.project_path(project_id).exists()
        else:
            assert imported.status_code == 200, imported.text
            assert (
                store.project_root(project_id) / indexed.relative_uri
            ).read_bytes() == b"film"

    run_scenario(app, scenario)


@pytest.mark.parametrize(
    "limit",
    ["MAX_ARCHIVE_BYTES", "MAX_EXTRACTED_BYTES", "MAX_MEMBERS"],
)
def test_export_enforces_import_limits_and_removes_partial_archives(
    app,
    api_runtime_root,
    run_scenario,
    monkeypatch,
    limit,
):
    async def scenario(client):
        project_id = await _create_project(client)
        monkeypatch.setattr(project_archive, limit, 1)
        with pytest.raises(BadRequestError):
            ProjectStore(api_runtime_root).export(project_id)
        assert not list((api_runtime_root / "exports").iterdir())
        assert (
            ProjectStore(api_runtime_root).read(project_id).project.name
            == _CREATE_PAYLOAD["name"]
        )

    run_scenario(app, scenario)


def _rename_archive_root(archive: bytes, new_root: str) -> bytes:
    out = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(archive)) as src:
        with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as dst:
            for info in src.infolist():
                parts = info.filename.split("/", 1)
                renamed = (
                    f"{new_root}/{parts[1]}" if len(parts) == 2 else new_root
                )
                dst.writestr(renamed, src.read(info.filename))
    return out.getvalue()


def test_import_rejects_folder_and_project_id_mismatch(
    app,
    api_runtime_root,
    run_scenario,
):
    async def scenario(client):
        project_id = await _create_project(client)
        exported = await _export(client, project_id)
        await client.delete(
            f"/projects/{project_id}",
            headers={"Idempotency-Key": uuid4().hex},
        )
        renamed = _rename_archive_root(
            exported.content,
            "project-999999999999",
        )
        imported = await _import(client, "evil.zip", renamed)
        listed = await client.get("/projects")
        return imported, listed

    imported, listed = run_scenario(app, scenario)

    assert imported.status_code == 400
    assert "does not match" in imported.json()["message"]
    # Nothing half-imported is left behind for the listing to trip on.
    assert listed.json()["items"] == []


def test_import_rejects_path_traversal_members(
    app,
    api_runtime_root,
    run_scenario,
):
    payload = io.BytesIO()
    with zipfile.ZipFile(payload, "w") as archive:
        archive.writestr("project-1/project.json", "{}")
        archive.writestr("../escape.txt", "boom")

    imported = run_scenario(
        app,
        lambda client: _import(client, "traversal.zip", payload.getvalue()),
    )

    assert imported.status_code == 400
    assert "escapes the extraction root" in imported.json()["message"]
    assert not (api_runtime_root.parent / "escape.txt").exists()


def test_import_enforces_upload_and_extraction_limits(
    app,
    api_runtime_root,
    monkeypatch,
    run_scenario,
):
    payload = io.BytesIO()
    with zipfile.ZipFile(payload, "w") as archive:
        archive.writestr("project-1/project.json", "x" * 4096)
    data = payload.getvalue()

    async def scenario(client):
        monkeypatch.setattr(project_archive, "MAX_ARCHIVE_BYTES", 16)
        oversized_zip = await _import(client, "big.zip", data)
        monkeypatch.setattr(
            project_archive,
            "MAX_ARCHIVE_BYTES",
            2 * 1024 * 1024 * 1024,
        )
        monkeypatch.setattr(project_archive, "MAX_EXTRACTED_BYTES", 16)
        zip_bomb = await _import(client, "bomb.zip", data)
        return oversized_zip, zip_bomb

    oversized_zip, zip_bomb = run_scenario(app, scenario)

    assert oversized_zip.status_code == 400
    assert "byte limit" in oversized_zip.json()["message"]
    assert zip_bomb.status_code == 400
    assert "expands beyond" in zip_bomb.json()["message"]
    # Failed imports never leave temp files behind.
    imports_root = api_runtime_root / "imports"
    assert not imports_root.exists() or not list(imports_root.iterdir())


@pytest.mark.parametrize(
    "extract",
    [_extract_example_archive, _extract_archive_sanitized],
)
def test_archive_extractors_reject_path_traversal(tmp_path, extract):
    archive_path = tmp_path / "test.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr("project-1/project.json", "{}")
        archive.writestr("../../../etc/passwd", "boom")
    extract_dir = tmp_path / "extract"
    extract_dir.mkdir()
    with pytest.raises(BadRequestError, match="escapes.*root"):
        extract(archive_path, extract_dir)


@pytest.mark.parametrize(
    "extract",
    [_extract_example_archive, _extract_archive_sanitized],
)
def test_archive_paths_do_not_silently_rename_or_collide(
    tmp_path,
    extract,
    monkeypatch,
):
    path = tmp_path / "names.zip"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("project-1/source:a/file.json", "colon")
        archive.writestr("project-1/source_a/file.json", "underscore")
    destination = tmp_path / "restored"
    extract(path, destination)
    assert (
        destination / "project-1/source:a/file.json"
    ).read_text() == "colon"
    assert (
        destination / "project-1/source_a/file.json"
    ).read_text() == "underscore"
    # Windows must reject an unrepresentable archive instead of returning
    # success with dangling references or overwriting one colliding file.
    monkeypatch.setattr(
        project_archive,
        "sys",
        SimpleNamespace(platform="win32"),
    )
    with pytest.raises(BadRequestError, match="not supported on Windows"):
        extract(path, tmp_path / "windows")


def test_validator_accepts_windows_reserved_chars(app, api_runtime_root):
    payload = io.BytesIO()
    with zipfile.ZipFile(payload, "w") as archive:
        archive.writestr("project-1/project.json", "{}")
        archive.writestr(
            "project-1/assets/source:cat_cam_1/file.txt",
            "data",
        )
    archive_path = api_runtime_root / "test.zip"
    api_runtime_root.mkdir(parents=True, exist_ok=True)
    archive_path.write_bytes(payload.getvalue())

    project_routes._validate_import_archive(archive_path)
