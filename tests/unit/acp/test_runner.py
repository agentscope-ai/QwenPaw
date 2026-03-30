# -*- coding: utf-8 -*-
from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest

from agentscope.memory import InMemoryMemory
from agentscope.message import Msg, TextBlock

from copaw.acp.i18n import RUNTIME_I18N_PREFIX
from copaw.acp.errors import ACPConfigurationError
from copaw.app.runner.runner import AgentRunner


def _build_fake_acp_service(service_cls):
    return service_cls()


def _make_returner(value):
    def _returner(*_args, **_kwargs):
        return value

    return _returner


class _FakeAgent:
    def __init__(self, *args, **kwargs):
        _ = args, kwargs

    async def register_mcp_clients(self) -> None:
        return None

    def set_console_output_enabled(self, *, enabled: bool) -> None:
        _ = enabled


class _FakeChatManager:
    def __init__(self) -> None:
        self.chat = SimpleNamespace(id="chat-1", meta={})

    async def get_or_create_chat(self, *args, **kwargs):
        _ = args, kwargs
        return self.chat

    async def update_chat(self, chat):
        return chat


class _FakeSessionStore:
    def __init__(self) -> None:
        self.state: dict[tuple[str, str], dict] = {}

    async def get_session_state_dict(
        self,
        session_id: str,
        user_id: str = "",
        allow_not_exist: bool = True,
    ) -> dict:
        _ = allow_not_exist
        return self.state.get((session_id, user_id), {})

    async def update_session_state(
        self,
        session_id: str,
        key,
        value,
        user_id: str = "",
        create_if_not_exist: bool = True,
    ) -> None:
        _ = create_if_not_exist
        state = self.state.setdefault((session_id, user_id), {})
        path = key.split(".") if isinstance(key, str) else list(key)
        cursor = state
        for part in path[:-1]:
            cursor = cursor.setdefault(part, {})
        cursor[path[-1]] = value


def _make_fake_config(
    *,
    keep_session_default: bool = False,
    require_approval: bool = False,
):
    return SimpleNamespace(
        agents=SimpleNamespace(
            running=SimpleNamespace(
                max_iters=4,
                max_input_length=4000,
            ),
        ),
        acp=SimpleNamespace(
            require_approval=require_approval,
            harnesses={
                "opencode": SimpleNamespace(
                    keep_session_default=keep_session_default,
                    permission_broker_verified=False,
                ),
            },
        ),
    )


def _make_assistant_msg(text: str, *, msg_id: str) -> Msg:
    msg = Msg(
        name="Friday",
        role="assistant",
        content=[TextBlock(type="text", text=text)],
    )
    msg.id = msg_id
    return msg


@pytest.mark.asyncio
async def test_external_agent_defaults_to_process_cwd(monkeypatch) -> None:
    runner = AgentRunner()
    runner.set_chat_manager(_FakeChatManager())
    runner.session = _FakeSessionStore()

    captured: dict[str, str] = {}

    class _FakeACPService:
        async def run_turn(self, **kwargs):
            captured["cwd"] = kwargs["cwd"]
            await kwargs["on_message"](
                Msg(
                    name="Friday",
                    role="assistant",
                    content=[TextBlock(type="text", text="ok")],
                ),
                True,
            )
            return SimpleNamespace(
                session_id="acp-session-1",
                cwd=kwargs["cwd"],
            )

    fake_config = _make_fake_config()

    monkeypatch.setattr(
        "copaw.app.runner.runner.load_config",
        lambda: fake_config,
    )
    monkeypatch.setattr("copaw.app.runner.runner.CoPawAgent", _FakeAgent)
    service = _FakeACPService()

    def fake_get_acp_service():
        return service

    monkeypatch.setattr(runner, "_get_acp_service", fake_get_acp_service)

    request = SimpleNamespace(
        session_id="session-1",
        user_id="user-1",
        channel="console",
        external_agent={
            "enabled": True,
            "harness": "opencode",
            "keep_session": False,
        },
    )
    msgs = [
        Msg(
            name="user",
            role="user",
            content=[TextBlock(type="text", text="inspect this repo")],
        ),
    ]

    outputs = []
    async for item in runner.query_handler(msgs, request=request):
        outputs.append(item)

    assert outputs
    assert captured["cwd"] == str(Path.cwd())


