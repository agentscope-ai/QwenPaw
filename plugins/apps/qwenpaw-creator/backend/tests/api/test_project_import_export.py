# -*- coding: utf-8 -*-
# pylint: disable=unused-argument,protected-access
"""Project archive export/import behavior and safety limits."""

from __future__ import annotations

import io
import hashlib
import json
import logging
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
from services.project_files.models import IndexedFile, Project

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


@pytest.mark.parametrize(
    "invalid_config",
    [False, True, "invalid-json", "invalid-provider", "null-model"],
)
def test_listing_and_archive_transfer_ignore_current_model_settings(
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
        if invalid_config == "invalid-json":
            config_path.write_text("{broken")
        elif invalid_config == "invalid-provider":
            config_path.write_text('{"asr": {"provider": "unsupported"}}')
        elif invalid_config == "null-model":
            config_path.write_text('{"llm": {"model_name": null}}')
        config_before = config_path.read_bytes()
        imported = await _import(client, "backup.zip", exported.content)
        assert imported.status_code == 200, imported.text
        assert imported.json()["projectId"] == project_id
        assert store.read(project_id).project == before
        assert sessions.get_project_session_snapshot(project_id) == stopped
        assert config_path.read_bytes() == config_before
        reexported = await _export(client, project_id)
        assert reexported.status_code == 200, reexported.text
        listed = await client.get("/projects")
        assert listed.status_code == 200, listed.text
        assert [item["projectId"] for item in listed.json()["items"]] == [
            project_id,
        ]
        assert listed.headers["X-Creator-Trace-ID"]
        config_read = await client.get("/models/config")
        assert config_read.status_code == (422 if invalid_config else 200)
        assert config_path.read_bytes() == config_before

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
            relative_uri="assets/source-film/film.mp4",
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
    if project_archive.sys.platform != "win32":
        extract(path, destination)
        assert (
            destination / "project-1/source:a/file.json"
        ).read_text() == "colon"
        assert (
            destination / "project-1/source_a/file.json"
        ).read_text() == "underscore"
    # A Windows extraction may rename an unrepresentable member, but a
    # pair that folds onto the same target is real corruption and has to
    # be refused rather than silently overwrite one of the two files.
    monkeypatch.setattr(
        project_archive,
        "sys",
        SimpleNamespace(platform="win32"),
    )
    with pytest.raises(
        BadRequestError,
        match="collide after Windows sanitization",
    ):
        extract(path, tmp_path / "windows")


@pytest.mark.parametrize(
    "extract",
    [_extract_example_archive, _extract_archive_sanitized],
)
def test_windows_extraction_renames_illegal_member_and_rewrites_registry(
    tmp_path,
    extract,
    monkeypatch,
):
    """One sidecar cannot kill the whole bundle: rename it and keep going.

    Regression for #8547: the bundled ``cat-perspective-0803`` example
    carries ``assets/source-intelligence/source:cat_cam_1/*.json`` and
    previously the whole 122 MiB archive failed to open on Windows.
    """
    project_json = {
        "assets": {
            "files_by_id": {
                "file-colon": {
                    "file_id": "file-colon",
                    "relative_uri": (
                        "assets/source-intelligence/"
                        "source:cat_cam_1/index.json"
                    ),
                    "sha256": "a" * 64,
                },
                "file-plain": {
                    "file_id": "file-plain",
                    "relative_uri": "assets/clip.mp4",
                    "sha256": "b" * 64,
                },
            },
        },
        "sources": {
            "items": {
                "source:cat_cam_1": {
                    "source_id": "source:cat_cam_1",
                    "order": ["source:cat_cam_1"],
                },
            },
        },
    }
    path = tmp_path / "bundle.zip"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(
            "project-1/project.json",
            json.dumps(project_json, ensure_ascii=False),
        )
        archive.writestr(
            "project-1/assets/source-intelligence/source:cat_cam_1/"
            "index.json",
            "{}",
        )
        archive.writestr("project-1/assets/clip.mp4", "binary")

    monkeypatch.setattr(
        project_archive,
        "sys",
        SimpleNamespace(platform="win32"),
    )
    destination = tmp_path / "out"
    extract(path, destination)

    assert (
        destination
        / "project-1/assets/source-intelligence/source_cat_cam_1/index.json"
    ).is_file()
    assert not (
        destination / "project-1/assets/source-intelligence/source:cat_cam_1"
    ).exists()
    assert (destination / "project-1/assets/clip.mp4").read_text() == (
        "binary"
    )
    restored = json.loads(
        (destination / "project-1/project.json").read_text(encoding="utf-8"),
    )
    files = restored["assets"]["files_by_id"]
    assert files["file-colon"]["relative_uri"] == (
        "assets/source-intelligence/source_cat_cam_1/index.json"
    )
    assert files["file-plain"]["relative_uri"] == "assets/clip.mp4"
    # Logical identifiers stay as authored; only on-disk paths move.
    assert restored["sources"]["items"] == project_json["sources"]["items"]


def test_windows_extraction_skips_registry_rewrite_for_skill_bundles(
    tmp_path,
    monkeypatch,
):
    """A SKILL.md bundle has no project.json; sanitization still works."""
    path = tmp_path / "skill.zip"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("my:skill/SKILL.md", "# hello")
    monkeypatch.setattr(
        project_archive,
        "sys",
        SimpleNamespace(platform="win32"),
    )
    destination = tmp_path / "out"
    project_archive.extract_archive(path, destination)
    assert (destination / "my_skill/SKILL.md").read_text() == "# hello"


def test_windows_registry_rewrite_is_atomic_and_canonical(
    tmp_path,
    monkeypatch,
):
    """CR feedback: the rewrite must publish atomically in canonical form.

    A truncated project.json left behind by a crash mid-rewrite would be
    published by the example flow, which only checks ``is_file()``. The
    on-disk bytes also have to match the canonical pretty form (indent 2
    plus a final newline) so tooling diffing project.json stays quiet.
    """
    path = tmp_path / "bundle.zip"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(
            "project-1/project.json",
            json.dumps(
                {
                    "assets": {
                        "files_by_id": {
                            "f": {
                                "relative_uri": "assets/source:a/x.json",
                            },
                        },
                    },
                },
            ),
        )
        archive.writestr("project-1/assets/source:a/x.json", "{}")
    monkeypatch.setattr(
        project_archive,
        "sys",
        SimpleNamespace(platform="win32"),
    )
    destination = tmp_path / "out"
    project_archive.extract_archive(path, destination)

    project_dir = destination / "project-1"
    raw = (project_dir / "project.json").read_text(encoding="utf-8")
    assert raw.endswith("}\n")
    assert (
        json.loads(raw)["assets"]["files_by_id"]["f"]["relative_uri"]
        == "assets/source_a/x.json"
    )
    # The temp file used for the atomic replace never survives.
    assert not list(project_dir.glob("*.tmp"))


def test_windows_registry_rewrite_skip_is_logged_not_fatal(
    tmp_path,
    monkeypatch,
    caplog,
):
    """CR feedback: substitutions with an unreadable registry must warn.

    The rename already happened on disk; silently returning would leave
    dangling relative_uris with nothing in creator.log to explain them.
    """
    path = tmp_path / "bundle.zip"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("project-1/project.json", "not json at all")
        archive.writestr("project-1/assets/source:a/x.json", "{}")
    monkeypatch.setattr(
        project_archive,
        "sys",
        SimpleNamespace(platform="win32"),
    )
    destination = tmp_path / "out"
    # Creator loggers stop propagating at the ``qwenpaw.creator`` family,
    # so caplog's root handler never sees them; attach it directly.
    archive_logger = logging.getLogger(
        "qwenpaw.creator.project_files.archive",
    )
    archive_logger.addHandler(caplog.handler)
    try:
        project_archive.extract_archive(path, destination)
    finally:
        archive_logger.removeHandler(caplog.handler)

    assert any(
        "skipped Windows relative_uri rewrite" in record.getMessage()
        for record in caplog.records
    )
    # Extraction still succeeds and the corrupt registry is left as-is.
    assert (destination / "project-1/assets/source_a/x.json").is_file()
    assert (
        destination / "project-1/project.json"
    ).read_text() == "not json at all"


def test_sanitize_windows_part_is_idempotent_and_total():
    """Legal names pass through, illegal ones fold onto a stable safe form."""
    for name in (
        "assets",
        "source-intelligence",
        "file-abc.json",
        "clip.mp4",
    ):
        assert project_archive._sanitize_windows_part(name) == name
    assert (
        project_archive._sanitize_windows_part("source:cat_cam_1")
        == "source_cat_cam_1"
    )
    assert project_archive._sanitize_windows_part("CON") == "_CON"
    assert project_archive._sanitize_windows_part("NUL.txt") == "_NUL.txt"
    assert project_archive._sanitize_windows_part("trail ") == "trail"
    assert project_archive._sanitize_windows_part("trail.") == "trail"
    assert project_archive._sanitize_windows_part(":") == "_"
    # Applying the sanitizer twice must not resanitize the already-safe name.
    for name in (
        "source:cat",
        "CON",
        "trail ",
        ":",
    ):
        once = project_archive._sanitize_windows_part(name)
        assert project_archive._sanitize_windows_part(once) == once


def test_export_rejects_directory_redirects(tmp_path, directory_link):
    project = Project.new(project_id="project-1", name="Archive")
    root = tmp_path / project.project_id
    root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "private.txt").write_bytes(b"must not be exported")
    directory_link(outside, root / "linked")
    destination = tmp_path / "export.zip"
    with pytest.raises(BadRequestError, match="non-regular path"):
        project_archive.write_project_archive(root, project, destination)
    assert not destination.exists()


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


