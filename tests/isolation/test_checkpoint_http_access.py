# -*- coding: utf-8 -*-
"""检查点 HTTP 别名必须经过真实 Agent 门控和归属策略。"""
from __future__ import annotations

import json
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI

from qwenpaw.access.actor import ActorContext, ActorType
from qwenpaw.access.agent_membership import AgentMembershipService
from qwenpaw.access.agent_repository import AgentAccessRecord, AgentResourceRole
from qwenpaw.app import agent_context
from qwenpaw.app.chats.manager import ChatManager
from qwenpaw.app.chats.models import ChatSpec
from qwenpaw.app.chats.repo import JsonChatRepository
from qwenpaw.app.routers import agent_scoped, checkpoints
from qwenpaw.checkpoints.policy import session_file_path
from qwenpaw.checkpoints.runtime import CheckpointRuntime
from qwenpaw.identity.models import PlatformRole
from qwenpaw.persistence import agent_user_workspaces
from qwenpaw.services import workspace_files


@pytest.fixture
async def checkpoint_http(tmp_path, monkeypatch, checkpoint_test_git):
    """仅替换身份/配置/数据库边界，保留所有授权、作用域、Git 和路由代码。"""
    actors = {
        name: ActorContext(
            user_id=uuid4(),
            actor_type=ActorType.USER,
            platform_role=PlatformRole.MEMBER,
            admin_mode=False,
            request_id=f"http-{name}",
        )
        for name in ("owner", "member", "collaborator")
    }
    roles = {
        actors[name].user_id: role
        for name, role in (
            ("owner", AgentResourceRole.OWNER),
            ("member", AgentResourceRole.USER),
            ("collaborator", AgentResourceRole.COLLABORATOR),
        )
    }
    historical = set()

    class MembershipRepository:
        async def list_accessible(self, *, agent_keys, user_id):
            if user_id not in roles:
                return {}
            return {
                key: AgentAccessRecord(
                    key, actors["owner"].user_id, roles[user_id], "active"
                )
                for key in agent_keys
            }

        async def list_historical_accessible(self, *, agent_keys, user_id):
            return (
                {
                    key: AgentAccessRecord(
                        key,
                        actors["owner"].user_id,
                        AgentResourceRole.USER,
                        "active",
                        historical_read_only=True,
                    )
                    for key in agent_keys
                }
                if user_id in historical
                else {}
            )

        async def list_registered_keys(self, keys):
            return set(keys)

        async def get_first_admin_id(self):
            return actors["owner"].user_id

    membership = AgentMembershipService(MembershipRepository())
    agent_root = tmp_path / "agent"
    agent_root.mkdir()
    chat_manager = ChatManager(repo=JsonChatRepository(agent_root / "chats.json"))
    workspace = SimpleNamespace(
        agent_id="a", workspace_dir=agent_root, chat_manager=chat_manager
    )
    source_paths = {}
    for name, actor in actors.items():
        path = session_file_path(
            agent_root, session_id=name, user_id=str(actor.user_id), channel="console"
        )
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                {"agent": {"state": {"context": [], "summary": f"{name}-before"}}}
            ),
            encoding="utf-8",
        )
        source_paths[name] = path
        await chat_manager.create_chat(
            ChatSpec(
                session_id=name,
                user_id=str(actor.user_id),
                channel="console",
                name=name,
            )
        )

    class WorkspaceManager:
        async def get_agent(self, agent_id):
            assert agent_id == "a"
            return workspace

    class PrivateWorkspaceRepository:
        def __init__(self, **_kwargs):
            pass

        async def ensure_private(self, **kwargs):
            assert kwargs["user_id"] == actors["member"].user_id
            assert kwargs["agent_key"] == "a"

    config = SimpleNamespace(
        agents=SimpleNamespace(
            profiles={"a": SimpleNamespace(enabled=True, workspace_dir=str(agent_root))}
        )
    )
    for module in (agent_context, agent_scoped, checkpoints):
        monkeypatch.setattr(module, "is_multi_user_enabled", lambda: True)
    for module in (agent_context, agent_scoped):
        monkeypatch.setattr(module, "load_config", lambda: config)
        monkeypatch.setattr(module, "_get_agent_membership_service", lambda: membership)
    monkeypatch.setattr(workspace_files, "WORKING_DIR", tmp_path)
    monkeypatch.setattr(
        agent_user_workspaces,
        "AgentUserWorkspaceRepository",
        PrivateWorkspaceRepository,
    )
    runtime = CheckpointRuntime()
    monkeypatch.setattr(checkpoints, "RUNTIME", runtime)

    app = FastAPI()
    app.state.multi_agent_manager = WorkspaceManager()
    app.add_middleware(agent_scoped.AgentContextMiddleware)

    @app.middleware("http")
    async def authenticate(request, call_next):
        request.state.actor = actors[request.headers.get("x-test-actor", "member")]
        response = await call_next(request)
        access = getattr(request.state, "agent_access", None)
        response.headers["x-a-role"] = access.role.value if access else "none"
        return response

    app.include_router(checkpoints.router, prefix="/api")
    app.include_router(agent_scoped.create_agent_scoped_router(), prefix="/api")
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
        headers={"X-Agent-Id": "a"},
    ) as client:
        yield SimpleNamespace(
            client=client,
            actors=actors,
            roles=roles,
            historical=historical,
            paths=source_paths,
            manager=chat_manager,
        )
    await runtime.flush_and_close_all()


