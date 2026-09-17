# -*- coding: utf-8 -*-
# pylint: disable=unused-argument
"""Project archive export/import behavior and safety limits."""
from __future__ import annotations

import asyncio
import io
import zipfile
from uuid import uuid4

import pytest

from api import project_routes
from httpx import ASGITransport, AsyncClient

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


def _client(app) -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://t")


def test_export_import_round_trip_restores_the_project(
    app,
    api_runtime_root,
):
    async def scenario():
        async with _client(app) as client:
            project_id = await _create_project(client)
            exported = await client.get(
                f"/projects/{project_id}/export",
                headers={"Idempotency-Key": uuid4().hex},
            )
            assert exported.status_code == 200
            archive = exported.content
            deleted = await client.delete(
                f"/projects/{project_id}",
                headers={"Idempotency-Key": uuid4().hex},
            )
            assert deleted.status_code == 204
            imported = await client.post(
                "/projects/import",
                headers={"Idempotency-Key": uuid4().hex},
                files={"file": ("backup.zip", archive, "application/zip")},
            )
            listed = await client.get("/projects")
            return project_id, imported, listed

    project_id, imported, listed = asyncio.run(scenario())

    assert imported.status_code == 200
    assert imported.json()["projectId"] == project_id
    # The restored Project is visible and readable again.
    assert [item["projectId"] for item in listed.json()["items"]] == [
        project_id,
    ]


def test_export_does_not_cancel_sessions_or_consume_messages(
    app,
    api_runtime_root,
):
    async def scenario():
        async with _client(app) as client:
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
            exported = await client.get(
                f"/projects/{project_id}/export",
                headers={"Idempotency-Key": uuid4().hex},
            )
            after = runtime.get_project_session(project_id)
            return exported, before, after

    exported, before, after = asyncio.run(scenario())

    assert exported.status_code == 200
    # Export is a read: session status and the message queue are untouched.
    assert after.status == before.status
    assert after.status.value != "CANCELLED"
    assert after.last_consumed_message_seq == before.last_consumed_message_seq
    assert after.last_message_seq == before.last_message_seq


def _rename_archive_root(archive: bytes, new_root: str) -> bytes:
    """Rebuild a project archive under a different top-level folder."""

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
):
    async def scenario():
        async with _client(app) as client:
            project_id = await _create_project(client)
            exported = await client.get(
                f"/projects/{project_id}/export",
                headers={"Idempotency-Key": uuid4().hex},
            )
            await client.delete(
                f"/projects/{project_id}",
                headers={"Idempotency-Key": uuid4().hex},
            )
            renamed = _rename_archive_root(
                exported.content,
                "project-999999999999",
            )
            imported = await client.post(
                "/projects/import",
                headers={"Idempotency-Key": uuid4().hex},
                files={"file": ("evil.zip", renamed, "application/zip")},
            )
            listed = await client.get("/projects")
            return imported, listed

    imported, listed = asyncio.run(scenario())

    assert imported.status_code == 400
    assert "does not match" in imported.json()["message"]
    # Nothing half-imported is left behind for the listing to trip on.
    assert listed.json()["items"] == []
    leftovers = [
        item
        for item in api_runtime_root.iterdir()
        if item.name.startswith("project-")
    ]
    assert leftovers == []


def test_import_rejects_path_traversal_members(app, api_runtime_root):
    async def scenario():
        async with _client(app) as client:
            payload = io.BytesIO()
            with zipfile.ZipFile(payload, "w") as archive:
                archive.writestr("project-1/project.json", "{}")
                archive.writestr("../escape.txt", "boom")
            imported = await client.post(
                "/projects/import",
                headers={"Idempotency-Key": uuid4().hex},
                files={
                    "file": (
                        "traversal.zip",
                        payload.getvalue(),
                        "application/zip",
                    ),
                },
            )
            return imported

    imported = asyncio.run(scenario())

    assert imported.status_code == 400
    assert "escapes the extraction root" in imported.json()["message"]
    assert not (api_runtime_root.parent / "escape.txt").exists()


def test_import_enforces_upload_and_extraction_limits(
    app,
    api_runtime_root,
    monkeypatch,
):
    async def scenario():
        async with _client(app) as client:
            payload = io.BytesIO()
            with zipfile.ZipFile(payload, "w") as archive:
                archive.writestr("project-1/project.json", "x" * 4096)
            data = payload.getvalue()

            monkeypatch.setattr(
                project_routes,
                "_IMPORT_MAX_ZIP_BYTES",
                16,
            )
            oversized_zip = await client.post(
                "/projects/import",
                headers={"Idempotency-Key": uuid4().hex},
                files={"file": ("big.zip", data, "application/zip")},
            )
            monkeypatch.setattr(
                project_routes,
                "_IMPORT_MAX_ZIP_BYTES",
                2 * 1024 * 1024 * 1024,
            )

            monkeypatch.setattr(
                project_routes,
                "_IMPORT_MAX_EXTRACTED_BYTES",
                16,
            )
            zip_bomb = await client.post(
                "/projects/import",
                headers={"Idempotency-Key": uuid4().hex},
                files={"file": ("bomb.zip", data, "application/zip")},
            )
            return oversized_zip, zip_bomb

    oversized_zip, zip_bomb = asyncio.run(scenario())

    assert oversized_zip.status_code == 400
    assert "byte limit" in oversized_zip.json()["message"]
    assert zip_bomb.status_code == 400
    assert "expands beyond" in zip_bomb.json()["message"]
    # Failed imports never leave temp files behind.
    imports_root = api_runtime_root / "imports"
    assert not imports_root.exists() or not list(imports_root.iterdir())