@pytest.mark.asyncio
async def test_external_agent_reuses_previous_session_from_chat_meta(
    monkeypatch,
) -> None:
    runner = AgentRunner()
    chat_manager = _FakeChatManager()
    chat_manager.chat.meta = {
        "external_agent": {
            "harness": "opencode",
            "keep_session": False,
            "acp_session_id": "prev-session-1",
            "cwd": str(Path.cwd()),
        },
    }
    runner.set_chat_manager(chat_manager)
    runner.session = _FakeSessionStore()

    captured: dict[str, object] = {}

    class _FakeACPService:
        async def run_turn(self, **kwargs):
            captured["existing_session_id"] = kwargs["existing_session_id"]
            captured["keep_session"] = kwargs["keep_session"]
            await kwargs["on_message"](
                Msg(
                    name="Friday",
                    role="assistant",
                    content=[TextBlock(type="text", text="ok")],
                ),
                True,
            )
            return SimpleNamespace(
                session_id="prev-session-1",
                cwd=kwargs["cwd"],
            )

    fake_config = _make_fake_config()

    monkeypatch.setattr(
        "copaw.app.runner.runner.load_config",
        lambda: fake_config,
    )
    monkeypatch.setattr("copaw.app.runner.runner.CoPawAgent", _FakeAgent)
    service = _FakeACPService()

    def fake_get_acp_service():
        return service

    monkeypatch.setattr(runner, "_get_acp_service", fake_get_acp_service)

    request = SimpleNamespace(
        session_id="session-1",
        user_id="user-1",
        channel="console",
    )
    msgs = [
        Msg(
            name="user",
            role="user",
            content=[
                TextBlock(
                    type="text",
                    text="/acp opencode 请使用之前的 session 当前代码量",
                ),
            ],
        ),
    ]

    outputs = []
    async for item in runner.query_handler(msgs, request=request):
        outputs.append(item)

    assert outputs
    assert captured["existing_session_id"] == "prev-session-1"
    assert captured["keep_session"] is True


@pytest.mark.asyncio
async def test_external_agent_reuses_current_session_phrase_from_chat_meta(
    monkeypatch,
) -> None:
    runner = AgentRunner()
    chat_manager = _FakeChatManager()
    chat_manager.chat.meta = {
        "external_agent": {
            "harness": "opencode",
            "keep_session": False,
            "acp_session_id": "current-session-1",
            "cwd": str(Path.cwd()),
        },
    }
    runner.set_chat_manager(chat_manager)
    runner.session = _FakeSessionStore()

    captured: dict[str, object] = {}

    class _FakeACPService:
        async def run_turn(self, **kwargs):
            captured["existing_session_id"] = kwargs["existing_session_id"]
            captured["keep_session"] = kwargs["keep_session"]
            await kwargs["on_message"](
                Msg(
                    name="Friday",
                    role="assistant",
                    content=[TextBlock(type="text", text="ok")],
                ),
                True,
            )
            return SimpleNamespace(
                session_id="current-session-1",
                cwd=kwargs["cwd"],
            )

    fake_config = _make_fake_config()

    monkeypatch.setattr(
        "copaw.app.runner.runner.load_config",
        lambda: fake_config,
    )
    monkeypatch.setattr("copaw.app.runner.runner.CoPawAgent", _FakeAgent)
    service = _FakeACPService()

    def fake_get_acp_service():
        return service

    monkeypatch.setattr(runner, "_get_acp_service", fake_get_acp_service)

    request = SimpleNamespace(
        session_id="session-1",
        user_id="user-1",
        channel="console",
    )
    msgs = [
        Msg(
            name="user",
            role="user",
            content=[
                TextBlock(
                    type="text",
                    text="/acp opencode 在当前 session 简单分析CONTRIBUTING_zh.md",
                ),
            ],
        ),
    ]

    outputs = []
    async for item in runner.query_handler(msgs, request=request):
        outputs.append(item)

    assert outputs
    assert captured["existing_session_id"] == "current-session-1"
    assert captured["keep_session"] is True