def test_archive_budget_is_per_call_and_resolved_when_used(monkeypatch):
    """A caller's caps replace the Project ones; the defaults still follow.

    Skills import through the same extractor with a far smaller payload, so
    the budget has to be per call. The defaults are read when the limits are
    built rather than bound as argument defaults, because the import tests
    above move a cap by patching the module constant.
    """

    assert project_archive.archive_limits() == (
        project_archive.MAX_ARCHIVE_BYTES,
        project_archive.MAX_EXTRACTED_BYTES,
        project_archive.MAX_MEMBERS,
        None,
    )
    monkeypatch.setattr(project_archive, "MAX_EXTRACTED_BYTES", 8)
    assert project_archive.archive_limits().extracted_bytes == 8
    assert project_archive.archive_limits(max_extracted_bytes=4)[1] == 4


def test_extract_archive_honours_a_caller_supplied_budget(tmp_path):
    """Every field of a caller budget is enforced, and a refusal is clean."""

    path = tmp_path / "bundle.zip"
    with zipfile.ZipFile(path, "w", zipfile.ZIP_STORED) as archive:
        archive.writestr("one/SKILL.md", "a" * 8)
        archive.writestr("two/SKILL.md", "b" * 8)
    destination = tmp_path / "out"
    limits = project_archive.archive_limits

    with pytest.raises(BadRequestError, match="more than 1 entries"):
        project_archive.extract_archive(
            path,
            destination,
            limits=limits(max_members=1),
        )
    with pytest.raises(BadRequestError, match="expands beyond"):
        project_archive.extract_archive(
            path,
            destination,
            limits=limits(max_extracted_bytes=8),
        )
    with pytest.raises(BadRequestError, match="byte limit"):
        project_archive.extract_archive(
            path,
            destination,
            limits=limits(max_archive_bytes=8),
        )
    assert not list(destination.rglob("SKILL.md"))

    # A per-member cap is reached only while copying: the declared total is
    # inside the budget, so the member that overruns it has to be refused
    # mid-write and its partial file removed.
    with pytest.raises(BadRequestError, match="beyond its budget"):
        project_archive.extract_archive(
            path,
            destination,
            limits=limits(max_member_bytes=4),
        )
    assert not (destination / "one" / "SKILL.md").exists()

    project_archive.extract_archive(path, destination, limits=limits())
    assert (destination / "one" / "SKILL.md").read_text() == "a" * 8
    assert (destination / "two" / "SKILL.md").read_text() == "b" * 8


