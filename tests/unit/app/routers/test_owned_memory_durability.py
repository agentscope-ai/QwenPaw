"""本人私有记忆读取不应依赖原 Agent 的运行资格。"""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import httpx
import pytest
from fastapi import Depends, FastAPI, HTTPException

from qwenpaw.access.actor import ActorContext, ActorType
from qwenpaw.app.routers import agents, workspace
from qwenpaw.identity.models import PlatformRole
from qwenpaw.memory_scope.resolver import MemoryScopeResolver


def _memory_app(tmp_path, monkeypatch, *, user_id=None, admin=False):
    owner = user_id or uuid4()
    actor = ActorContext(
        user_id=owner,
        actor_type=ActorType.USER,
        platform_role=PlatformRole.ADMIN if admin else PlatformRole.MEMBER,
        admin_mode=False,
        request_id="memory-owner-test",
    )
    resolver = MemoryScopeResolver(working_dir=tmp_path)
    denied = AsyncMock(side_effect=HTTPException(403, "agent_access_revoked"))
    repository = SimpleNamespace(
        ensure_private=AsyncMock(
            side_effect=AssertionError("read must not create metadata")
        ),
        get_private=AsyncMock(return_value=None),
    )
    for module in (workspace, agents):
        monkeypatch.setattr(module, "is_multi_user_enabled", lambda: True)
        monkeypatch.setattr(module, "MemoryScopeResolver", lambda: resolver)
    monkeypatch.setattr(agents, "_get_memory_scope_resolver", lambda: resolver)
    monkeypatch.setattr(
        agents, "_get_agent_user_workspace_repository", lambda: repository
    )
    monkeypatch.setattr(
        workspace, "AgentUserWorkspaceRepository", lambda **kwargs: repository
    )
    monkeypatch.setattr(workspace, "get_running_config_workspace", denied)
    monkeypatch.setattr(agents, "_require_agent_role", denied)
    monkeypatch.setattr(
        agents,
        "load_agent_config",
        lambda _: (_ for _ in ()).throw(AssertionError("no live Agent config")),
    )
    # There is deliberately no Agent profile: history belongs to this account.
    monkeypatch.setattr(
        "qwenpaw.agents.memory.agent_md_manager.load_agent_config",
        lambda _: (_ for _ in ()).throw(ValueError("agent profile removed")),
    )
    monkeypatch.setattr(
        "qwenpaw.config.utils.load_config",
        lambda: SimpleNamespace(agents=SimpleNamespace(profiles={})),
    )
    app = FastAPI()

    @app.middleware("http")
    async def identity(request, call_next):
        request.state.actor = actor
        request.state.agent_id = request.headers.get("X-Agent-Id", "retired-agent")
        return await call_next(request)

    app.include_router(workspace.router, prefix="/api")
    app.include_router(agents.router, prefix="/api")
    return app, owner, repository


@pytest.mark.asyncio
async def test_owned_private_memory_is_readable_after_agent_is_unavailable(
    tmp_path, monkeypatch
):
    app, owner, repository = _memory_app(tmp_path, monkeypatch)
    root = tmp_path / "user_workspaces" / str(owner) / "retired-agent"
    daily = root / "memory" / "2026-09-17" / "brief.md"
    daily.parent.mkdir(parents=True)
    daily.write_text("本人的日记记忆", encoding="utf-8")
    digest = root / "digest" / "topics.md"
    digest.parent.mkdir()
    digest.write_text("本人的长期记忆", encoding="utf-8")
    before = set(tmp_path.rglob("*"))
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://local"
    ) as client:
        scopes = await client.get("/api/agents/retired-agent/memory/scopes")
        assert scopes.status_code == 200
        assert [
            (item["scope"], item["can_edit"]) for item in scopes.json()["scopes"]
        ] == [("private", False)]
        listed = await client.get("/api/workspace/memory?scope=private&section=daily")
        assert listed.status_code == 200
        assert [item["filename"] for item in listed.json()] == ["2026-09-17/brief.md"]
        for path, section, expected in (
            ("2026-09-17/brief.md", "daily", "本人的日记记忆"),
            ("topics.md", "digest", "本人的长期记忆"),
        ):
            loaded = await client.get(
                f"/api/workspace/memory/{path}?scope=private&section={section}"
            )
            assert loaded.status_code == 200
            assert loaded.json()["content"] == expected
    assert set(tmp_path.rglob("*")) == before
    repository.ensure_private.assert_not_awaited()


