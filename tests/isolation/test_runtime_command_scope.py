"""检查运行时动态注册的命令与静态路由使用相同的多用户边界。"""
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest
from fastapi import FastAPI, HTTPException

from qwenpaw.api_action import ManagerRegistry
from qwenpaw.app import _api_action_routes as adapters
from qwenpaw.app.app_services import _builtin_tool_commands as commands
from qwenpaw.app.crons import api as cron
from qwenpaw.app.crons.manager import CronManager
from qwenpaw.tool_calls._entry import ToolCallStatus


@pytest.mark.parametrize("multi_user", [False, True])
def test_manager_adapters_only_register_in_single_user(multi_user, monkeypatch):
    monkeypatch.setattr(adapters, "is_multi_user_enabled", lambda: multi_user)
    app = FastAPI()
    registry = ManagerRegistry()
    registry.register(CronManager, lambda _: None)
    count = adapters.register_http_routes(app, registry)
    slash = {spec.name for spec in adapters.collect_slash_specs_from_api_actions(registry)}
    if multi_user:
        assert count == 0 and slash == set()
        assert not any(route.name.startswith("auto_") for route in app.routes)
    else:
        assert count == 3 and slash == {"cron-list", "cron-create", "cron-delete"}


def test_governed_cron_router_requires_its_authorization_service(monkeypatch):
    monkeypatch.setattr(cron, "is_multi_user_enabled", lambda: True)
    with pytest.raises(HTTPException) as denied:
        cron._authorization_service(SimpleNamespace(authorization_service=None))
    assert denied.value.status_code == 503


def test_runtime_diagnostics_use_platform_role(monkeypatch):
    from starlette.requests import Request
    from qwenpaw.app import _app
    from qwenpaw.access.actor import ActorContext, ActorType
    from qwenpaw.identity.models import PlatformRole

    monkeypatch.setattr(_app, "is_multi_user_enabled", lambda: True)
    request = Request({"type": "http", "headers": []})
    request.state.actor = ActorContext(uuid4(), ActorType.USER, PlatformRole.MEMBER, False, "test")
    with pytest.raises(HTTPException) as denied:
        _app.get_doctor_runtime(request)
    assert denied.value.status_code == 403
    request.state.actor = ActorContext(uuid4(), ActorType.USER, PlatformRole.ADMIN, False, "test")
    assert _app.get_doctor_runtime(request)["python_executable"]
    assert set(_app.get_version()) == {"version"}


@pytest.mark.asyncio
async def test_slash_controls_only_manage_own_current_chat(monkeypatch):
    monkeypatch.setattr(commands, "is_multi_user_enabled", lambda: True)
    owner = uuid4()
    ctx = SimpleNamespace(agent_id="office", session_id="work", root_session_id="root",
                          request=SimpleNamespace(user_id=owner))
    def entry(agent, user, session, name):
        return SimpleNamespace(status=ToolCallStatus.RUNNING, ctx=SimpleNamespace(
            agent_id=agent, session_id=session, tool_call_id=name, tool_name=name, started_at=0,
            extra={"execution_context": {"user_id": str(user)}},
        ))
    calls = {e.ctx.tool_call_id: e for e in (
        entry("office", owner, "work", "own"), entry("office", uuid4(), "work", "other-member"),
        entry("support", owner, "work", "other-agent"), entry("office", owner, "draft", "other-session"),
    )}
    coordinator = SimpleNamespace(get=calls.get, list_entries=Mock(return_value=list(calls.values())),
                                  request_offload=AsyncMock(return_value=True), cancel=AsyncMock(return_value=True))
    listed = await commands._handle_tools(coordinator, ctx, "")
    assert "own" in listed.content[0].text and "other-" not in listed.content[0].text
    coordinator.list_entries.assert_called_once_with(session_id="work")
    for call_id in calls:
        await commands._handle_tool_bg(coordinator, ctx, call_id)
        await commands._handle_tool_cancel(coordinator, ctx, call_id)
    assert coordinator.request_offload.await_count == coordinator.cancel.await_count == 1
    assert coordinator.request_offload.await_args.args == coordinator.cancel.await_args.args == ("own",)