@pytest.mark.asyncio
@pytest.mark.parametrize("prefix", ["/api", "/api/agents/a"])
async def test_member_checkpoint_http_uses_personal_scope_and_rejects_foreign_restore(
    checkpoint_http, prefix
):
    env = checkpoint_http
    client = env.client
    base = prefix + "/workspace/checkpoints"
    owner = await client.post(
        base + "/snapshot",
        headers={"x-test-actor": "owner"},
        json={"session_id": "owner", "name": "owner"},
    )
    assert owner.status_code == 200, owner.text
    own = await client.post(
        base + "/snapshot",
        json={
            "session_id": "member",
            "user_id": str(env.actors["owner"].user_id),
            "name": "member",
        },
    )
    assert own.status_code == 200, own.text
    status = await client.get(base + "/status")
    assert status.json()["scope"] == "user_runtime"
    graph = await client.get(base + "/graph")
    assert [node["commit"] for node in graph.json()["nodes"]] == [own.json()["commit"]]
    assert graph.json()["nodes"][0]["user_id"] == str(env.actors["member"].user_id)
    foreign = await client.post(
        base + "/restore/preview",
        json={
            "session_id": "owner",
            "user_id": str(env.actors["owner"].user_id),
            "commit": owner.json()["commit"],
        },
    )
    assert foreign.status_code == 403
    assert foreign.headers["x-a-role"] == "user", "前置门控已放行，拒绝必须来自检查点归属策略"
    body = {"session_id": "member", "commit": own.json()["commit"]}
    preview = await client.post(base + "/restore/preview", json=body)
    assert preview.status_code == 200, preview.text
    env.paths["member"].write_text(
        '{"agent":{"state":{"context":[],"summary":"member-after"}}}', encoding="utf-8"
    )
    restored = await client.post(base + "/restore", json=body)
    assert restored.status_code == 200, restored.text
    assert (
        json.loads(env.paths["member"].read_text(encoding="utf-8"))["agent"]["state"][
            "summary"
        ]
        == "member-after"
    )
    chat = await env.manager.get_chat(restored.json()["new_chat_id"])
    assert chat.user_id == str(env.actors["member"].user_id)
    restored_path = session_file_path(
        env.paths["member"].parents[2],
        session_id=chat.session_id,
        user_id=chat.user_id,
        channel=chat.channel,
    )
    assert json.loads(restored_path.read_text(encoding="utf-8"))["agent"]["state"][
        "summary"
    ] == "member-before"
    for method, suffix, payload in [
        ("PATCH", "/auto", {"enabled": False}),
        ("POST", "/gc/preview", {}),
        ("POST", "/gc", {}),
        (
            "PATCH",
            "/gc/settings",
            {"gc_keep_count": 5, "gc_keep_days": 7, "pre_restore_retention_days": 1},
        ),
    ]:
        response = await client.request(method, base + suffix, json=payload)
        assert response.status_code == 200, response.text
    reset = await client.delete(base)
    assert reset.status_code == 200, reset.text
    owner_graph = await client.get(base + "/graph", headers={"x-test-actor": "owner"})
    assert [node["commit"] for node in owner_graph.json()["nodes"]] == [
        owner.json()["commit"]
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize("prefix", ["/api", "/api/agents/a"])
async def test_collaborator_checkpoint_http_cannot_reset_shared_repository(
    checkpoint_http, prefix
):
    base = prefix + "/workspace/checkpoints"
    owner = await checkpoint_http.client.post(
        base + "/snapshot",
        headers={"x-test-actor": "owner"},
        json={"session_id": "owner", "name": "protected"},
    )
    assert owner.status_code == 200, owner.text
    response = await checkpoint_http.client.delete(
        base, headers={"x-test-actor": "collaborator"}
    )
    assert response.status_code == 403
    graph = await checkpoint_http.client.get(
        base + "/graph", headers={"x-test-actor": "owner"}
    )
    assert [node["commit"] for node in graph.json()["nodes"]] == [
        owner.json()["commit"]
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize("prefix", ["/api", "/api/agents/a"])
@pytest.mark.parametrize("historical", [False, True])
async def test_revoked_member_cannot_enter_checkpoint_routes(
    checkpoint_http, prefix, historical
):
    env = checkpoint_http
    del env.roles[env.actors["member"].user_id]
    if historical:
        env.historical.add(env.actors["member"].user_id)
    for method, suffix in [
        ("GET", "/status"),
        ("POST", "/snapshot"),
        ("POST", "/restore/preview"),
        ("DELETE", ""),
    ]:
        response = await env.client.request(
            method,
            prefix + "/workspace/checkpoints" + suffix,
            json={"session_id": "member", "commit": "a" * 40},
        )
        assert response.status_code == 403, response.text


@pytest.mark.parametrize("prefix", ["/api", "/api/agents/a"])
@pytest.mark.parametrize(
    "method,path",
    [
        ("POST", "/workspace/checkpoints/unknown"),
        ("PUT", "/workspace/checkpoints/snapshot"),
        ("POST", "/workspace/running-config"),
        ("DELETE", "/workspace/checkpoints/gc"),
    ],
)
def test_checkpoint_exception_does_not_allow_other_workspace_writes(
    prefix, method, path
):
    request = SimpleNamespace(method=method, url=SimpleNamespace(path=prefix + path))
    assert AgentResourceRole.USER not in agent_context.allowed_agent_roles_for_request(
        request, "a"
    )
