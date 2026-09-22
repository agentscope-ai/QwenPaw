from __future__ import annotations

import json
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
import httpx
from fastapi import FastAPI

from qwenpaw.pawapp.capabilities import (
    CapabilityBroker,
    CapabilityError,
    CapabilityScope,
)
from qwenpaw.plugins.registry import PawAppLocalToolRegistration
from qwenpaw.pawapp.capability_routes import router as capability_router


class FakePlugins:
    def __init__(
        self,
        *,
        host_tools=None,
        host_skills=None,
        local_tools=None,
        local_skill_dirs=None,
    ):
        self.host_tools = host_tools or set()
        self.host_skills = host_skills or {}
        self.local_tools = local_tools or {}
        self.local_skill_dirs = local_skill_dirs or []

    def get_pawapp_capabilities(self, app_id):
        if app_id != "fixture":
            return {
                "host_tools": set(),
                "host_skills": {},
                "local_tools": {},
                "local_skill_dirs": [],
            }
        return {
            "host_tools": set(self.host_tools),
            "host_skills": dict(self.host_skills),
            "local_tools": dict(self.local_tools),
            "local_skill_dirs": list(self.local_skill_dirs),
        }


class FakeTasks:
    def __init__(self, scope):
        self.scope = scope

    async def get(self, scope, task_id):
        if scope != self.scope.task_scope or task_id != self.scope.task_id:
            raise LookupError("wrong scope")
        return SimpleNamespace(
            handle=SimpleNamespace(
                origin=SimpleNamespace(
                    return_session_ref=self.scope.session_id,
                    app_session_ref=None,
                ),
            ),
        )


class NoWorkspaces:
    async def get_agent(self, workspace_id):
        raise AssertionError(
            f"private capability resolved workspace {workspace_id}",
        )


def scope(**changes) -> CapabilityScope:
    values = {
        "principal_id": "alice",
        "workspace_id": "workspace-1",
        "app_id": "fixture",
        "task_id": "task-1",
        "session_id": "main:1",
    }
    values.update(changes)
    return CapabilityScope(**values)


def private_tool(name, func) -> PawAppLocalToolRegistration:
    return PawAppLocalToolRegistration(
        plugin_id="fixture",
        name=name,
        func=func,
        description=f"{name} description",
        input_schema={
            "type": "object",
            "properties": {"value": {"type": "integer"}},
            "required": ["value"],
            "additionalProperties": False,
        },
    )


@pytest.mark.asyncio
async def test_private_tool_and_skill_are_scoped_and_audited(
    tmp_path: Path,
) -> None:
    async def double(value: int) -> int:
        return value * 2

    skill_dir = tmp_path / "private-skills" / "guide"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "---\nname: guide\ndescription: Double values\n"
        "tool_refs:\n  - double\n---\nUse double.\n",
        encoding="utf-8",
    )
    (skill_dir / "reference.txt").write_text(
        "private reference",
        encoding="utf-8",
    )
    plugin_registry = FakePlugins(
        local_tools={"double": private_tool("double", double)},
        local_skill_dirs=[skill_dir.parent],
    )
    granted_scope = scope()
    broker = CapabilityBroker(
        workspace_manager=NoWorkspaces(),
        plugin_registry=plugin_registry,
        task_runtime=FakeTasks(granted_scope),
        state_dir=tmp_path / "state",
    )

    token = broker.issue(granted_scope, created_at=time.time())
    authorized = await broker.authorize_token(token)
    catalog = await broker.catalog(authorized)
    result = await broker.invoke(authorized, "app/tool/double", {"value": 21})
    loaded = await broker.load_skill(authorized, "app/skill/guide")

    assert {item.capability_id for item in catalog} == {
        "app/tool/double",
        "app/skill/guide",
    }
    skill = next(item for item in catalog if item.kind == "skill")
    assert skill.tool_refs == ("double",)
    assert skill.available is True
    assert result == {"state": "success", "output": 42}
    assert {item["path"] for item in loaded["files"]} == {
        "SKILL.md",
        "reference.txt",
    }
    audit = [
        json.loads(line)
        for line in (tmp_path / "state/capability-audit.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    assert [(item["action"], item["outcome"]) for item in audit] == [
        ("invoke", "allowed"),
        ("load", "allowed"),
    ]
    assert "value" not in audit[0]
    assert "token" not in audit[0]


@pytest.mark.asyncio
async def test_token_and_capability_scope_fail_closed(tmp_path: Path) -> None:
    async def double(value: int) -> int:
        return value * 2

    granted_scope = scope()
    broker = CapabilityBroker(
        workspace_manager=NoWorkspaces(),
        plugin_registry=FakePlugins(
            local_tools={"double": private_tool("double", double)},
        ),
        task_runtime=FakeTasks(granted_scope),
        state_dir=tmp_path / "state",
    )
    token = broker.issue(granted_scope, created_at=time.time())

    with pytest.raises(CapabilityError, match="invalid_capability_token"):
        await broker.authorize_token(
            token[:-1] + ("A" if token[-1] != "A" else "B"),
        )
    with pytest.raises(CapabilityError, match="capability_not_found"):
        await broker.invoke(
            granted_scope,
            "app/tool/not-declared",
            {"value": 1},
        )
    assert await broker.catalog(scope(app_id="other")) == []


@pytest.mark.asyncio
async def test_skill_with_missing_tool_dependency_is_explicitly_blocked(
    tmp_path: Path,
) -> None:
    skill_dir = tmp_path / "private-skills" / "guide"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "---\nname: guide\ndescription: Needs a missing tool\n"
        "tool_refs:\n  - absent\n---\nUse absent.\n",
        encoding="utf-8",
    )
    broker = CapabilityBroker(
        workspace_manager=NoWorkspaces(),
        plugin_registry=FakePlugins(local_skill_dirs=[skill_dir.parent]),
        state_dir=tmp_path / "state",
    )

    catalog = await broker.catalog(scope())

    assert catalog[0].available is False
    assert catalog[0].blocked_reason == "skill_dependency_unavailable"
    with pytest.raises(CapabilityError, match="skill_dependency_unavailable"):
        await broker.load_skill(scope(), "app/skill/guide")


