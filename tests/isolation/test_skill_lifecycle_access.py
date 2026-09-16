"""Lifecycle route boundaries must not allow workspace identity substitution."""

from fastapi import FastAPI
from fastapi.testclient import TestClient
from qwenpaw.access.dependencies import get_actor
from tests.isolation.test_skill_pool_governance import actor
import pytest

from tests.integration.test_agent_skill_lifecycle import (
    lifecycle_fixture,
    skill_database,
)


def test_load_rejects_arbitrary_workspace_field_before_action():
    from qwenpaw.app.routers.skill_governance import router

    app = FastAPI()
    app.include_router(router, prefix="/api")
    app.dependency_overrides[get_actor] = actor
    response = TestClient(app).post(
        "/api/agent-skills/load",
        json={
            "agent_id": "agentA",
            "skill_id": "11111111-1111-1111-1111-111111111111",
            "workspace_id": "agentB",
        },
    )
    assert response.status_code == 422


def test_mutable_pool_download_cannot_bypass_lifecycle(tmp_path, monkeypatch):
    from qwenpaw.agents.skill_system.pool_service import SkillPoolService

    monkeypatch.setenv("QWENPAW_MULTI_USER_ENABLED", "true")
    monkeypatch.setattr("qwenpaw.constant.WORKING_DIR", str(tmp_path))
    result = SkillPoolService().download_to_workspace(
        "sample", tmp_path / "agentB", overwrite=True
    )
    assert result == {"success": False, "reason": "authorized_lifecycle_required"}
    assert not (tmp_path / "agentB").exists()


def test_mutable_rename_returns_unsynced_targets(tmp_path, monkeypatch):
    from qwenpaw.agents.skill_system.pool_service import SkillPoolService

    monkeypatch.setenv("QWENPAW_MULTI_USER_ENABLED", "true")
    monkeypatch.setattr("qwenpaw.constant.WORKING_DIR", str(tmp_path))
    result = SkillPoolService().rename_in_workspaces(
        "sample", "new", targets=["agentA"]
    )
    assert result["renamed"] == []
    assert result["results"] == [
        {
            "agent_id": "agentA",
            "status": "skipped",
            "reason": "immutable_version_required",
        }
    ]


@pytest.mark.asyncio
async def test_http_load_update_and_aliases_use_actual_agent_grants(
    skill_database, tmp_path, monkeypatch
):
    from httpx import AsyncClient, ASGITransport
    from qwenpaw.app.routers import skill_governance, skills
    from qwenpaw.skills.lifecycle import SkillLifecycleService

    monkeypatch.setenv("QWENPAW_MULTI_USER_ENABLED", "true")
    async with lifecycle_fixture(skill_database, tmp_path) as fixture:
        governance, (admin, owner, collaborator, user), item, _, workspaces, _ = fixture
        lifecycle = SkillLifecycleService(governance, workspaces.__getitem__)
        monkeypatch.setattr(
            skill_governance, "get_skill_lifecycle_service", lambda: lifecycle
        )
        monkeypatch.setattr(
            "qwenpaw.skills.runtime.get_skill_lifecycle_service", lambda: lifecycle
        )
        app = FastAPI()
        app.include_router(skill_governance.router, prefix="/api")
        app.include_router(skills.router, prefix="/api")
        app.include_router(skills.router, prefix="/api/agents/agentB")
        app.dependency_overrides[get_actor] = lambda: owner
        async with AsyncClient(
            transport=ASGITransport(app), base_url="http://fixture"
        ) as client:
            body = {"agent_id": "agentB", "skill_id": str(item["id"])}
            response = await client.post(
                "/api/agent-skills/load", json=body, headers={"x-agent-id": "agentA"}
            )
            assert response.status_code == 403
            assert not any(ws.exists() for ws in workspaces.values())
            app.dependency_overrides[get_actor] = lambda: user
            body["agent_id"] = "agentA"
            assert (
                await client.post("/api/agent-skills/load", json=body)
            ).status_code == 403
            for prefix in ["/api", "/api/agents/agentB"]:
                assert (
                    await client.post(
                        prefix + "/skills/pool/download",
                        json={
                            "skill_name": "sample",
                            "targets": [{"workspace_id": "agentA"}],
                        },
                    )
                ).status_code == 403
            app.dependency_overrides[get_actor] = lambda: collaborator
            loaded = await client.post("/api/agent-skills/load", json=body)
            assert loaded.status_code == 200
            await governance.set_agent_grant(admin, item["id"], "agentA", False)
            for operation in ["update", "restore"]:
                response = await client.post(
                    f"/api/agent-skills/sample/{operation}",
                    json={
                        "agent_id": "agentA",
                        "expected_content_hash": loaded.json()["content_hash"],
                    },
                )
                assert response.status_code == 403
            app.dependency_overrides[get_actor] = lambda: admin
            for prefix in ["/api", "/api/agents/agentB"]:
                response = await client.post(
                    prefix + "/skills/pool/download",
                    json={
                        "skill_name": "sample",
                        "targets": [{"workspace_id": "agentB"}],
                        "overwrite": True,
                    },
                )
                assert response.status_code == 200
                assert response.json()["downloaded"] == []
                assert response.json()["results"] == [
                    {
                        "agent_id": "agentB",
                        "status": "skipped",
                        "reason": "not_authorized",
                    }
                ]
            assert not workspaces["agentB"].exists()


