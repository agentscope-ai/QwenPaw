"""Mounted Worker and legacy endpoints share the same member and agent scope."""

from dataclasses import replace
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from zipfile import ZipFile
from concurrent.futures import ThreadPoolExecutor
from threading import Event
import runpy
import asyncio
import json
import sys
import time
import pytest
from uuid import uuid4

from fastapi import APIRouter, FastAPI, HTTPException
from fastapi.testclient import TestClient

from qwenpaw.app import agent_context
from qwenpaw.app.routers import frontend_plugin
from qwenpaw.identity.models import PlatformRole
from qwenpaw.pawapp import deps
from qwenpaw.plugins.governance import PluginGovernanceService
from qwenpaw.plugins.registry import PluginRegistry
from qwenpaw.plugins.http_scope import PluginScope, current_plugin_scope
from tests.isolation.test_plugin_governance import (
    MemoryPluginRepository,
    actor,
    installation,
)

PLUGINS = Path(__file__).resolve().parents[2] / "plugins"


def test_two_kanban_subscribers_replay_and_receive_independent_live_events(monkeypatch):
    monkeypatch.setenv("QWENPAW_MULTI_USER_ENABLED", "false")
    board = runpy.run_path(str(PLUGINS / "apps/agent-kanban/backend/main.py"))

    async def scenario():
        channel = board["SSEBroadcast"]()
        board["_CHANNELS"]["work"] = channel
        await channel.send_event({"type": "started"})
        a = (await board["stream_issue"]("work")).body_iterator
        b = (await board["stream_issue"]("work")).body_iterator
        for stream in [a, b]:
            assert '"started"' in await anext(stream)
        await channel.send_event({"type": "progress"})
        for stream in [a, b]:
            assert '"progress"' in await asyncio.wait_for(anext(stream), 1)
        await a.aclose()
        assert board["_CHANNELS"]["work"] is channel
        await channel.send_event({"type": "done"})
        channel.close()
        assert '"done"' in await asyncio.wait_for(anext(b), 1)
        await b.aclose()
        assert "work" not in board["_CHANNELS"]

    asyncio.run(scenario())


