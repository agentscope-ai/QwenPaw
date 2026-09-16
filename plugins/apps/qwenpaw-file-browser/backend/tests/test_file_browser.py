# -*- coding: utf-8 -*-
"""Read-only file-browser setup, persistence, and adapter tests."""
# pylint: disable=wrong-import-position

from __future__ import annotations

import importlib.util
import json
import os
import sys
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
from fastapi import FastAPI, Request

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from file_browser import (  # noqa: E402
    APP_ID,
    FileBrowserStore,
    FileBrowserTaskAdapter,
    list_directory_action_descriptor,
    make_input_resolver,
    make_setup_checker,
    render_directory,
)
from qwenpaw.pawapp.tasks import (  # noqa: E402
    TaskHandle,
    TaskOrigin,
    TaskScope,
    TaskStoreError,
    TaskSubmission,
)


def scope(workspace_id: str = "workspace-1") -> TaskScope:
    return TaskScope(
        principal_id="principal-1",
        workspace_id=workspace_id,
        app_id=APP_ID,
    )


def submission(directory: Path) -> TaskSubmission:
    action = list_directory_action_descriptor()
    task_scope = scope()
    now = time.time()
    return TaskSubmission(
        handle=TaskHandle(
            task_id="task-1",
            submission_id="submission-1",
            scope=task_scope,
            action_id=action.action_id,
            descriptor_digest=action.descriptor_digest,
            origin=TaskOrigin(
                engagement="direct",
                origin_ref="chat-1",
                app_session_ref=f"pawapp:{APP_ID}",
            ),
            created_at=now,
            updated_at=now,
        ),
        action=action,
        inputs={"directory": str(directory.resolve())},
    )


def test_render_directory_is_bounded_and_does_not_follow_symlinks(tmp_path):
    (tmp_path / "folder").mkdir()
    (tmp_path / "alpha.txt").write_text("alpha")
    outside = tmp_path.parent / "outside-file-browser-test.txt"
    outside.write_text("secret")
    link = tmp_path / "outside-link"
    try:
        link.symlink_to(outside)
    except OSError:
        pytest.skip("symlinks are unavailable on this platform")

    payload = json.loads(render_directory(str(tmp_path)))

    assert payload["directory"] == str(tmp_path.resolve())
    assert payload["limit"] == 200
    assert [item["name"] for item in payload["entries"]] == [
        "folder",
        "alpha.txt",
        "outside-link",
    ]
    assert payload["entries"][2]["type"] == "symlink"
    assert "secret" not in json.dumps(payload)


def test_render_directory_stops_at_the_declared_limit(tmp_path):
    for index in range(205):
        (tmp_path / f"item-{index:03}.txt").touch()

    payload = json.loads(render_directory(str(tmp_path)))

    assert len(payload["entries"]) == 200
    assert payload["truncated"] is True


def test_preferences_are_scoped_and_compare_and_swap(tmp_path):
    store = FileBrowserStore(tmp_path / "state.sqlite3")
    first = store.save_preference(
        scope(),
        str(tmp_path),
        expected_revision=0,
    )

    assert first.directory == str(tmp_path.resolve())
    assert first.revision == 1
    assert store.preference(scope()).revision == 1
    assert store.preference(scope("workspace-2")).directory is None
    with pytest.raises(TaskStoreError, match="context_conflict"):
        store.save_preference(
            scope(),
            str(tmp_path),
            expected_revision=0,
        )


@pytest.mark.asyncio
async def test_default_setup_is_conditional_and_resolves_canonical_path(
    tmp_path,
):
    store = FileBrowserStore(tmp_path / "state.sqlite3")
    checker = make_setup_checker(store)
    resolver = make_input_resolver(store)

    missing = await checker(scope(), {})
    explicit = await checker(scope(), {"directory": str(tmp_path)})
    assert missing.state == "needs_configuration"
    assert missing.reason_code == "file_browser_default_root_missing"
    assert explicit.state == "ready"

    saved = store.save_preference(
        scope(),
        str(tmp_path),
        expected_revision=0,
    )
    resolved = await resolver(scope(), {})
    assert saved.revision == 1
    assert resolved == {"directory": str(tmp_path.resolve())}


@pytest.mark.asyncio
async def test_adapter_replays_the_exact_persisted_listing(tmp_path):
    listed = tmp_path / "listed"
    listed.mkdir()
    (listed / "before.txt").write_text("before")
    store = FileBrowserStore(tmp_path / "state.sqlite3")
    adapter = FileBrowserTaskAdapter(store)
    task = submission(listed)

    run_ref = await adapter.submit(task)
    (listed / "after.txt").write_text("after")
    replay_ref = await adapter.submit(task)
    lookup = await adapter.query(task)
    events = [event async for event in adapter.attach(task)]

    assert replay_ref == run_ref
    assert lookup.state == "accepted"
    assert lookup.run_ref == run_ref
    assert len(events) == 1
    assert events[0].status == "succeeded"
    payload = json.loads(events[0].text_result)
    assert [item["name"] for item in payload["entries"]] == ["before.txt"]


