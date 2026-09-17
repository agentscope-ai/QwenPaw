# -*- coding: utf-8 -*-
"""Task 13.2 API、SSE、错误、日志和前端存储泄露矩阵。"""

from __future__ import annotations

from pathlib import Path
import json
from types import SimpleNamespace
from uuid import UUID

import pytest
from starlette.requests import Request

from qwenpaw.access.actor import ActorContext, ActorType
from qwenpaw.app.routers import backup, console
from qwenpaw.app.routers import project_directory
from qwenpaw.app.chats.query_error_dump import write_query_error_dump
from qwenpaw.backup.models import CreateBackupRequest
from qwenpaw.identity.models import PlatformRole
from qwenpaw.platform_ops.log_redaction import REDACTED, redact_log_text


USER_ID = UUID("11111111-1111-4111-8111-111111111111")
SECRET = "sk-proj-task132-secret-value"
PRIVATE_PATH = "C:/Users/private/QwenPaw/secret.txt"


def _request() -> Request:
    request = Request({"type": "http", "headers": []})
    request.state.actor = ActorContext(
        user_id=USER_ID,
        actor_type=ActorType.USER,
        platform_role=PlatformRole.MEMBER,
        admin_mode=False,
        request_id="task-13-2-secret",
    )
    return request


def test_log_redaction_removes_secret_path_and_user_identifier() -> None:
    raw = (
        f"Authorization: Bearer {SECRET} path={PRIVATE_PATH} "
        f"owner_user_id={USER_ID}"
    )

    redacted = redact_log_text(raw, secret_values=[SECRET])

    assert REDACTED in redacted
    assert SECRET not in redacted
    assert PRIVATE_PATH not in redacted
    assert str(USER_ID) not in redacted


def test_query_error_dump_redacts_nested_credentials_and_private_paths(
    monkeypatch, tmp_path
) -> None:
    import qwenpaw.app.chats.query_error_dump as dump_module

    monkeypatch.setattr(dump_module.tempfile, "gettempdir", lambda: str(tmp_path))
    request = SimpleNamespace(
        session_id="session-a",
        user_id=str(USER_ID),
        channel="console",
        request_context={"api_key": SECRET, "path": PRIVATE_PATH},
    )

    path = write_query_error_dump(
        request,
        RuntimeError(f"token={SECRET} at {PRIVATE_PATH}"),
        {"agent": SimpleNamespace(state_dict=lambda: {"password": SECRET})},
    )

    assert path is not None
    serialized = Path(path).read_text(encoding="utf-8")
    payload = json.loads(serialized)
    assert SECRET not in serialized
    assert PRIVATE_PATH not in serialized
    assert payload["request"]["request_context"]["api_key"] == REDACTED
    assert payload["agent_state"]["password"] == REDACTED


@pytest.mark.asyncio
async def test_backup_sse_does_not_echo_internal_exception(monkeypatch) -> None:
    async def failing_stream(_request):
        raise RuntimeError(f"token={SECRET} path={PRIVATE_PATH}")
        yield  # pragma: no cover

    monkeypatch.setattr(backup, "create_stream", failing_stream)
    response = await backup.create_backup_stream(CreateBackupRequest(name="safe"))
    chunks = [chunk async for chunk in response.body_iterator]
    body = "".join(chunk.decode() if isinstance(chunk, bytes) else chunk for chunk in chunks)

    assert "backup_creation_failed" in body
    assert SECRET not in body
    assert PRIVATE_PATH not in body


@pytest.mark.asyncio
async def test_project_clone_sse_redacts_subprocess_output(monkeypatch, tmp_path) -> None:
    class Output:
        async def read(self, _size):
            if getattr(self, "read_once", False):
                return b""
            self.read_once = True
            return f"Authorization: Bearer {SECRET} {PRIVATE_PATH}\n".encode()

    class Process:
        stdout = Output()

        async def wait(self):
            return 1

    async def workspace(*_args, **_kwargs):
        return SimpleNamespace(workspace_dir=tmp_path, agent_id="agent-a")

    monkeypatch.setattr(project_directory, "get_running_config_workspace", workspace)
    monkeypatch.setattr(project_directory, "require_running_config_editor", lambda _r: None)
    monkeypatch.setattr(
        project_directory,
        "start_command_async",
        lambda *_args, **_kwargs: _async(Process()),
    )
    response = await project_directory.clone_project(
        project_directory.CloneProjectRequest(url="https://example.test/repo.git"),
        _request(),
    )
    chunks = [chunk async for chunk in response.body_iterator]
    body = "".join(chunk.decode() if isinstance(chunk, bytes) else chunk for chunk in chunks)

    assert REDACTED in body
    assert SECRET not in body
    assert PRIVATE_PATH not in body


@pytest.mark.asyncio
async def test_background_task_error_is_fixed_and_owner_scoped(monkeypatch, tmp_path) -> None:
    class Channel:
        def resolve_session_id(self, **kwargs):
            return kwargs["channel_meta"]["session_id"]

        async def stream_one(self, _payload):
            raise RuntimeError(f"api_key={SECRET} at {PRIVATE_PATH}")
            yield  # pragma: no cover

    conversation_id = "44444444-4444-4444-8444-444444444444"

    class ChatManager:
        conversation_repository = None

        async def get_or_create_chat(self, *_args, **_kwargs):
            return SimpleNamespace(id=conversation_id, meta={})

    workspace = SimpleNamespace(
        agent_id="agent-a",
        workspace_dir=tmp_path,
        channel_manager=SimpleNamespace(get_channel=lambda _name: _async(Channel())),
        chat_manager=ChatManager(),
    )
    monkeypatch.setattr(console, "is_multi_user_enabled", lambda: True)
    monkeypatch.setattr(console, "get_agent_for_request", lambda _request: _async(workspace))
    monkeypatch.setattr(
        "qwenpaw.config.config.load_agent_config",
        lambda _agent_id: SimpleNamespace(project_dir=None),
    )
    monkeypatch.setattr(
        "qwenpaw.models.runtime.prepare_console_model",
        lambda *_args: _async(None),
    )

    submitted = await console.post_console_chat_task(
        {
            "channel": "console",
            "user_id": "forged",
            "session_id": "session-a",
            "input": [],
        },
        _request(),
    )
    task_id = submitted["task_id"]
    try:
        await console._bg_tasks[task_id].asyncio_task
        result = await console.get_console_chat_task(task_id, _request())
        serialized = str(result)
        assert result["result"]["error"]["message"] == "task_execution_failed"
        assert SECRET not in serialized
        assert PRIVATE_PATH not in serialized
    finally:
        console._bg_tasks.pop(task_id, None)


def test_multi_user_access_token_and_file_contents_are_not_persisted() -> None:
    project_root = Path(__file__).resolve().parents[2]
    config_source = (project_root / "console/src/api/config.ts").read_text(encoding="utf-8")
    cache_source = (project_root / "console/src/stores/codeFileCacheStore.ts").read_text(
        encoding="utf-8"
    )

    set_token_function = config_source.split(
        "export function setAuthToken", 1
    )[1].split("export function clearAuthToken", 1)[0]
    multi_user_branch = set_token_function.split(
        'if (authMode === "multi_user") {', 1
    )[1].split("}", 1)[0]
    assert "memoryAuthToken = token" in multi_user_branch
    assert "localStorage.setItem" not in multi_user_branch
    assert "localStorage.setItem" not in cache_source
    assert "sessionStorage.setItem" not in cache_source


async def _async(value):
    return value