def test_members_use_real_private_kanban_and_creator_data(monkeypatch, tmp_path):
    monkeypatch.setenv("QWENPAW_MULTI_USER_ENABLED", "true")
    monkeypatch.setenv("CREATOR_DATA_ROOT", str(tmp_path / "creator"))
    monkeypatch.setattr("qwenpaw.constant.WORKING_DIR", tmp_path)
    monkeypatch.syspath_prepend(str(PLUGINS / "apps/qwenpaw-creator/backend"))
    from api.router import router as creator_router
    from api.dependencies import creator_error_handler
    from domain.errors import CreatorError

    from services.storage_root import require_creator_data_root
    from services.file_agent_runtime import driver as creator_driver
    from services.file_agent_runtime.model_client import (
        AgentModelTurn,
        CallbackAgentChatClient,
    )
    from services.file_agent_runtime import registry as runtimes
    from services.project_files import facade
    from services.media_files import shutdown_file_media_execution_services

    with pytest.raises(PermissionError):
        require_creator_data_root()
    assert require_creator_data_root(installation=True) == tmp_path / "creator"

    monkeypatch.setattr(runtimes, "_MEMBER_IDLE_SECONDS", 0.12)
    startup = {}
    original_start = creator_driver.FileCreatorAgentRuntime.start

    async def track_start(self, *, resume_unattended=True):
        startup.setdefault(self.services.root, []).append(resume_unattended)
        await original_start(self, resume_unattended=resume_unattended)

    monkeypatch.setattr(creator_driver.FileCreatorAgentRuntime, "start", track_start)
    started, release = Event(), Event()
    dispatch = Event()
    original_reconcile = creator_driver.FileCreatorAgentRuntime._reconcile_project

    async def wait_for_test_dispatch(self, project_id):
        if dispatch.is_set():
            await original_reconcile(self, project_id)

    monkeypatch.setattr(
        creator_driver.FileCreatorAgentRuntime,
        "_reconcile_project",
        wait_for_test_dispatch,
    )
    calls = []

    async def local_model(messages, tools):
        calls.append(1)
        started.set()
        assert await asyncio.to_thread(release.wait, 10)
        return AgentModelTurn(content="Local storyboard ready")

    monkeypatch.setattr(
        creator_driver,
        "AgentScopeAgentChatClient",
        lambda: CallbackAgentChatClient(local_model),
    )

    board = runpy.run_path(str(PLUGINS / "apps/agent-kanban/backend/main.py"))
    users = {u: actor(PlatformRole.MEMBER) for u in ["alice", "bob"]}
    plugin_ids = [
        "agent-kanban",
        "qwenpaw-creator",
        "chrome",
        "cloudpaw",
        "computer-use",
        "qwenpaw-pet",
    ]
    installs = [replace(installation(), plugin_id=i) for i in plugin_ids]
    repo = MemoryPluginRepository(installs, {i.id: {"all_members"} for i in installs})
    service = PluginGovernanceService(repo)
    monkeypatch.setattr(
        frontend_plugin, "get_plugin_governance_service", lambda: service
    )
    monkeypatch.setattr(deps, "_plugin_governance_service", lambda: service)
    monkeypatch.setattr(deps, "_get_session", lambda req: None)

    async def permitted_workspace(request):
        agent = request.headers["x-agent-id"]
        if agent not in {"shared", "second"}:
            raise HTTPException(403)
        request.state.authorized_agent_id = agent
        return SimpleNamespace(agent_id=agent)

    monkeypatch.setattr(agent_context, "get_agent_for_request", permitted_workspace)
    app = FastAPI()
    app.add_exception_handler(CreatorError, creator_error_handler)
    app.include_router(frontend_plugin.router, prefix="/api")
    app.state.plugin_loader = SimpleNamespace(
        get_loaded_plugin=lambda plugin: SimpleNamespace(
            source_path=PLUGINS / "apps" / plugin,
            manifest=SimpleNamespace(entry=SimpleNamespace(frontend="worker.js")),
        )
    )

    @app.middleware("http")
    async def local_test_identity(request, call_next):
        request.state.actor = users[request.headers["x-test-user"]]
        return await call_next(request)

    monkeypatch.setattr(PluginRegistry, "_instance", None)
    registry = PluginRegistry()
    registry.set_plugin_http_app(app)
    registry.register_http_router(
        "agent-kanban", board["router"], prefix="/agent-kanban"
    )
    registry.register_http_router(
        "qwenpaw-creator", creator_router, prefix="/qwenpaw-creator"
    )
    # These handlers stand in for privileged shared-host or external effects.
    shared = APIRouter()

    @shared.get("/probe")
    def probe():
        raise AssertionError("A member must not enter the shared host handler")

    for plugin, prefix in [
        ("chrome", "/plugins/chrome"),
        ("computer-use", "/plugins/computer-use"),
        ("qwenpaw-pet", "/plugins/qwenpaw-pet"),
        ("cloudpaw", "/a2a"),
    ]:
        registry.register_http_router(plugin, shared, prefix=prefix)
    app.router.on_shutdown.extend(
        [runtimes.stop_creator_agent_runtime, shutdown_file_media_execution_services]
    )
    with TestClient(app) as client:

        def headers(user, agent="shared"):
            return {"X-Test-User": user, "X-Agent-Id": agent}

        board_url = "/api/frontend_plugin/agent-kanban/runtime/issues"
        creator_url = "/api/frontend_plugin/qwenpaw-creator/runtime/projects"
        static = "/api/frontend_plugin/agent-kanban/files/"
        script = client.get(static + "worker.js", headers=headers("alice"))
        assert (
            script.status_code == 200
            and script.headers["cache-control"] == "private, no-store"
        )
        assert (
            client.get(static + "plugin.json", headers=headers("alice")).status_code
            == 404
        )
        item = client.post(
            board_url, headers=headers("alice"), json={"title": "Alice draft"}
        ).json()
        assert item["title"] == "Alice draft"
        project = client.post(
            creator_url,
            headers=headers("alice"),
            json={
                "name": "Alice movie",
                "description": "local",
                "scenario": "general",
                "clientRequestId": "new-one",
            },
        )
        assert project.status_code == 201, project.text
        project_id = project.json()["projectId"]
        for other in [headers("bob"), headers("alice", "second")]:
            assert client.get(board_url, headers=other).json()["issues"] == []
            assert (
                client.get("/api/agent-kanban/issues", headers=other).json()["issues"]
                == []
            )
            assert client.get(creator_url, headers=other).json()["items"] == []
            assert (
                client.get(
                    f"/api/qwenpaw-creator/projects/{project_id}/project", headers=other
                ).status_code
                == 404
            )
        snapshot = client.get(
            f"{creator_url}/{project_id}/project", headers=headers("alice")
        )
        assert snapshot.json()["project"]["name"] == "Alice movie"
        exported = client.get(
            f"{creator_url}/{project_id}/export",
            headers={**headers("alice"), "Idempotency-Key": "one-export"},
        )
        assert exported.status_code == 200, exported.text
        assert any(
            name.endswith("project.json")
            for name in ZipFile(BytesIO(exported.content)).namelist()
        )
        conversation = project.json()["conversationId"]
        sent = client.post(
            f"{creator_url}/{project_id}/messages",
            headers=headers("alice"),
            json={
                "conversationId": conversation,
                "clientMessageId": "message-1",
                "message": "Write a storyboard",
            },
        )
        assert sent.is_success, sent.text
        alice_key = PluginScope(users["alice"].user_id, "shared").storage_parts
        bob_key = PluginScope(users["bob"].user_id, "shared").storage_parts
        time.sleep(3 * runtimes._MEMBER_IDLE_SECONDS)
        queued_driver = runtimes._runtimes[alice_key]
        assert not calls and queued_driver.has_queued_work()
        dispatch.set()
        queued_driver.notify(project_id)
        assert started.wait(5)
        assert client.get(creator_url, headers=headers("bob")).is_success
        bob_root = runtimes._runtimes[bob_key].services.root
        until = time.monotonic() + 5
        while bob_key in runtimes._members and time.monotonic() < until:
            time.sleep(0.025)
        assert bob_key not in runtimes._runtimes and bob_root not in facade._registry
        assert runtimes._runtimes[alice_key].started
        release.set()
        history_url = (
            f"{creator_url}/{project_id}/conversations/{conversation}/messages"
        )
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            history = client.get(history_url, headers=headers("alice"))
            if "Local storyboard ready" in history.text:
                break
            time.sleep(0.1)
        assert "Local storyboard ready" in history.text
        original = runtimes._runtimes[alice_key]
        until = time.monotonic() + 5
        while alice_key in runtimes._members and time.monotonic() < until:
            time.sleep(0.025)
        assert alice_key not in runtimes._members and not original.started
        assert original.services.root not in facade._registry
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [
                pool.submit(client.get, history_url, headers=headers("alice"))
                for _ in range(2)
            ]
            assert all("Local storyboard ready" in f.result().text for f in futures)
        reopened = runtimes._runtimes[alice_key]
        assert reopened is not original and reopened.started
        assert startup[reopened.services.root][0] is True
        assert startup[reopened.services.root][-1] is False
        assert calls == [1]
        assert client.get(history_url, headers=headers("bob")).status_code == 404
        for route in [
            "chrome/runtime",
            "computer-use/runtime",
            "qwenpaw-pet/runtime",
            "cloudpaw/runtime/a2a",
        ]:
            assert (
                client.get(
                    "/api/frontend_plugin/" + route + "/probe", headers=headers("alice")
                ).status_code
                == 403
            )
        repo.grants[installs[0].id] = {users["bob"].user_id}
        for route in [board_url, "/api/agent-kanban/issues"]:
            assert client.get(route, headers=headers("alice")).status_code == 404
            assert client.get(route, headers=headers("bob")).status_code == 200
    assert not runtimes._members and not runtimes._runtimes and not reopened.started
    assert reopened.services.root not in facade._registry