def test_relative_and_unavailable_preferences_are_rejected(tmp_path):
    store = FileBrowserStore(tmp_path / "state.sqlite3")
    with pytest.raises(
        TaskStoreError,
        match="file_browser_directory_not_absolute",
    ):
        store.save_preference(scope(), "relative", expected_revision=0)
    with pytest.raises(
        TaskStoreError,
        match="file_browser_default_root_unavailable",
    ):
        store.save_preference(
            scope(),
            str(tmp_path / "missing"),
            expected_revision=0,
        )


def test_database_permissions_are_private(tmp_path):
    database = tmp_path / "private" / "state.sqlite3"
    FileBrowserStore(database)
    if os.name != "nt":
        assert database.stat().st_mode & 0o777 == 0o600
        assert database.parent.stat().st_mode & 0o777 == 0o700


def test_manifest_and_backend_registrations_match(tmp_path, monkeypatch):
    plugin_dir = BACKEND_DIR.parent
    manifest = json.loads((plugin_dir / "plugin.json").read_text())
    monkeypatch.setenv("QWENPAW_FILE_BROWSER_STATE_DIR", str(tmp_path))
    spec = importlib.util.spec_from_file_location(
        "qwenpaw_file_browser_test_main",
        BACKEND_DIR / "main.py",
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    api = MagicMock()
    api.manifest = manifest

    module.app.register(api)

    registration = api.register_task_action.call_args.args[0]
    assert registration.action.action_id == "list-directory"
    assert registration.action.engagements == ("delegated", "direct")
    assert registration.requirement_ids == ("default-root",)
    assert registration.input_resolver is not None
    api.register_pawapp_setup_entry.assert_called_once()
    api.register_pawapp_setup_check.assert_called_once()


@pytest.mark.asyncio
async def test_preference_api_uses_workspace_scope_and_completes_setup(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setenv("QWENPAW_FILE_BROWSER_STATE_DIR", str(tmp_path))
    spec = importlib.util.spec_from_file_location(
        "qwenpaw_file_browser_test_routes",
        BACKEND_DIR / "main.py",
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    task_scope = scope()
    setup_request = SimpleNamespace(
        request=SimpleNamespace(
            entry_id="file-browser-default-root",
            requirement_ids=("default-root",),
        ),
    )
    coordinator = SimpleNamespace(
        backend_request=AsyncMock(return_value=(task_scope, setup_request)),
        complete=AsyncMock(),
    )
    web = FastAPI()

    @web.middleware("http")
    async def authenticate(request: Request, call_next):
        request.state.user = "principal-1"
        return await call_next(request)

    web.include_router(module.router, prefix=f"/api/{APP_ID}")
    web.state.pawapp_setup = coordinator
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=web),
        base_url="http://host",
    ) as client:
        missing_scope = await client.get(
            f"/api/{APP_ID}/preferences/directory",
        )
        assert missing_scope.status_code == 400
        saved = await client.put(
            f"/api/{APP_ID}/preferences/directory",
            headers={"X-Agent-Id": "workspace-1"},
            json={
                "directory": str(tmp_path),
                "expected_revision": 0,
                "setup_request_id": "setup-1",
            },
        )
        assert saved.status_code == 200, saved.text
        assert saved.json()["directory"] == str(tmp_path.resolve())
        assert saved.json()["revision"] == 1
        replayed = await client.put(
            f"/api/{APP_ID}/preferences/directory",
            headers={"X-Agent-Id": "workspace-1"},
            json={
                "directory": str(tmp_path),
                "expected_revision": 0,
                "setup_request_id": "setup-1",
            },
        )
        assert replayed.status_code == 200
        assert replayed.json()["revision"] == 1
        other = tmp_path / "other"
        other.mkdir()
        conflict = await client.put(
            f"/api/{APP_ID}/preferences/directory",
            headers={"X-Agent-Id": "workspace-1"},
            json={
                "directory": str(other),
                "expected_revision": 1,
                "setup_request_id": "setup-1",
            },
        )
        assert conflict.status_code == 409
        assert conflict.json()["detail"] == "setup_result_conflict"
        conflicting = await client.get(
            f"/api/{APP_ID}/preferences/directory?agent_id=other",
            headers={"X-Agent-Id": "workspace-1"},
        )
        assert conflicting.status_code == 403

    assert coordinator.backend_request.await_count == 3
    assert coordinator.backend_request.await_args_list[0].args == (
        "principal-1",
        APP_ID,
        "setup-1",
    )
    assert coordinator.complete.await_count == 2
    completed_scope, result = coordinator.complete.await_args_list[0].args
    assert completed_scope == task_scope
    assert result.outcome == "saved"
    assert result.changed_requirement_ids == ("default-root",)
    assert coordinator.complete.await_args_list[1].args[1] == result