@pytest.mark.asyncio
async def test_private_memory_does_not_grant_public_read_or_mutation(
    tmp_path, monkeypatch
):
    app, owner, _ = _memory_app(tmp_path, monkeypatch)
    root = tmp_path / "user_workspaces" / str(owner) / "retired-agent" / "memory"
    root.mkdir(parents=True)
    (root / "own.md").write_text("unchanged", encoding="utf-8")
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://local"
    ) as client:
        for method, path in (
            ("GET", "/api/workspace/memory?scope=public"),
            ("PUT", "/api/workspace/memory/own.md?scope=private"),
            ("POST", "/api/workspace/memory/new.md?scope=private"),
            ("POST", "/api/agents/retired-agent/memory/reindex?scope=private"),
        ):
            response = await client.request(method, path, json={"content": "forbidden"})
            assert response.status_code in {403, 404}, (method, path, response.text)
    assert (root / "own.md").read_text(encoding="utf-8") == "unchanged"


@pytest.mark.asyncio
@pytest.mark.parametrize("admin", [False, True])
async def test_other_account_cannot_read_private_memory_by_owner_override(
    tmp_path, monkeypatch, admin
):
    original = uuid4()
    private = tmp_path / "user_workspaces" / str(original) / "retired-agent" / "memory"
    private.mkdir(parents=True)
    (private / "secret.md").write_text("another account secret", encoding="utf-8")
    app, viewer, _ = _memory_app(tmp_path, monkeypatch, admin=admin)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://local"
    ) as client:
        query = (
            f"scope=private&section=daily&user_id={original}&owner_user_id={original}"
        )
        listed = await client.get(f"/api/workspace/memory?{query}")
        assert listed.status_code == 200 and listed.json() == []
        loaded = await client.get(f"/api/workspace/memory/secret.md?{query}")
        assert loaded.status_code == 404
        assert "another account secret" not in loaded.text
        denied = await client.get(
            "/api/workspace/memory?scope=private",
            headers={"X-Agent-Governance": "runtime-config"},
        )
        assert denied.status_code == 403
    assert not (tmp_path / "user_workspaces" / str(viewer)).exists()


@pytest.mark.asyncio
async def test_private_memory_rejects_unsafe_agent_and_relative_escape(
    tmp_path, monkeypatch
):
    app, owner, _ = _memory_app(tmp_path, monkeypatch)
    root = tmp_path / "user_workspaces" / str(owner) / "retired-agent" / "memory"
    root.mkdir(parents=True)
    (root.parent / "PROFILE.md").write_text("not a memory file", encoding="utf-8")
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://local"
    ) as client:
        invalid = await client.get(
            "/api/workspace/memory?scope=private", headers={"X-Agent-Id": "../someone"}
        )
        assert invalid.status_code == 400
        mismatch = await client.get(
            "/api/agents/retired-agent/memory/scopes", headers={"X-Agent-Id": "someone"}
        )
        assert mismatch.status_code == 400
        escaped = await client.get(
            "/api/workspace/memory/%2E%2E%2FPROFILE.md?scope=private&section=daily"
        )
        assert escaped.status_code == 400
        assert "not a memory file" not in escaped.text


@pytest.mark.asyncio
async def test_private_scope_survives_unavailable_rebuildable_index_metadata(
    tmp_path, monkeypatch
):
    app, owner, repository = _memory_app(tmp_path, monkeypatch)
    repository.get_private.side_effect = RuntimeError(
        "rebuildable metadata unavailable"
    )
    memory = (
        tmp_path
        / "user_workspaces"
        / str(owner)
        / "retired-agent"
        / "memory"
        / "own.md"
    )
    memory.parent.mkdir(parents=True)
    memory.write_text("visible independently of index", encoding="utf-8")
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://local"
    ) as client:
        scopes = await client.get("/api/agents/retired-agent/memory/scopes")
        assert scopes.status_code == 200
        assert scopes.json()["scopes"][0]["index_state"] == "needs_reindex"
        loaded = await client.get(
            "/api/workspace/memory/own.md?scope=private&section=daily"
        )
        assert loaded.status_code == 200
        assert loaded.json()["content"] == "visible independently of index"