@pytest.mark.asyncio
async def test_open_member_request_holds_runtime_until_release(monkeypatch, tmp_path):
    monkeypatch.setenv("QWENPAW_MULTI_USER_ENABLED", "true")
    monkeypatch.setenv("CREATOR_DATA_ROOT", str(tmp_path))
    monkeypatch.syspath_prepend(str(PLUGINS / "apps/qwenpaw-creator/backend"))
    from services.file_agent_runtime import registry
    from services.storage_root import require_creator_data_root

    monkeypatch.setattr(registry, "_MEMBER_IDLE_SECONDS", 0.04)
    scope = PluginScope(uuid4(), "shared")
    token = current_plugin_scope.set(scope)
    try:
        async with registry.member_project_services(require_creator_data_root()):
            driver = registry.get_creator_agent_runtime()
            await asyncio.sleep(0.16)
            assert (
                driver.started and registry._members[scope.storage_parts].requests == 1
            )
        async with asyncio.timeout(3):
            while scope.storage_parts in registry._members:
                await asyncio.sleep(0.02)
        assert not driver.started
    finally:
        await registry.stop_creator_agent_runtime()
        current_plugin_scope.reset(token)


def test_cloud_proposal_is_bound_to_user_agent_and_nonce_and_times_out_closed(
    monkeypatch,
):
    monkeypatch.setenv("QWENPAW_MULTI_USER_ENABLED", "true")
    cloud = PLUGINS / "bundle/cloudpaw"
    monkeypatch.delitem(sys.modules, "qwenpaw.app.interaction", raising=False)
    runpy.run_path(str(cloud / "injectors.py"))["inject_interaction_module"]()
    manager = sys.modules["qwenpaw.app.interaction"].InteractionManager
    owner = PluginScope(uuid4(), "shared")
    token = current_plugin_scope.set(owner)
    try:
        original = manager.create("chat", ["A"], [])
        for other in [
            PluginScope(uuid4(), "shared"),
            PluginScope(owner.user_id, "second"),
        ]:
            other_token = current_plugin_scope.set(other)
            try:
                assert manager.pending("chat") is None
                assert not manager.resolve("chat", "approval", original.id)
            finally:
                current_plugin_scope.reset(other_token)
        replacement = manager.create("chat", ["B"], [])
        manager.cleanup("chat", original)
        assert not manager.resolve("chat", "approval", original.id)
        assert manager.resolve("chat", "approval", replacement.id)
        assert not manager.resolve("chat", "approval", replacement.id)
        tool = runpy.run_path(str(cloud / "tools/proposal_choice.py"))[
            "proposal_choice"
        ]
        monkeypatch.setitem(tool.__globals__, "get_current_session_id", lambda: "chat")
        monkeypatch.setitem(tool.__globals__, "_INTERACTION_TIMEOUT", 0.005)
        result = asyncio.run(tool(json.dumps([["local"] * 10])))
        assert result.state.value == "error"
        assert "未授权部署" in result.content[0].text
        assert not manager.pending("chat")
    finally:
        current_plugin_scope.reset(token)
        sys.modules.pop("qwenpaw.app.interaction", None)