@pytest.mark.asyncio
async def test_external_agent_persists_history_for_chat_reload(
    monkeypatch,
) -> None:
    runner = AgentRunner()
    runner.set_chat_manager(_FakeChatManager())
    runner.session = _FakeSessionStore()

    class _FakeACPService:
        async def run_turn(self, **kwargs):
            await kwargs["on_message"](
                _make_assistant_msg("partial", msg_id="acp-assistant-1"),
                False,
            )
            await kwargs["on_message"](
                _make_assistant_msg(
                    "final answer",
                    msg_id="acp-assistant-1",
                ),
                True,
            )
            return SimpleNamespace(
                session_id="acp-session-1",
                cwd=kwargs["cwd"],
            )

    fake_config = _make_fake_config()

    monkeypatch.setattr(
        "copaw.app.runner.runner.load_config",
        lambda: fake_config,
    )
    monkeypatch.setattr("copaw.app.runner.runner.CoPawAgent", _FakeAgent)
    service = _FakeACPService()

    def fake_get_acp_service():
        return service

    monkeypatch.setattr(runner, "_get_acp_service", fake_get_acp_service)

    request = SimpleNamespace(
        session_id="session-1",
        user_id="user-1",
        channel="console",
        external_agent={
            "enabled": True,
            "harness": "opencode",
            "keep_session": False,
        },
    )
    msgs = [
        Msg(
            name="user",
            role="user",
            content=[TextBlock(type="text", text="inspect this repo")],
        ),
    ]

    outputs = []
    async for item in runner.query_handler(msgs, request=request):
        outputs.append(item)

    assert outputs

    persisted = await runner.session.get_session_state_dict(
        "session-1",
        "user-1",
    )
    memory = InMemoryMemory()
    memory.load_state_dict(persisted["external_agent_memory"])
    history = await memory.get_memory()

    # Streaming chunks with the same message id should collapse into the
    # finalized message so chat reload does not duplicate the response.
    assert len(history) == 2
    assert history[0].role == "user"
    assert history[1].role == "assistant"
    assert history[1].content[0]["text"] == "final answer"


@pytest.mark.asyncio
async def test_external_agent_persists_configuration_error_for_chat_reload(
    monkeypatch,
) -> None:
    runner = AgentRunner()
    runner.set_chat_manager(_FakeChatManager())
    runner.session = _FakeSessionStore()

    class _FakeACPService:
        async def run_turn(self, **kwargs):
            _ = kwargs
            raise ACPConfigurationError("ACP is disabled in config")

    fake_config = _make_fake_config()

    monkeypatch.setattr(
        "copaw.app.runner.runner.load_config",
        lambda: fake_config,
    )
    monkeypatch.setattr("copaw.app.runner.runner.CoPawAgent", _FakeAgent)
    monkeypatch.setattr(
        runner,
        "_get_acp_service",
        lambda: _build_fake_acp_service(_FakeACPService),
    )

    request = SimpleNamespace(
        session_id="session-1",
        user_id="user-1",
        channel="console",
        external_agent={
            "enabled": True,
            "harness": "opencode",
            "keep_session": False,
        },
    )
    msgs = [
        Msg(
            name="user",
            role="user",
            content=[TextBlock(type="text", text="/acp opencode 分析 main.py")],
        ),
    ]

    outputs = []
    async for item in runner.query_handler(msgs, request=request):
        outputs.append(item)

    assert outputs
    persisted = await runner.session.get_session_state_dict(
        "session-1",
        "user-1",
    )
    memory = InMemoryMemory()
    memory.load_state_dict(persisted["external_agent_memory"])
    history = await memory.get_memory()

    assert len(history) == 2
    assert history[0].role == "user"
    assert history[1].role == "assistant"
    assert history[1].content[0]["text"] == "ACP is disabled in config"


def test_external_agent_timeout_message_uses_runtime_i18n_payload(
    monkeypatch,
) -> None:
    pending = SimpleNamespace(
        request_id="req-1",
        tool_name="bash",
        created_at=0.0,
    )

    class _FakeApprovalService:
        async def get_pending_by_session(self, session_id: str):
            _ = session_id
            return pending

        async def resolve_request(self, request_id: str, decision):
            _ = request_id, decision
            return pending

    approval_service = _FakeApprovalService()

    def _fake_get_approval_service():
        return approval_service

    monkeypatch.setattr(
        "copaw.app.runner.runner.time.time",
        lambda: 999.0,
    )
    monkeypatch.setattr(
        "copaw.app.approvals.get_approval_service",
        _fake_get_approval_service,
    )

    # pylint: disable=protected-access
    async def _run():
        runner = AgentRunner()
        return await runner._resolve_pending_approval("session-1", "")

    response, consumed, approved, approved_external = asyncio.run(_run())

    assert consumed is True
    assert approved is None
    assert approved_external is None
    assert response is not None
    assert response.content[0]["text"].startswith(RUNTIME_I18N_PREFIX)