@pytest.mark.parametrize("has_profile", [True, False])
@pytest.mark.asyncio
async def test_private_memory_keeps_existing_custom_section_directories(
    tmp_path,
    monkeypatch,
    has_profile,
):
    app, owner, _ = _memory_app(tmp_path, monkeypatch)
    profile_root = tmp_path / "workspaces" / "retired-agent"
    profile_root.mkdir(parents=True)
    (profile_root / "agent.json").write_text(
        json.dumps(
            {
                "running": {
                    "reme_light_memory_config": {
                        "daily_dir": "journals",
                        "digest_dir": "topics/wiki",
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "qwenpaw.config.utils.load_config",
        lambda: SimpleNamespace(
            agents=SimpleNamespace(
                profiles=(
                    {
                        "retired-agent": SimpleNamespace(
                            workspace_dir=str(profile_root)
                        ),
                    }
                    if has_profile
                    else {}
                ),
            )
        ),
    )
    root = tmp_path / "user_workspaces" / str(owner) / "retired-agent"
    for directory, name in (("journals", "day.md"), ("topics/wiki", "theme.md")):
        file = root / directory / name
        file.parent.mkdir(parents=True)
        file.write_text(f"{directory} content", encoding="utf-8")
    before = {path: path.read_bytes() for path in tmp_path.rglob("*") if path.is_file()}
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://local"
    ) as client:
        for section, filename, expected in (
            ("daily", "day.md", "journals content"),
            ("digest", "theme.md", "topics/wiki content"),
        ):
            result = await client.get(
                f"/api/workspace/memory/{filename}?scope=private&section={section}"
            )
            assert result.status_code == 200 and result.json()["content"] == expected
    assert {
        path: path.read_bytes() for path in tmp_path.rglob("*") if path.is_file()
    } == before
    assert not (root / "memory").exists() and not (root / "digest").exists()


@pytest.mark.asyncio
async def test_scoped_private_memory_keeps_owner_access_without_runtime(
    tmp_path, monkeypatch
):
    from qwenpaw.app.routers import agent_scoped

    app, owner, _ = _memory_app(tmp_path, monkeypatch)
    monkeypatch.setattr(agent_scoped, "is_multi_user_enabled", lambda: True)
    monkeypatch.setattr(
        agent_scoped,
        "load_config",
        lambda: SimpleNamespace(agents=SimpleNamespace(profiles={})),
    )
    app.include_router(
        workspace.router,
        prefix="/api/agents/{agentId}",
        dependencies=[Depends(agent_scoped.require_agent_scoped_access)],
    )
    memory = (
        tmp_path
        / "user_workspaces"
        / str(owner)
        / "retired-agent"
        / "memory"
        / "own.md"
    )
    memory.parent.mkdir(parents=True)
    memory.write_text("scoped owned memory", encoding="utf-8")
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://local"
    ) as client:
        result = await client.get(
            "/api/agents/retired-agent/workspace/memory/own.md?scope=private&section=daily"
        )
        assert (
            result.status_code == 200
            and result.json()["content"] == "scoped owned memory"
        )
        for query in (
            "scope=public",
            "scope=private&scope=public",
            "scope=public&scope=private",
        ):
            rejected = await client.get(
                f"/api/agents/retired-agent/workspace/memory?{query}"
            )
            assert rejected.status_code == 403


@pytest.mark.asyncio
async def test_memory_read_rejects_private_root_symlink(tmp_path, monkeypatch):
    app, owner, _ = _memory_app(tmp_path, monkeypatch)
    foreign = tmp_path / "user_workspaces" / str(uuid4()) / "retired-agent"
    (foreign / "memory").mkdir(parents=True)
    (foreign / "memory" / "secret.md").write_text("foreign", encoding="utf-8")
    alias = tmp_path / "user_workspaces" / str(owner) / "retired-agent"
    alias.parent.mkdir(parents=True)
    try:
        alias.symlink_to(foreign, target_is_directory=True)
    except OSError:
        pytest.skip("The platform does not permit symlink creation")
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://local"
    ) as client:
        response = await client.get(
            "/api/workspace/memory/secret.md?scope=private&section=daily"
        )
        assert response.status_code == 403
        assert "foreign" not in response.text