@pytest.mark.asyncio
async def test_host_skill_import_statuses_join_manifest_and_workspace_state(
    tmp_path: Path,
) -> None:
    workspace_dir = tmp_path / "workspace-1"
    for name in ("guidance", "disabled-guide"):
        directory = workspace_dir / "skills" / name
        directory.mkdir(parents=True)
        (directory / "SKILL.md").write_text(
            f"---\nname: {name}\ndescription: {name} description\n---\n"
            "Use the guide.\n",
            encoding="utf-8",
        )
    (workspace_dir / "skill.json").write_text(
        json.dumps(
            {
                "schema_version": "workspace-skill-manifest.v1",
                "version": 1,
                "skills": {
                    "guidance": {"enabled": True, "channels": ["all"]},
                    "disabled-guide": {
                        "enabled": False,
                        "channels": ["all"],
                    },
                },
            },
        ),
        encoding="utf-8",
    )

    class Workspaces:
        async def get_agent(self, workspace_id):
            assert workspace_id == "workspace-1"
            return SimpleNamespace(workspace_dir=workspace_dir)

    broker = CapabilityBroker(
        workspace_manager=Workspaces(),
        plugin_registry=FakePlugins(
            host_skills={
                "guidance": (),
                "disabled-guide": (),
                "missing-guide": (),
            },
        ),
        state_dir=tmp_path / "state",
    )

    statuses = await broker.host_skill_import_statuses(
        principal_id="alice",
        workspace_id="workspace-1",
        app_ids=("fixture",),
    )

    assert [(item["skill_id"], item["status"]) for item in statuses] == [
        ("disabled-guide", "disabled"),
        ("guidance", "available"),
        ("missing-guide", "not_installed"),
    ]
    assert statuses[1]["description"] == "guidance description"
    assert statuses[1]["available"] is True


@pytest.mark.asyncio
async def test_capability_routes_preserve_encoded_capability_ids() -> None:
    calls = []

    class RouteBroker:
        async def authorize_token(self, token):
            assert token == "scoped-token"
            return scope()

        async def invoke(self, granted_scope, capability_id, params):
            calls.append((granted_scope, capability_id, params))
            return {"state": "success", "output": "ok"}

    app = FastAPI()
    app.state.pawapp_capabilities = RouteBroker()
    app.include_router(capability_router, prefix="/api")
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://host.test",
        headers={"Authorization": "Bearer scoped-token"},
    ) as client:
        response = await client.post(
            "/api/pawapp-capabilities/tools/app%2Ftool%2Fecho/invoke",
            json={"params": {"value": 1}},
        )

    assert response.status_code == 200
    assert response.json()["output"] == "ok"
    assert calls[0][1:] == ("app/tool/echo", {"value": 1})
