"""Real route gates reject members before touching the pool filesystem."""

from uuid import uuid4
import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from qwenpaw.access.actor import ActorContext, ActorType
from qwenpaw.identity.models import PlatformRole


def actor(role=PlatformRole.MEMBER):
    return ActorContext(uuid4(), ActorType.USER, role, False, "test")


@pytest.mark.parametrize("prefix", ["/api", "/api/agents/agentB", "/api/agents/skills"])
@pytest.mark.parametrize(
    "method,path,body",
    [
        ("GET", "/skills/pool", None),
        ("GET", "/skills/pool/sample", None),
        ("GET", "/skills/pool/sample/config", None),
        ("POST", "/skills/pool/refresh", None),
        ("POST", "/skills/pool/import-builtin", {"skill_names": []}),
    ],
)
def test_member_pool_management_denied_before_filesystem(
    tmp_path, monkeypatch, prefix, method, path, body
):
    from qwenpaw.app.routers.skills import router
    from qwenpaw.access.dependencies import get_actor

    monkeypatch.setattr("qwenpaw.constant.WORKING_DIR", str(tmp_path))
    monkeypatch.setenv("QWENPAW_MULTI_USER_ENABLED", "true")
    app = FastAPI()
    app.include_router(router, prefix=prefix)
    app.dependency_overrides[get_actor] = lambda: actor()
    before = list(tmp_path.rglob("*"))
    response = TestClient(app).request(method, prefix + path, json=body)
    assert response.status_code == 403
    assert list(tmp_path.rglob("*")) == before


@pytest.mark.asyncio
async def test_member_import_rejected_without_disk_write(tmp_path):
    from qwenpaw.skills.service import SkillGovernanceService
    from qwenpaw.skills.snapshots import SnapshotStore
    from qwenpaw.access.service import AuthorizationDeniedError

    service = SkillGovernanceService(
        None, SnapshotStore(tmp_path / "snapshots"), tmp_path / "pool"
    )
    with pytest.raises(AuthorizationDeniedError):
        await service.import_existing(actor(), [])
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize(
    "path",
    [
        "/skill-governance/items",
        "/skill-governance/requests",
        "/skill-governance/items/11111111-1111-1111-1111-111111111111/agent-grants",
    ],
)
def test_governance_admin_route_is_independent_of_storage(path):
    from qwenpaw.app.routers.skill_governance import router
    from qwenpaw.access.dependencies import get_actor

    app = FastAPI()
    app.include_router(router, prefix="/api")
    app.dependency_overrides[get_actor] = lambda: actor()
    assert TestClient(app).get("/api" + path).status_code == 403


def test_database_error_is_not_an_empty_or_legacy_catalog(monkeypatch):
    from qwenpaw.app.routers import skill_governance
    from qwenpaw.access.dependencies import get_actor
    from sqlalchemy.exc import OperationalError

    class Unavailable:
        async def list_catalog(self, actor, agent_id):
            raise OperationalError("test", {}, Exception("unavailable"))

    monkeypatch.setattr(skill_governance, "get_skill_service", lambda: Unavailable())
    app = FastAPI()
    app.include_router(skill_governance.router, prefix="/api")
    app.dependency_overrides[get_actor] = lambda: actor()
    response = TestClient(app).get("/api/skill-catalog?agent_id=agentA")
    assert response.status_code == 503
    assert response.json() == {"detail": "skill_authority_unavailable"}


@pytest.mark.parametrize(
    "path",
    [
        "/api/skills/sample/config",
        "/api/skills/hub/config",
        "/api/skills/hub/files/SKILL.md",
        "/api/agents/agentA/skills/hub/config",
        "/api/agents/agentA/skills/hub/files/SKILL.md",
        "/api/agents/agentA/skills/sample/files/SKILL.md",
        "/api/skills/sample",
    ],
)
def test_use_only_cannot_read_skill_configuration(path):
    from qwenpaw.app.agent_context import allowed_agent_roles_for_request
    from qwenpaw.access.agent_repository import AgentResourceRole

    request = Request({"type": "http", "method": "GET", "path": path, "headers": []})
    assert AgentResourceRole.USER not in allowed_agent_roles_for_request(
        request, "agentA"
    )


@pytest.mark.parametrize(
    "path",
    [
        "/api/skills/hub/search",
        "/api/agents/agentA/skills/hub/search",
        "/api/skills/hub/install/status/synthetic-task",
    ],
)
def test_real_hub_read_endpoints_keep_existing_roles(path):
    from qwenpaw.app.agent_context import allowed_agent_roles_for_request
    from qwenpaw.access.agent_repository import AgentResourceRole

    request = Request({"type": "http", "method": "GET", "path": path, "headers": []})
    assert AgentResourceRole.USER in allowed_agent_roles_for_request(request, "agentA")


@pytest.mark.parametrize("kind", ["scan", "database_config"])
def test_governance_external_errors_have_safe_response(monkeypatch, kind):
    from qwenpaw.app.routers import skill_governance
    from qwenpaw.access.dependencies import get_actor
    from qwenpaw.exceptions import SkillScanError
    from qwenpaw.persistence.settings import DatabaseConfigurationError
    from qwenpaw.persistence.mode import StorageMode

    class Unavailable:
        async def list_catalog(self, actor, agent_id):
            if kind == "scan":
                raise SkillScanError(None)
            raise DatabaseConfigurationError(
                "missing_database_url", StorageMode.POSTGRES
            )

    monkeypatch.setattr(skill_governance, "get_skill_service", lambda: Unavailable())
    app = FastAPI()
    app.include_router(skill_governance.router, prefix="/api")
    app.dependency_overrides[get_actor] = lambda: actor()
    response = TestClient(app, raise_server_exceptions=False).get(
        "/api/skill-catalog?agent_id=agentA"
    )
    assert response.status_code == (422 if kind == "scan" else 503)
    assert response.json() == {
        "detail": (
            "skill_security_scan_failed"
            if kind == "scan"
            else "skill_authority_unavailable"
        )
    }
