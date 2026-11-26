# -*- coding: utf-8 -*-
"""Tests for the Antigravity CLI (ACP) Harness plugin."""

# pylint: disable=protected-access,too-many-lines

from __future__ import annotations

import asyncio
import base64
import json
import os
import stat
import sys
import time
import zipfile
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import acp
import pytest
from acp import (
    PROTOCOL_VERSION,
    RequestError,
    start_tool_call,
    tool_content,
    tool_diff_content,
    update_agent_message_text,
    update_agent_thought_text,
    update_tool_call,
    update_user_message_text,
)
from acp.schema import (
    AgentCapabilities,
    InitializeResponse,
    McpCapabilities,
    ModelInfo,
    NewSessionResponse,
    PermissionOption,
    PromptResponse,
    ResumeSessionResponse,
    SessionConfigOptionSelect,
    SessionConfigSelectOption,
    SessionModelState,
    SetSessionConfigOptionResponse,
    ToolCallUpdate,
)
from pydantic import SecretStr

from plugins.harness.agy import adapter as agy_adapter
from plugins.harness.agy.adapter import (
    BYPASS_PERMISSIONS,
    AgyBackend,
    _clean_agy_env,
)
from plugins.harness.agy.auth_fingerprint import (
    _parse_credential_fingerprint,
    async_agy_auth_fingerprint,
    read_active_agy_auth_fingerprint,
    reset_auth_fingerprint_cache,
)
from plugins.harness.agy.discovery import resolve_agy_binary_info
from plugins.harness.agy.event_mapper import AgyEventMapper
from plugins.harness.agy.projection import mcp_servers
from qwenpaw.plugins import SDKError
from qwenpaw.plugins.compliance import check_plugin
from qwenpaw.plugins.harnesses import (
    HarnessAttachment,
    HarnessAttachmentKind,
    HarnessCallContext,
    HarnessContext,
    HarnessEventKind,
    HarnessMCPServerDefinition,
    HarnessOperationNotSupportedError,
    HarnessRunRequest,
    HarnessRuntimeCapabilities,
)
from qwenpaw.plugins.resources import ResourceOwner, ResourceScope
from qwenpaw.plugins.storage import PluginStorage
from qwenpaw.plugins.testing import PluginTestHost

_MODELS = {
    "gemini-4-carbon": ["low", "medium", "high"],
    "gemini-4-hydrogen": ["low", "medium", "high", "xhigh"],
    "gemini-pro-orchestrator": [],
}
_MODES = ["default", "accept-edits", "auto", "plan"]
_PNG_HEADER = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16