def test_acp_permission_finding_title_uses_i18n_key() -> None:
    from copaw.acp.permissions import ACPPermissionAdapter

    adapter = ACPPermissionAdapter(cwd=str(Path.cwd()))
    # pylint: disable=protected-access
    result = adapter._build_tool_guard_result(
        tool_name="bash",
        tool_kind="exec",
        summary={"tool_name": "bash"},
        tool_call={"command": "pwd"},
    )

    assert result.findings[0].title == "acp.approval.requestTitle"
    assert (
        result.findings[0].metadata["i18n_key"] == "acp.approval.requestTitle"
    )


@pytest.mark.asyncio
async def test_external_agent_unverified_dangerous_prompt_queues_preapproval(
    monkeypatch,
) -> None:
    runner = AgentRunner()
    runner.set_chat_manager(_FakeChatManager())
    runner.session = _FakeSessionStore()

    class _FakeACPService:
        async def run_turn(self, **kwargs):
            _ = kwargs
            raise AssertionError("ACP turn should wait for approval first")

    class _FakePending:
        def __init__(self) -> None:
            self.request_id = "req-1"

    class _FakeApprovalService:
        def __init__(self) -> None:
            self.calls: list[dict[str, object]] = []

        async def get_pending_by_session(self, _session_id: str):
            return None

        async def create_pending(self, **kwargs):
            self.calls.append(kwargs)
            return _FakePending()

    approval_service = _FakeApprovalService()
    fake_config = _make_fake_config(require_approval=True)
    fake_config.acp.harnesses["opencode"].permission_broker_verified = False

    monkeypatch.setattr(
        "copaw.app.runner.runner.load_config",
        lambda: fake_config,
    )
    monkeypatch.setattr("copaw.app.runner.runner.CoPawAgent", _FakeAgent)
    monkeypatch.setattr(
        runner,
        "_get_acp_service",
        _make_returner(_FakeACPService()),
    )
    monkeypatch.setattr(
        "copaw.app.approvals.get_approval_service",
        lambda: approval_service,
    )

    request = SimpleNamespace(
        session_id="session-1",
        user_id="user-1",
        channel="console",
        external_agent={
            "enabled": True,
            "harness": "opencode",
            "keep_session": False,
            "cwd": "/repo",
        },
    )
    msgs = [
        Msg(
            name="user",
            role="user",
            content=[TextBlock(type="text", text="创建一个新文件 note.txt")],
        ),
    ]

    outputs = []
    async for item in runner.query_handler(msgs, request=request):
        outputs.append(item)

    assert len(outputs) == 1
    assert "Waiting for approval" in outputs[0][0].content[0]["text"]
    assert outputs[0][1] is True
    assert approval_service.calls
    extra = approval_service.calls[0]["extra"]
    assert isinstance(extra, dict)
    queued = extra["external_agent_request"]
    assert isinstance(queued, dict)
    assert queued["prompt"] == "创建一个新文件 note.txt"
    assert queued["preapproved"] is True