def test_copy_member_counts_written_bytes_not_declared_ones(tmp_path):
    """The budget stops the byte that would exceed it, before it lands.

    ``validate_archive`` can only read the sizes an archive declares. The
    stream here stands in for a member carrying more than it declared -- one
    that ignores the declared size -- so what is refused is the copy's own
    counter, and the partial file it had opened does not survive.
    """

    info = SimpleNamespace(filename="project-1/member.txt")
    archive = SimpleNamespace(open=lambda _info: io.BytesIO(b"x" * 64))

    kept = tmp_path / "kept.txt"
    written = project_archive._copy_member(
        archive,
        info,
        kept,
        remaining=64,
        member_bytes=None,
    )
    assert written == 64
    assert kept.read_bytes() == b"x" * 64

    refused = tmp_path / "refused.txt"
    with pytest.raises(BadRequestError, match="beyond its budget"):
        project_archive._copy_member(
            archive,
            info,
            refused,
            remaining=16,
            member_bytes=None,
        )
    assert not refused.exists()
    # A per-member cap refuses inside a larger remaining budget too.
    with pytest.raises(BadRequestError, match="beyond its budget"):
        project_archive._copy_member(
            archive,
            info,
            refused,
            remaining=1024,
            member_bytes=16,
        )
    assert not refused.exists()
