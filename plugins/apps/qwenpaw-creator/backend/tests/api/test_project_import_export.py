# -*- coding: utf-8 -*-
# pylint: disable=unused-argument,protected-access
"""Project archive export/import behavior and safety limits."""

from __future__ import annotations

import io
import json
import zipfile
from uuid import uuid4

import pytest

from api import project_routes
from services.media_files import r2v_execution
from services.runtime_files import ProjectRuntimeSessionStore

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


def test_export_import_round_trip_restores_the_project(
    app,
    api_runtime_root,
    run_scenario,
):
    async def scenario(client):
        project_id = await _create_project(client)
        exported = await _export(client, project_id)
        assert exported.status_code == 200
        deleted = await client.delete(
            f"/projects/{project_id}",
            headers={"Idempotency-Key": uuid4().hex},
        )
        assert deleted.status_code == 204
        imported = await _import(client, "backup.zip", exported.content)
        listed = await client.get("/projects")
        return project_id, imported, listed

    project_id, imported, listed = run_scenario(app, scenario)

    assert imported.status_code == 200
    assert imported.json()["projectId"] == project_id
    assert [item["projectId"] for item in listed.json()["items"]] == [
        project_id,
    ]


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
        monkeypatch.setattr(project_routes, "_IMPORT_MAX_ZIP_BYTES", 16)
        oversized_zip = await _import(client, "big.zip", data)
        monkeypatch.setattr(
            project_routes,
            "_IMPORT_MAX_ZIP_BYTES",
            2 * 1024 * 1024 * 1024,
        )
        monkeypatch.setattr(project_routes, "_IMPORT_MAX_EXTRACTED_BYTES", 16)
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