@pytest.mark.asyncio
async def test_external_agent_approve_replays_preapproved_request(
    monkeypatch,
) -> None:
    runner = AgentRunner()
    runner.set_chat_manager(_FakeChatManager())
    runner.session = _FakeSessionStore()

    captured: dict[str, object] = {}

    class _FakeACPService:
        async def run_turn(self, **kwargs):
            captured.update(kwargs)
            await kwargs["on_message"](
                Msg(
                    name="Friday",
                    role="assistant",
                    content=[TextBlock(type="text", text="approved run")],
                ),
                True,
            )
            return SimpleNamespace(
                session_id="acp-session-1",
                cwd=kwargs["cwd"],
            )

    pending = SimpleNamespace(
        request_id="req-1",
        created_at=999.0,
        tool_name="ACP/opencode",
        extra={
            "external_agent_request": {
                "enabled": True,
                "harness": "opencode",
                "keep_session": False,
                "cwd": "/repo",
                "existing_session_id": None,
                "prompt": "创建一个新文件 note.txt",
                "keep_session_specified": True,
                "preapproved": True,
            },
        },
    )

    class _FakeApprovalService:
        async def get_pending_by_session(self, _session_id: str):
            return pending

        async def resolve_request(self, _request_id: str, _decision):
            return pending

    fake_config = _make_fake_config(require_approval=True)

    monkeypatch.setattr(
        "copaw.app.runner.runner.load_config",
        lambda: fake_config,
    )
    monkeypatch.setattr("copaw.app.runner.runner.CoPawAgent", _FakeAgent)
    monkeypatch.setattr(
        runner,
        "_get_acp_service",
        _make_returner(_FakeACPService()),
    )
    monkeypatch.setattr(
        "copaw.app.approvals.get_approval_service",
        _make_returner(_FakeApprovalService()),
    )
    monkeypatch.setattr(
        "copaw.app.runner.runner.time.time",
        lambda: 1000.0,
    )

    async def _fake_cleanup(*args, **kwargs):
        _ = args, kwargs
        return None

    monkeypatch.setattr(
        runner,
        "_cleanup_denied_session_memory",
        _fake_cleanup,
    )

    request = SimpleNamespace(
        session_id="session-1",
        user_id="user-1",
        channel="console",
    )
    msgs = [
        Msg(
            name="user",
            role="user",
            content=[TextBlock(type="text", text="/approve")],
        ),
    ]

    outputs = []
    async for item in runner.query_handler(msgs, request=request):
        outputs.append(item)

    assert outputs
    assert outputs[-1][0].content[0]["text"] == "approved run"
    assert captured["preapproved"] is True
    assert captured["prompt_blocks"] == [
        {"type": "text", "text": "创建一个新文件 note.txt"},
    ]


@pytest.mark.asyncio
async def test_pending_approval_denial_persists_history(monkeypatch) -> None:
    runner = AgentRunner()
    runner.set_chat_manager(_FakeChatManager())
    runner.session = _FakeSessionStore()

    pending = SimpleNamespace(
        request_id="req-1",
        created_at=999.0,
        tool_name="ACP/opencode",
        extra={},
    )

    class _FakeApprovalService:
        async def get_pending_by_session(self, _session_id: str):
            return pending

        async def resolve_request(self, _request_id: str, _decision):
            return pending

    monkeypatch.setattr(
        "copaw.app.approvals.get_approval_service",
        _make_returner(_FakeApprovalService()),
    )
    monkeypatch.setattr(
        "copaw.app.runner.runner.time.time",
        lambda: 1000.0,
    )

    async def _fake_cleanup(*args, **kwargs):
        _ = args, kwargs
        return None

    monkeypatch.setattr(
        runner,
        "_cleanup_denied_session_memory",
        _fake_cleanup,
    )

    request = SimpleNamespace(
        session_id="session-1",
        user_id="user-1",
        channel="console",
    )
    msgs = [
        Msg(
            name="user",
            role="user",
            content=[TextBlock(type="text", text="no")],
        ),
    ]

    outputs = []
    async for item in runner.query_handler(msgs, request=request):
        outputs.append(item)

    assert outputs
    persisted = await runner.session.get_session_state_dict(
        "session-1",
        "user-1",
    )
    memory = InMemoryMemory()
    memory.load_state_dict(persisted["external_agent_memory"])
    history = await memory.get_memory()

    assert history[-2].content[0]["text"] == "no"
    assert "denied" in history[-1].content[0]["text"]


@pytest.mark.asyncio
async def test_external_agent_uses_harness_keep_session_default(
    monkeypatch,
) -> None:
    runner = AgentRunner()
    runner.set_chat_manager(_FakeChatManager())
    runner.session = _FakeSessionStore()

    captured: dict[str, object] = {}

    class _FakeACPService:
        async def run_turn(self, **kwargs):
            captured["keep_session"] = kwargs["keep_session"]
            captured["existing_session_id"] = kwargs["existing_session_id"]
            await kwargs["on_message"](
                Msg(
                    name="Friday",
                    role="assistant",
                    content=[TextBlock(type="text", text="ok")],
                ),
                True,
            )
            return SimpleNamespace(
                session_id="acp-session-1",
                cwd=kwargs["cwd"],
            )

    fake_config = _make_fake_config(keep_session_default=True)

    monkeypatch.setattr(
        "copaw.app.runner.runner.load_config",
        lambda: fake_config,
    )
    monkeypatch.setattr("copaw.app.runner.runner.CoPawAgent", _FakeAgent)
    service = _FakeACPService()
    monkeypatch.setattr(runner, "_get_acp_service", lambda: service)

    request = SimpleNamespace(
        session_id="session-1",
        user_id="user-1",
        channel="console",
        external_agent={
            "enabled": True,
            "harness": "opencode",
        },
    )
    msgs = [
        Msg(
            name="user",
            role="user",
            content=[TextBlock(type="text", text="inspect this repo")],
        ),
    ]

    outputs = []
    async for item in runner.query_handler(msgs, request=request):
        outputs.append(item)

    assert outputs
    assert captured["keep_session"] is True
    assert captured["existing_session_id"] is None