def test_a2a_stream_and_connection_pool_are_partitioned(monkeypatch):
    monkeypatch.setenv("QWENPAW_MULTI_USER_ENABLED", "true")
    monkeypatch.syspath_prepend(str(PLUGINS / "bundle/cloudpaw"))
    from modules.a2a.call_stream import start_stream, finish_stream, get_stream
    from modules.a2a.client_manager import get_a2a_manager, shutdown_a2a_manager

    user_a = PluginScope(uuid4(), "shared")
    first_token = current_plugin_scope.set(user_a)
    try:
        first_stream, first_manager = start_stream(), get_a2a_manager()
        for user in [
            PluginScope(uuid4(), "shared"),
            PluginScope(user_a.user_id, "second"),
        ]:
            other_token = current_plugin_scope.set(user)
            try:
                assert get_stream() is None
                assert get_a2a_manager() is not first_manager
                stream = start_stream()
                stream.publish({"text": "other scope"})
                finish_stream()
            finally:
                current_plugin_scope.reset(other_token)
        assert get_stream() is first_stream and not first_stream.history
        assert get_a2a_manager() is first_manager
        finish_stream()
        assert get_stream() is None
    finally:
        current_plugin_scope.reset(first_token)
        asyncio.run(shutdown_a2a_manager())