@pytest.mark.asyncio
async def test_submission_legacy_directory_migration_follows_owner_authority(
    skill_database, tmp_path, monkeypatch
):
    from types import SimpleNamespace
    from qwenpaw.app.routers import skill_governance
    from qwenpaw.access.service import AuthorizationDeniedError

    async with lifecycle_fixture(skill_database, tmp_path) as fixture:
        governance, (_, owner, collaborator, user), _, _, workspaces, _ = fixture
        legacy = workspaces["agentA"] / "skill/sample"
        legacy.mkdir(parents=True)
        (legacy / "SKILL.md").write_text(
            "---\nname: sample\ndescription: Fixture\n---\nLegacy", encoding="utf-8"
        )
        monkeypatch.setattr(skill_governance, "get_skill_service", lambda: governance)
        monkeypatch.setattr(
            "qwenpaw.config.utils.load_config",
            lambda: SimpleNamespace(
                agents=SimpleNamespace(
                    profiles={
                        "agentA": SimpleNamespace(
                            enabled=True, workspace_dir=str(workspaces["agentA"])
                        )
                    }
                )
            ),
        )
        body = skill_governance.Submission(agent_id="agentA", skill_name="sample")
        before = set(tmp_path.rglob("*"))
        for person in [user, collaborator]:
            with pytest.raises(AuthorizationDeniedError):
                await skill_governance.submit(body, actor=person)
            assert set(tmp_path.rglob("*")) == before
        result = await skill_governance.submit(body, actor=owner)
        assert result["status"] == "pending"
        assert (
            (workspaces["agentA"] / "skills/sample/SKILL.md")
            .read_text()
            .endswith("Legacy")
        )
        assert not legacy.exists()


def test_concurrent_workspace_writer_rejects_without_modification(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    from qwenpaw.agents.skill_system.store import workspace_skill_write_lock
    from qwenpaw.agents.skill_system.workspace_service import SkillService

    service = SkillService(tmp_path)
    service.create_skill(
        "sample", "---\nname: sample\ndescription: Fixture\n---\nA", enable=True
    )
    manifest = (tmp_path / "skill.json").read_bytes()
    with workspace_skill_write_lock(tmp_path):
        with ThreadPoolExecutor(max_workers=1) as worker:
            pending = worker.submit(service.disable_skill, "sample")
            with pytest.raises(ValueError, match="skill_busy"):
                pending.result()
    assert (tmp_path / "skill.json").read_bytes() == manifest


@pytest.mark.asyncio
async def test_round1_http_damaged_copy_visible_and_stale_restore_is_409(
    skill_database, tmp_path, monkeypatch
):
    from types import SimpleNamespace
    from httpx import AsyncClient, ASGITransport
    from qwenpaw.app.routers import skill_governance, skills
    from qwenpaw.access.agent_repository import AgentResourceRole
    from qwenpaw.skills.lifecycle import SkillLifecycleService

    async with lifecycle_fixture(skill_database, tmp_path) as fixture:
        governance, (_, owner, _, user), item, _, workspaces, _ = fixture
        lifecycle = SkillLifecycleService(governance, workspaces.__getitem__)
        await lifecycle.install(owner, "agentA", item["id"])
        ws = workspaces["agentA"]
        target = ws / "skills/sample"
        (target / "SKILL.md").rename(target / "README.md")

        async def resolve(request):
            return SimpleNamespace(agent_id="agentA", workspace_dir=str(ws))

        monkeypatch.setenv("QWENPAW_MULTI_USER_ENABLED", "true")
        monkeypatch.setattr("qwenpaw.app.agent_context.get_agent_for_request", resolve)
        monkeypatch.setattr(
            "qwenpaw.app.agent_context.get_agent_access_state",
            lambda request: (AgentResourceRole.OWNER, None),
        )
        monkeypatch.setattr(
            skill_governance, "get_skill_lifecycle_service", lambda: lifecycle
        )
        monkeypatch.setattr(
            "qwenpaw.skills.runtime.get_skill_lifecycle_service", lambda: lifecycle
        )
        app = FastAPI()
        app.include_router(skill_governance.router, prefix="/api")
        app.include_router(skills.router, prefix="/api")

        @app.middleware("http")
        async def fixture_actor(request, call_next):
            request.state.actor = owner
            return await call_next(request)

        async with AsyncClient(
            transport=ASGITransport(app), base_url="http://fixture"
        ) as client:
            for method, url in [
                ("GET", "/api/skills"),
                ("POST", "/api/skills/refresh"),
                ("GET", "/api/agent-skills?agent_id=agentA"),
            ]:
                response = await client.request(method, url)
                assert response.status_code == 200
                rows = response.json()
                if isinstance(rows, dict):
                    rows = rows["items"]
                assert len(rows) == 1
                assert rows[0]["name"] == "sample"
                assert rows[0]["detached"] is True
                assert rows[0]["source_pool_version_id"] == str(item["version_id"])
                stale_hash = rows[0]["content_hash"]
            (target / "scripts/run.py").write_text(
                "print('changed')\n", encoding="utf-8"
            )
            before = (ws / "skill.json").read_bytes()
            response = await client.post(
                "/api/agent-skills/sample/restore",
                json={"agent_id": "agentA", "expected_content_hash": stale_hash},
            )
            assert response.status_code == 409
            assert response.json()["detail"] == "content_conflict"
            assert (ws / "skill.json").read_bytes() == before
            assert not (target / "SKILL.md").exists()
            current = (await client.get("/api/agent-skills?agent_id=agentA")).json()[
                "items"
            ][0]
            response = await client.post(
                "/api/agent-skills/sample/restore",
                json={
                    "agent_id": "agentA",
                    "expected_content_hash": current["content_hash"],
                },
            )
            assert response.status_code == 200
            assert response.json()["detached"] is False
            assert (target / "SKILL.md").is_file()