@pytest.mark.asyncio
async def test_external_agent_reuses_previous_session_from_harness_default(
    monkeypatch,
) -> None:
    runner = AgentRunner()
    chat_manager = _FakeChatManager()
    chat_manager.chat.meta = {
        "external_agent": {
            "harness": "opencode",
            "keep_session": False,
            "acp_session_id": "prev-session-1",
            "cwd": str(Path.cwd()),
        },
    }
    runner.set_chat_manager(chat_manager)
    runner.session = _FakeSessionStore()

    captured: dict[str, object] = {}

    class _FakeACPService:
        async def run_turn(self, **kwargs):
            captured["keep_session"] = kwargs["keep_session"]
            captured["existing_session_id"] = kwargs["existing_session_id"]
            await kwargs["on_message"](
                Msg(
                    name="Friday",
                    role="assistant",
                    content=[TextBlock(type="text", text="ok")],
                ),
                True,
            )
            return SimpleNamespace(
                session_id="prev-session-1",
                cwd=kwargs["cwd"],
            )

    fake_config = _make_fake_config(keep_session_default=True)

    monkeypatch.setattr(
        "copaw.app.runner.runner.load_config",
        lambda: fake_config,
    )
    monkeypatch.setattr("copaw.app.runner.runner.CoPawAgent", _FakeAgent)
    service = _FakeACPService()
    monkeypatch.setattr(runner, "_get_acp_service", lambda: service)

    request = SimpleNamespace(
        session_id="session-1",
        user_id="user-1",
        channel="console",
        external_agent={
            "enabled": True,
            "harness": "opencode",
        },
    )
    msgs = [
        Msg(
            name="user",
            role="user",
            content=[TextBlock(type="text", text="inspect this repo")],
        ),
    ]

    outputs = []
    async for item in runner.query_handler(msgs, request=request):
        outputs.append(item)

    assert outputs
    assert captured["keep_session"] is True
    assert captured["existing_session_id"] == "prev-session-1"


@pytest.mark.asyncio
async def test_external_agent_auto_restores_from_chat_meta_keep_session(
    monkeypatch,
) -> None:
    runner = AgentRunner()
    chat_manager = _FakeChatManager()
    chat_manager.chat.meta = {
        "external_agent": {
            "enabled": True,
            "harness": "opencode",
            "keep_session": True,
            "acp_session_id": "prev-session-1",
            "cwd": str(Path.cwd()),
        },
    }
    runner.set_chat_manager(chat_manager)
    runner.session = _FakeSessionStore()

    captured: dict[str, object] = {}

    class _FakeACPService:
        async def run_turn(self, **kwargs):
            captured["keep_session"] = kwargs["keep_session"]
            captured["existing_session_id"] = kwargs["existing_session_id"]
            captured["cwd"] = kwargs["cwd"]
            captured["prompt"] = kwargs["prompt_blocks"][0]["text"]
            await kwargs["on_message"](
                Msg(
                    name="Friday",
                    role="assistant",
                    content=[TextBlock(type="text", text="ok")],
                ),
                True,
            )
            return SimpleNamespace(
                session_id="prev-session-1",
                cwd=kwargs["cwd"],
            )

    fake_config = _make_fake_config(keep_session_default=False)

    monkeypatch.setattr(
        "copaw.app.runner.runner.load_config",
        lambda: fake_config,
    )
    monkeypatch.setattr("copaw.app.runner.runner.CoPawAgent", _FakeAgent)
    service = _FakeACPService()
    monkeypatch.setattr(runner, "_get_acp_service", lambda: service)

    request = SimpleNamespace(
        session_id="session-1",
        user_id="user-1",
        channel="console",
    )
    msgs = [
        Msg(
            name="user",
            role="user",
            content=[
                TextBlock(
                    type="text",
                    text="Please inspect the file you just created.",
                ),
            ],
        ),
    ]

    outputs = []
    async for item in runner.query_handler(msgs, request=request):
        outputs.append(item)

    assert outputs
    assert captured["keep_session"] is True
    assert captured["existing_session_id"] == "prev-session-1"
    assert captured["cwd"] == str(Path.cwd())
    assert captured["prompt"] == "Please inspect the file you just created."