def _make_executable(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    if os.name != "nt":
        path.chmod(path.stat().st_mode | stat.S_IXUSR)
    return path


def _select(option_id: str, current: str, values: list[str]) -> Any:
    return SessionConfigOptionSelect(
        id=option_id,
        name=option_id,
        type="select",
        current_value=current,
        options=[
            SessionConfigSelectOption(value=value, name=value.title())
            for value in values
        ],
    )


class _FakeProcess:
    def __init__(self) -> None:
        self.returncode: int | None = None
        self.closed = False


class FakeServer:
    """In-memory ACP server double standing in for ``agy acp``."""

    def __init__(self) -> None:
        self.logged_in = True
        self.protocol_version = PROTOCOL_VERSION
        self.mcp_http = True
        self.mcp_sse = True
        self.tier_name = "Pro"
        self.spawned: list[dict[str, Any]] = []
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.sessions: dict[str, dict[str, str]] = {}
        self.known: set[str] = set()
        self.script: list[Any] = [update_agent_message_text("Done")]
        self.scripts: list[list[Any]] = []
        self.stop_reason = "end_turn"
        self.stop_reasons: list[str] = []
        self.prompt_error: Exception | None = None
        self.hold_prompt: asyncio.Event | None = None
        self.permissions: list[Any] = []
        self.permission_requests: list[tuple[list[Any], Any]] = []
        self.processes: list[_FakeProcess] = []
        self.prompt_count = 0
        self.clients: list[Any] = []

    def spawn(
        self,
        client: Any,
        command: str,
        *args: str,
        **kwargs: Any,
    ):
        server = self
        server.clients.append(client)

        class _Conn:
            def __init__(self) -> None:
                self._conn = SimpleNamespace(
                    _disconnected=False,
                    _closed=False,
                )

            async def initialize(self, **params: Any) -> Any:
                server.calls.append(("initialize", params))
                return InitializeResponse(
                    protocol_version=server.protocol_version,
                    agent_capabilities=AgentCapabilities(
                        mcp_capabilities=McpCapabilities(
                            http=server.mcp_http,
                            sse=server.mcp_sse,
                        ),
                    ),
                )

            def _config_options(self, state: dict[str, str]) -> list[Any]:
                options = [
                    _select("model", state["model"], list(_MODELS)),
                    _select("mode", state["mode"], _MODES),
                ]
                efforts = _MODELS.get(state["model"]) or []
                if efforts:
                    current_effort = (
                        state["thought_level"]
                        if state["thought_level"] in efforts
                        else efforts[0]
                    )
                    options.append(
                        _select("thought_level", current_effort, efforts),
                    )
                return options

            def _models_state(self, current: str) -> SessionModelState:
                available = []
                for base, efforts in _MODELS.items():
                    if efforts:
                        for effort in efforts:
                            available.append(
                                ModelInfo(
                                    model_id=f"{base}-{effort}",
                                    name=f"{base} ({effort})",
                                ),
                            )
                    else:
                        available.append(
                            ModelInfo(model_id=base, name=base),
                        )
                return SessionModelState(
                    available_models=available,
                    current_model_id=current,
                )

            async def new_session(self, **params: Any) -> Any:
                server.calls.append(("new_session", params))
                if not server.logged_in:
                    raise RequestError(-32000, "Authentication required")
                acp_id = f"acp-{len(server.known) + 1}"
                server.known.add(acp_id)
                state = {
                    "model": "gemini-4-carbon",
                    "thought_level": "medium",
                    "mode": "default",
                }
                server.sessions[acp_id] = state
                meta = (
                    {"antigravity": {"tier": {"name": server.tier_name}}}
                    if server.tier_name
                    else {}
                )
                return NewSessionResponse(
                    session_id=acp_id,
                    config_options=self._config_options(state),
                    models=self._models_state("gemini-4-carbon-medium"),
                    field_meta=meta,
                )

            async def resume_session(self, **params: Any) -> Any:
                server.calls.append(("resume_session", params))
                if not server.logged_in:
                    raise RequestError(-32000, "Authentication required")
                acp_id = str(params["session_id"])
                if acp_id not in server.known:
                    raise RequestError(-32602, f"Unknown session: {acp_id}")
                state = server.sessions.setdefault(
                    acp_id,
                    {
                        "model": "gemini-4-carbon",
                        "thought_level": "medium",
                        "mode": "default",
                    },
                )
                return ResumeSessionResponse(
                    config_options=self._config_options(state),
                    models=self._models_state("gemini-4-carbon-medium"),
                )

            async def close_session(self, **params: Any) -> None:
                server.calls.append(("close_session", params))

            async def set_config_option(self, **params: Any) -> Any:
                server.calls.append(("set_config_option", params))
                acp_id = str(params["session_id"])
                state = server.sessions[acp_id]
                state[str(params["config_id"])] = str(params["value"])
                return SetSessionConfigOptionResponse(
                    config_options=self._config_options(state),
                )

            async def prompt(self, **params: Any) -> Any:
                server.calls.append(("prompt", params))
                server.prompt_count += 1
                acp_id = str(params["session_id"])
                if server.prompt_error is not None:
                    raise server.prompt_error
                if server.permission_requests:
                    options, tool_call = server.permission_requests.pop(0)
                    response = await client.request_permission(
                        options=options,
                        session_id=acp_id,
                        tool_call=tool_call,
                    )
                    server.permissions.append(response)
                updates = (
                    server.scripts.pop(0)
                    if server.scripts
                    else list(server.script)
                )
                for update in updates:
                    await client.session_update(acp_id, update)
                if server.hold_prompt is not None:
                    await server.hold_prompt.wait()
                reason = (
                    server.stop_reasons.pop(0)
                    if server.stop_reasons
                    else server.stop_reason
                )
                return PromptResponse(stop_reason=reason)

            async def cancel(self, **params: Any) -> None:
                server.calls.append(("cancel", params))
                if server.hold_prompt is not None:
                    server.hold_prompt.set()

        @asynccontextmanager
        async def _cm():
            proc = _FakeProcess()
            conn = _Conn()
            server.processes.append(proc)
            server.spawned.append(
                {
                    "command": command,
                    "args": args,
                    "cwd": kwargs.get("cwd"),
                    "env": kwargs.get("env"),
                },
            )
            try:
                yield conn, proc
            finally:
                proc.returncode = 0
                proc.closed = True
                conn._conn._closed = True

        return _cm()


class _Runtime:
    def __init__(self, tmp_path: Path) -> None:
        self.tmp_path = tmp_path
        self.workspace = tmp_path / "workspace"
        self.workspace.mkdir(parents=True, exist_ok=True)
        self.state_dir = self.workspace / "plugin-data" / "qwenpaw-harness-agy"
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.binary = _make_executable(
            tmp_path / "bin" / ("agy.exe" if os.name == "nt" else "agy"),
        )
        self.server = FakeServer()
        self.backends: list[AgyBackend] = []
        self.scopes: list[ResourceScope] = []

    def context(self) -> HarnessContext:
        owner = ResourceOwner("qwenpaw-harness-agy", 1, "workspace")
        scope = ResourceScope(owner, lambda: None)
        self.scopes.append(scope)
        storage = PluginStorage(self.state_dir, lambda: None)
        return HarnessContext(
            plugin_id="qwenpaw-harness-agy",
            generation=1,
            workspace_id="default",
            workspace_dir=self.workspace,
            state_dir=self.state_dir,
            storage=storage,
            resources=scope,
            logger=SimpleNamespace(
                debug=lambda *_a, **_k: None,
                info=lambda *_a, **_k: None,
                warning=lambda *_a, **_k: None,
                error=lambda *_a, **_k: None,
            ),
        )

    def backend(
        self,
        *,
        binary: str | None = ...,  # type: ignore[assignment]
        auth_fingerprint: Any = None,
        max_idle_isolated_servers: int | None = None,
        idle_isolated_server_ttl: float | None = None,
    ) -> AgyBackend:
        resolved_binary = str(self.binary) if binary is ... else binary
        instance = AgyBackend(
            self.context(),
            binary=resolved_binary,
            spawn=self.server.spawn,
            auth_fingerprint=auth_fingerprint,
            max_idle_isolated_servers=max_idle_isolated_servers,
            idle_isolated_server_ttl=idle_isolated_server_ttl,
        )
        self.backends.append(instance)
        return instance

    def call(
        self,
        session_id: str = "chat-1",
        *,
        user_id: str = "alice",
        channel: str = "console",
        cwd: Path | None = None,
        settings: dict[str, Any] | None = None,
        capabilities: HarnessRuntimeCapabilities | None = None,
        request_approval: Any = None,
    ) -> HarnessCallContext:
        owner = ResourceOwner("qwenpaw-harness-agy", 1, "call")
        scope = ResourceScope(owner, lambda: None)
        self.scopes.append(scope)
        return HarnessCallContext(
            request_id=f"req-{session_id}",
            session_id=session_id,
            user_id=user_id,
            channel=channel,
            cwd=cwd or self.workspace,
            settings=dict(settings or {}),
            runtime_capabilities=capabilities,
            resources=scope,
            _request_approval=request_approval,
        )

    async def cleanup(self) -> None:
        for backend in self.backends:
            await backend.close()
        for scope in self.scopes:
            await scope.close()


@pytest.fixture(name="runtime")
async def make_runtime(tmp_path: Path):
    rt = _Runtime(tmp_path)
    try:
        yield rt
    finally:
        await rt.cleanup()


async def _collect(
    backend: AgyBackend,
    call: HarnessCallContext,
    prompt: str = "Hello",
    attachments: tuple[HarnessAttachment, ...] = (),
) -> list[Any]:
    return [
        event
        async for event in backend.run_turn(
            call,
            HarnessRunRequest(prompt, attachments),
        )
    ]


# ------------------------------------------------------------------
# Discovery, environment, fingerprinting, mapper, projection
# ------------------------------------------------------------------


def test_discovery_precedence_and_strict_configured_path(tmp_path: Path):
    bin_dir = tmp_path / "path_bin"
    home_dir = tmp_path / "home"
    name = "agy.exe" if os.name == "nt" else "agy"
    in_path = _make_executable(bin_dir / name)
    in_local = _make_executable(home_dir / ".local" / "bin" / name)
    explicit = _make_executable(tmp_path / "custom" / name)

    res = resolve_agy_binary_info(
        str(explicit),
        environ={"PATH": str(bin_dir)},
        user_home=home_dir,
    )
    assert res is not None
    assert res.path == explicit.resolve()
    assert res.source == "configured"

    # A broken configured path must not silently fall back to PATH.
    assert (
        resolve_agy_binary_info(
            str(tmp_path / "does-not-exist"),
            environ={"PATH": str(bin_dir)},
            user_home=home_dir,
        )
        is None
    )

    res_path = resolve_agy_binary_info(
        None,
        environ={"PATH": str(bin_dir)},
        user_home=home_dir,
    )
    assert res_path is not None
    assert res_path.path == in_path.resolve()
    assert res_path.source == "path"

    res_local = resolve_agy_binary_info(
        None,
        environ={"PATH": ""},
        user_home=home_dir,
    )
    assert res_local is not None
    assert res_local.path == in_local.resolve()
    assert res_local.source == "local-bin"


def test_clean_agy_env_strips_ipc_vars_but_preserves_app_data_dir():
    cleaned = _clean_agy_env(
        {
            "PATH": "/usr/bin",
            "ANTIGRAVITY_LS_ADDRESS": "127.0.0.1:1234",
            "ANTIGRAVITY_CSRF_TOKEN": "secret",
            "ANTIGRAVITY_AGENT": "1",
            "ANTIGRAVITY_APP_DATA_DIR": "/custom/agy",
        },
    )
    assert cleaned == {
        "PATH": "/usr/bin",
        "ANTIGRAVITY_APP_DATA_DIR": "/custom/agy",
    }


def test_auth_fingerprint_parses_credentials_and_ssh_token_file(
    tmp_path: Path,
):
    reset_auth_fingerprint_cache()
    payload = json.dumps(
        {
            "auth_method": "oauth",
            "id_token_email": "User@Example.com",
            "token": {
                "access_token": "ephemeral-1",
                "refresh_token": "stable-refresh",
            },
        },
    )
    fp1 = _parse_credential_fingerprint(payload)
    # Short-lived access token rotation keeps the same fingerprint.
    payload_rotated = json.dumps(
        {
            "auth_method": "oauth",
            "id_token_email": "user@example.com",
            "token": {
                "access_token": "ephemeral-2",
                "refresh_token": "stable-refresh",
            },
        },
    )
    fp2 = _parse_credential_fingerprint(payload_rotated)
    assert fp1.startswith("agy:") and fp1 == fp2

    encoded = "go-keyring-base64:" + base64.b64encode(
        payload.encode("utf-8"),
    ).decode("ascii")
    assert _parse_credential_fingerprint(encoded) == fp1

    token_dir = tmp_path / "agy-data"
    token_dir.mkdir()
    token_file = token_dir / "antigravity-oauth-token"
    assert (
        read_active_agy_auth_fingerprint(
            {
                "SSH_CONNECTION": "1.2.3.4 22 5.6.7.8 22",
                "ANTIGRAVITY_APP_DATA_DIR": str(token_dir),
            },
        )
        == "logged-out"
    )
    token_file.write_text(payload, encoding="utf-8")
    assert (
        read_active_agy_auth_fingerprint(
            {
                "SSH_CONNECTION": "1.2.3.4 22 5.6.7.8 22",
                "ANTIGRAVITY_APP_DATA_DIR": str(token_dir),
            },
        )
        == fp1
    )
    # Fail-open when ADC auth is explicitly enabled.
    assert read_active_agy_auth_fingerprint({"AGY_ADC_AUTH": "true"}) == ""


async def test_async_auth_fingerprint_uses_injected_reader():
    assert await async_agy_auth_fingerprint(lambda: "agy:deadbeef") == (
        "agy:deadbeef"
    )


def test_event_mapper_translates_text_thought_plan_tools_and_close():
    mapper = AgyEventMapper()
    mapper.begin_prompt()

    # Delayed background text before echoed user message gets separated.
    e1 = mapper.convert(update_agent_message_text("Background done."))
    e2 = mapper.convert(update_user_message_text("Next question"))
    e3 = mapper.convert(update_agent_thought_text("Thinking..."))
    e4 = mapper.convert(
        {
            "session_update": "plan",
            "entries": [
                {"content": "Step 1", "status": "completed"},
                {"content": "Step 2", "status": "in_progress"},
            ],
        },
    )
    assert [e.text for e in e1] == ["Background done."]
    assert [e.text for e in e2] == ["\n\n"]
    assert [e.kind for e in e3] == [HarnessEventKind.REASONING_DELTA]
    assert "- [x] Step 1\n- [~] Step 2\n" in e4[0].text

    start = mapper.convert(
        start_tool_call(
            "call-1",
            "Run read_file",
            kind="other",
            status="in_progress",
            raw_input={"path": "a.py"},
        ),
    )
    assert start[0].kind == HarnessEventKind.TOOL_STARTED
    assert start[0].tool_name == "read_file"
    assert mapper.unfinished() == ["call-1"]

    diff_update = mapper.convert(
        update_tool_call(
            "call-1",
            status="completed",
            content=[
                tool_diff_content("a.py", new_text="new\n", old_text="old\n"),
            ],
        ),
    )
    assert diff_update[0].kind == HarnessEventKind.TOOL_COMPLETED
    assert "-old" in diff_update[0].text and "+new" in diff_update[0].text
    assert mapper.unfinished() == []

    # Open tool calls are forcibly closed with interrupted metadata.
    mapper.convert(
        start_tool_call(
            "call-2",
            "bash",
            kind="execute",
            status="in_progress",
        ),
    )
    mapper.convert(
        update_tool_call(
            "call-2",
            content=[tool_content({"type": "text", "text": "partial"})],
        ),
    )
    closed = mapper.close()
    assert len(closed) == 1
    assert closed[0].item_id == "call-2"
    assert closed[0].text == "partial"
    assert closed[0].data == {"is_error": True, "interrupted": True}


def test_mcp_projection_respects_policies_transports_and_cwd(tmp_path: Path):
    caps = HarnessRuntimeCapabilities(
        mcp_servers=(
            HarnessMCPServerDefinition(
                name="denied",
                display_name="Denied",
                transport="stdio",
                command="echo",
                default_policy="deny",
                tools=None,
            ),
            HarnessMCPServerDefinition(
                name="local-cwd",
                display_name="Local CWD",
                transport="stdio",
                command="my-mcp",
                args=("--flag",),
                cwd=tmp_path,
                env={"API_KEY": SecretStr("secret-value")},
            ),
            HarnessMCPServerDefinition(
                name="http-srv",
                display_name="HTTP",
                transport="streamable_http",
                url="https://example.test/mcp",
                headers={"Authorization": SecretStr("Bearer tok")},
            ),
            HarnessMCPServerDefinition(
                name="sse-srv",
                display_name="SSE",
                transport="sse",
                url="https://example.test/sse",
            ),
        ),
    )
    all_servers = mcp_servers(caps, allow_http=True, allow_sse=True)
    assert [s.name for s in all_servers] == [
        "local-cwd",
        "http-srv",
        "sse-srv",
    ]
    assert all_servers[0].command == sys.executable
    assert str(tmp_path) in all_servers[0].args
    assert all_servers[0].env[0].value == "secret-value"
    assert all_servers[1].headers[0].value == "Bearer tok"

    stdio_only = mcp_servers(caps, allow_http=False, allow_sse=False)
    assert [s.name for s in stdio_only] == ["local-cwd"]


# ------------------------------------------------------------------
# Backend status, login, models, turns, approvals, sessions
# ------------------------------------------------------------------


async def test_status_login_logout_models_and_unsupported_ops(
    runtime: _Runtime,
):
    missing = runtime.backend(binary=str(runtime.tmp_path / "missing-agy"))
    status_missing = await missing.status(runtime.call())
    assert not status_missing.installed
    assert status_missing.error

    backend = runtime.backend()
    runtime.server.logged_in = False
    status_logged_out = await backend.status(runtime.call())
    assert status_logged_out.installed
    assert not status_logged_out.authenticated
    assert status_logged_out.error is None
    # Probe-only process was closed immediately after probing.
    assert runtime.server.processes[-1].closed

    login = await backend.start_login(runtime.call())
    assert login.data["type"] == "external"
    assert "acp --login" in login.data["command"]

    runtime.server.logged_in = True
    status_ok = await backend.status(runtime.call())
    assert status_ok.authenticated
    assert status_ok.account == {"type": "google", "plan": "Pro"}

    models = await backend.models(runtime.call())
    by_id = {model.id: model for model in models}
    assert by_id["gemini-4-carbon"].is_default
    assert by_id["gemini-4-carbon"].reasoning_efforts == (
        "low",
        "medium",
        "high",
    )
    assert by_id["gemini-pro-orchestrator"].reasoning_efforts == ()

    assert await backend.history(runtime.call()) == ()
    with pytest.raises(HarnessOperationNotSupportedError):
        await backend.logout(runtime.call())
    with pytest.raises(HarnessOperationNotSupportedError):
        await backend.discover_skills(runtime.call())
    with pytest.raises(HarnessOperationNotSupportedError):
        await backend.discover_mcp(runtime.call())


async def test_run_turn_resumes_isolates_and_migrates_legacy_sessions(
    runtime: _Runtime,
):
    # Pre-populate legacy workspace session file.
    legacy = runtime.workspace / "harnesses" / "agy_sessions.json"
    legacy.parent.mkdir(parents=True, exist_ok=True)
    legacy.write_text(
        json.dumps({"legacy-chat": "acp-legacy"}),
        encoding="utf-8",
    )
    runtime.server.known.add("acp-legacy")

    backend = runtime.backend()
    events = await _collect(backend, runtime.call("legacy-chat"), "Continue")
    assert events[-1].kind == HarnessEventKind.COMPLETED
    assert any(
        name == "resume_session" and params["session_id"] == "acp-legacy"
        for name, params in runtime.server.calls
    )
    # Legacy file untouched; plugin storage now holds the scoped key.
    assert json.loads(legacy.read_text(encoding="utf-8")) == {
        "legacy-chat": "acp-legacy",
    }
    stored = json.loads(
        (runtime.state_dir / "agy_sessions.json").read_text(encoding="utf-8"),
    )
    assert stored[json.dumps(["alice", "console", "legacy-chat"])] == (
        "acp-legacy"
    )

    # Another user with the same session_id gets an independent ACP session.
    await _collect(
        backend,
        runtime.call("legacy-chat", user_id="bob"),
        "Separate user",
    )
    stored = json.loads(
        (runtime.state_dir / "agy_sessions.json").read_text(encoding="utf-8"),
    )
    assert (
        stored[json.dumps(["bob", "console", "legacy-chat"])] != "acp-legacy"
    )


async def test_settings_compound_model_effort_and_permission_mode(
    runtime: _Runtime,
):
    backend = runtime.backend()
    call = runtime.call(
        settings={
            "model": "gemini-4-hydrogen-xhigh",
            "permission_mode": "accept-edits",
        },
    )
    events = await _collect(backend, call, "Apply settings")
    assert events[-1].kind == HarnessEventKind.COMPLETED
    config_calls = [
        (params["config_id"], params["value"])
        for name, params in runtime.server.calls
        if name == "set_config_option"
    ]
    assert ("model", "gemini-4-hydrogen") in config_calls
    assert ("thought_level", "xhigh") in config_calls
    assert ("mode", "accept-edits") in config_calls

    with pytest.raises(SDKError, match="does not offer the model"):
        await _collect(
            backend,
            runtime.call(settings={"model": "unknown-model"}),
            "Bad model",
        )


@pytest.mark.parametrize(
    ("decision", "expected_outcome", "expected_option"),
    [
        ("approved", "selected", "opt-allow"),
        ("rejected", "selected", "opt-reject"),
        ("cancelled", "cancelled", None),
    ],
)
async def test_approval_belongs_to_live_call(
    runtime: _Runtime,
    decision: str,
    expected_outcome: str,
    expected_option: str | None,
):
    seen: list[tuple[str, str, float]] = []

    async def decide(summary, *, timeout):
        seen.append(
            (
                summary.tool_name,
                summary.parameters["provider_item_id"],
                timeout,
            ),
        )
        return decision

    options = [
        PermissionOption(
            option_id="opt-allow",
            name="Allow once",
            kind="allow_once",
        ),
        PermissionOption(
            option_id="opt-reject",
            name="Reject once",
            kind="reject_once",
        ),
    ]
    tool_call = ToolCallUpdate(
        tool_call_id="tc-1",
        title="rm -rf tmp",
        kind="execute",
        raw_input={"command": "rm -rf tmp"},
    )
    runtime.server.permission_requests.append((options, tool_call))

    backend = runtime.backend()
    call = runtime.call(request_approval=decide)
    events = await _collect(backend, call, "Run tool")
    assert events[-1].kind == HarnessEventKind.COMPLETED
    assert seen == [("rm -rf tmp", "tc-1", 60)]

    perm = runtime.server.permissions[-1]
    assert perm.outcome.outcome == expected_outcome
    if expected_option is not None:
        assert perm.outcome.option_id == expected_option

    # Stale permission request after the turn ends is cancelled and never
    # invokes the approval callback again.
    stale = await runtime.server.clients[-1].request_permission(
        options=options,
        session_id="acp-1",
        tool_call=tool_call,
    )
    assert stale.outcome.outcome == "cancelled"
    assert len(seen) == 1


async def test_bypass_permissions_spawns_unattended_server(runtime: _Runtime):
    backend = runtime.backend()
    call = runtime.call(settings={"permission_mode": BYPASS_PERMISSIONS})
    events = await _collect(backend, call, "Full access")
    assert events[-1].kind == HarnessEventKind.COMPLETED
    assert (
        "--dangerously-skip-permissions" in runtime.server.spawned[-1]["args"]
    )


async def test_system_prompt_meta_includes_memory_and_truncated_agents_rest(
    runtime: _Runtime,
):
    (runtime.workspace / "SOUL.md").write_text("Be concise.", encoding="utf-8")
    (runtime.workspace / "MEMORY.md").write_text(
        "Likes tea.",
        encoding="utf-8",
    )
    long_agents = ("line\n" * 6000) + "TAIL_RULE_MARKER\n"
    (runtime.workspace / "AGENTS.md").write_text(long_agents, encoding="utf-8")

    backend = runtime.backend()
    await _collect(backend, runtime.call(), "Check meta")
    new_session_params = next(
        params
        for name, params in runtime.server.calls
        if name == "new_session"
    )
    appended = new_session_params["antigravity"]["systemPrompt"]["append"]
    assert "Be concise." in appended
    assert "Likes tea." in appended
    assert "TAIL_RULE_MARKER" in appended
    assert "automated host" in appended


async def test_background_work_wait_reminder_and_daemon_exemption(
    runtime: _Runtime,
):
    runtime.server.scripts = [
        [
            start_tool_call(
                "bg-1",
                "npm run build",
                kind="execute",
                status="in_progress",
            ),
            update_agent_message_text("Started build, waiting..."),
        ],
        [
            update_tool_call("bg-1", status="completed"),
            update_agent_message_text("Build finished."),
        ],
    ]
    backend = runtime.backend()
    events = await _collect(backend, runtime.call(), "Build it")
    assert runtime.server.prompt_count == 2
    assert any(
        e.kind == HarnessEventKind.REASONING_DELTA
        and "still running in the background" in e.text
        for e in events
    )
    assert events[-1].kind == HarnessEventKind.COMPLETED

    # Daemon tools (IsDaemon=True) do not trigger a reminder.
    runtime.server.prompt_count = 0
    runtime.server.scripts = [
        [
            start_tool_call(
                "daemon-1",
                "npm run dev",
                kind="execute",
                status="in_progress",
                raw_input={"IsDaemon": True},
            ),
            update_agent_message_text("Dev server started."),
        ],
    ]
    events = await _collect(backend, runtime.call("chat-2"), "Start dev")
    assert runtime.server.prompt_count == 1
    assert events[-1].kind == HarnessEventKind.COMPLETED


async def test_swarm_command_adds_host_note_except_for_exempt_forms(
    runtime: _Runtime,
):
    backend = runtime.backend()
    await backend.run_command(runtime.call(), "swarm", "refactor auth")
    prompt_blocks = [
        params["prompt"]
        for name, params in runtime.server.calls
        if name == "prompt"
    ][-1]
    assert "swarm_wait" in prompt_blocks[0].text

    await backend.run_command(runtime.call(), "swarm", "status")
    status_blocks = [
        params["prompt"]
        for name, params in runtime.server.calls
        if name == "prompt"
    ][-1]
    assert "swarm_wait" not in status_blocks[0].text

    with pytest.raises(HarnessOperationNotSupportedError):
        await backend.run_command(runtime.call(), "compact", "")


async def test_attachments_images_data_urls_and_files(runtime: _Runtime):
    img = runtime.tmp_path / "shot.bin"
    img.write_bytes(_PNG_HEADER)
    doc = runtime.tmp_path / "notes.txt"
    doc.write_text("hello", encoding="utf-8")
    inline = "data:image/jpeg;base64," + base64.b64encode(b"jpg").decode(
        "ascii",
    )

    backend = runtime.backend()
    events = await _collect(
        backend,
        runtime.call(),
        "Inspect these",
        attachments=(
            HarnessAttachment(HarnessAttachmentKind.IMAGE, img, "shot.bin"),
            HarnessAttachment(
                HarnessAttachmentKind.IMAGE,
                Path(inline),
                "inline.jpg",
            ),
            HarnessAttachment(HarnessAttachmentKind.FILE, doc, "notes.txt"),
        ),
    )
    assert events[-1].kind == HarnessEventKind.COMPLETED
    prompt_blocks = next(
        params["prompt"]
        for name, params in runtime.server.calls
        if name == "prompt"
    )
    assert prompt_blocks[0].type == "text"
    assert str(doc.resolve()) in prompt_blocks[0].text
    image_blocks = [b for b in prompt_blocks if b.type == "image"]
    assert [(b.mime_type, bool(b.data)) for b in image_blocks] == [
        ("image/png", True),
        ("image/jpeg", True),
    ]
    links = [b for b in prompt_blocks if b.type == "resource_link"]
    assert len(links) == 1 and links[0].name == "notes.txt"


async def test_isolated_mcp_server_lru_eviction_and_auth_recycling(
    runtime: _Runtime,
):
    current_fp = ["agy:account-one"]
    caps = HarnessRuntimeCapabilities(
        mcp_servers=(
            HarnessMCPServerDefinition(
                name="demo",
                display_name="Demo",
                transport="stdio",
                command="echo",
            ),
        ),
    )
    backend = runtime.backend(
        auth_fingerprint=lambda: current_fp[0],
        max_idle_isolated_servers=1,
        idle_isolated_server_ttl=600.0,
    )
    await _collect(backend, runtime.call("s1", capabilities=caps), "One")
    first_proc = runtime.server.processes[-1]
    assert not first_proc.closed

    await _collect(backend, runtime.call("s2", capabilities=caps), "Two")
    # Cap of 1 idle isolated server evicted s1's dedicated server.
    assert first_proc.closed
    second_proc = runtime.server.processes[-1]
    assert not second_proc.closed

    # Account switch recycles the idle server on next turn.
    current_fp[0] = "agy:account-two"
    await _collect(backend, runtime.call("s2", capabilities=caps), "Three")
    assert second_proc.closed
    assert not runtime.server.processes[-1].closed


async def test_cancel_and_reset_session_isolation(runtime: _Runtime):
    runtime.server.hold_prompt = asyncio.Event()
    backend = runtime.backend()
    call_a = runtime.call("chat-a")
    call_b = runtime.call("chat-b")

    started = asyncio.Event()

    async def run_a():
        async for event in backend.run_turn(call_a, HarnessRunRequest("wait")):
            if event.kind == HarnessEventKind.TEXT_DELTA:
                started.set()

    task = asyncio.create_task(run_a())
    await asyncio.wait_for(started.wait(), 2)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert any(name == "cancel" for name, _ in runtime.server.calls)

    runtime.server.hold_prompt = None
    await _collect(backend, call_b, "Keep B")
    await backend.reset_session(call_a)
    stored = json.loads(
        (runtime.state_dir / "agy_sessions.json").read_text(encoding="utf-8"),
    )
    assert json.dumps(["alice", "console", "chat-a"]) not in stored
    assert json.dumps(["alice", "console", "chat-b"]) in stored


async def test_actual_zip_manifest_registration_and_host_call(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    plugin_id = "qwenpaw-harness-agy"
    archive = Path(__file__).resolve().parents[4] / (
        f"dist/plugins/harness/{plugin_id}/{plugin_id}-1.0.0.zip"
    )
    assert (
        archive.is_file()
    ), "Build and package Harness plugins before vendor tests"
    with zipfile.ZipFile(archive) as zipped:
        zipped.extractall(tmp_path / "unpacked")
    source = tmp_path / "unpacked" / plugin_id
    manifest = json.loads((source / "plugin.json").read_text(encoding="utf-8"))
    assert manifest["id"] == plugin_id
    assert manifest["entry"]["backend"] == "main.py"
    assert (source / manifest["entry"]["frontend"]).is_file()

    report = check_plugin(source)
    errors = [f for f in report.findings if f.severity == "error"]
    assert not errors, errors

    fake_bin = _make_executable(
        tmp_path / "bin" / ("agy.exe" if os.name == "nt" else "agy"),
    )
    server = FakeServer()
    monkeypatch.setattr(acp, "spawn_agent_process", server.spawn)
    monkeypatch.setenv("PATH", str(fake_bin.parent))

    async with PluginTestHost(tmp_path / "host") as host:
        assert (await host.install(source)).ok
        assert [
            (r["id"], r["plugin_id"], r["status"])
            for r in host.list_harnesses()
        ] == [("agy", plugin_id, "available")]
        output = [
            item
            async for item in host.run_harness(
                "agy",
                HarnessRunRequest("Review"),
                workspace_id="test",
                session_id="zip-call",
            )
        ]
        assert output[-1].status == "completed"
        assert "Done" in str(output)