@pytest.mark.asyncio
async def test_external_agent_does_not_reuse_previous_session_when_default_off(
    monkeypatch,
) -> None:
    runner = AgentRunner()
    chat_manager = _FakeChatManager()
    chat_manager.chat.meta = {
        "external_agent": {
            "harness": "opencode",
            "keep_session": True,
            "acp_session_id": "prev-session-1",
            "cwd": str(Path.cwd()),
        },
    }
    runner.set_chat_manager(chat_manager)
    runner.session = _FakeSessionStore()

    captured: dict[str, object] = {}

    class _FakeACPService:
        async def run_turn(self, **kwargs):
            captured["keep_session"] = kwargs["keep_session"]
            captured["existing_session_id"] = kwargs["existing_session_id"]
            await kwargs["on_message"](
                Msg(
                    name="Friday",
                    role="assistant",
                    content=[TextBlock(type="text", text="ok")],
                ),
                True,
            )
            return SimpleNamespace(
                session_id="new-session-1",
                cwd=kwargs["cwd"],
            )

    fake_config = _make_fake_config(keep_session_default=False)

    monkeypatch.setattr(
        "copaw.app.runner.runner.load_config",
        lambda: fake_config,
    )
    monkeypatch.setattr("copaw.app.runner.runner.CoPawAgent", _FakeAgent)
    service = _FakeACPService()
    monkeypatch.setattr(runner, "_get_acp_service", lambda: service)

    request = SimpleNamespace(
        session_id="session-1",
        user_id="user-1",
        channel="console",
        external_agent={
            "enabled": True,
            "harness": "opencode",
        },
    )
    msgs = [
        Msg(
            name="user",
            role="user",
            content=[TextBlock(type="text", text="inspect this repo")],
        ),
    ]

    outputs = []
    async for item in runner.query_handler(msgs, request=request):
        outputs.append(item)

    assert outputs
    assert captured["keep_session"] is False
    assert captured["existing_session_id"] is None


@pytest.mark.asyncio
async def test_external_agent_prompt_literal_does_not_enable_keep_session(
    monkeypatch,
) -> None:
    runner = AgentRunner()
    chat_manager = _FakeChatManager()
    runner.set_chat_manager(chat_manager)
    runner.session = _FakeSessionStore()

    captured: dict[str, object] = {}

    class _FakeACPService:
        async def run_turn(self, **kwargs):
            captured["keep_session"] = kwargs["keep_session"]
            captured["prompt"] = kwargs["prompt_blocks"][0]["text"]
            await kwargs["on_message"](
                Msg(
                    name="Friday",
                    role="assistant",
                    content=[TextBlock(type="text", text="ok")],
                ),
                True,
            )
            return SimpleNamespace(
                session_id="new-session-1",
                cwd=kwargs["cwd"],
            )

    fake_config = _make_fake_config(keep_session_default=False)

    monkeypatch.setattr(
        "copaw.app.runner.runner.load_config",
        lambda: fake_config,
    )
    monkeypatch.setattr("copaw.app.runner.runner.CoPawAgent", _FakeAgent)
    service = _FakeACPService()
    monkeypatch.setattr(runner, "_get_acp_service", lambda: service)

    request = SimpleNamespace(
        session_id="session-1",
        user_id="user-1",
        channel="console",
    )
    msgs = [
        Msg(
            name="user",
            role="user",
            content=[
                TextBlock(
                    type="text",
                    text=(
                        "/acp opencode 创建一个名为 note.txt 的文件，"
                        "内容是 hello no keep session"
                    ),
                ),
            ],
        ),
    ]

    outputs = []
    async for item in runner.query_handler(msgs, request=request):
        outputs.append(item)

    assert outputs
    assert captured["keep_session"] is False
    assert (
        captured["prompt"] == "创建一个名为 note.txt 的文件，内容是 hello no keep session"
    )
    assert chat_manager.chat.meta["external_agent"]["keep_session"] is False
    # pylint: disable=protected-access
    assert (
        runner._restore_external_agent_from_chat_meta(
            None,
            chat_manager.chat,
            "刚才让你做了什么？",
        )
        is None
    )
