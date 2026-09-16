"""插件平台治理、用户授权和 Agent 设置权限矩阵。"""

from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from qwenpaw.access.actor import ActorContext, ActorType
from qwenpaw.access.agent_repository import (
    AgentAccessRecord,
    AgentResourceRole,
    AgentVisibility,
    agent_database_id,
)
from qwenpaw.access.service import AuthorizationDeniedError
from qwenpaw.app.routers import frontend_plugin, pawapps
from qwenpaw.app.routers import plugins as plugin_router
from qwenpaw.identity.models import PlatformRole
from qwenpaw.pawapp.deps import get_ctx
from qwenpaw.plugins.governance import (
    AppAudience,
    PluginAccessError,
    PluginGovernanceService,
    PluginInstallation,
)


def actor(role: PlatformRole, user_id: UUID | None = None) -> ActorContext:
    return ActorContext(
        user_id=user_id or uuid4(),
        actor_type=ActorType.USER,
        platform_role=role,
        admin_mode=False,
        request_id="plugin-governance-test",
    )


class MemoryPluginRepository:
    def __init__(self, installations, grants=None) -> None:
        self.installations = {row.plugin_id: row for row in installations}
        self.grants = grants or {}
        self.replacements = []
        self.settings = {}
        self.status_changes = []
        self.registrations = []
        self.deleted = []

    async def list_installations(self):
        return list(self.installations.values())

    async def get_installation(self, plugin_id):
        return self.installations.get(plugin_id)

    async def is_user_granted(self, installation_id, user_id):
        grant = self.grants.get(installation_id, set())
        return "all_members" in grant or user_id in grant

    async def replace_audience(self, installation_id, audience, actor_id):
        self.replacements.append((installation_id, audience, actor_id))
        self.grants[installation_id] = (
            {"all_members"}
            if audience.mode == "all_members"
            else set(audience.selected_user_ids)
        )

    async def save_agent_setting(
        self, agent_id, installation_id, enabled, config, actor_id
    ):
        self.settings[(agent_id, installation_id)] = {
            "enabled": enabled,
            "config": config,
            "updated_by": actor_id,
        }
        return self.settings[(agent_id, installation_id)]

    async def get_agent_setting(self, agent_id, installation_id):
        return self.settings.get(
            (agent_id, installation_id), {"enabled": False, "config": {}}
        )

    async def set_status(self, installation_id, status, actor_id):
        current = next(
            row for row in self.installations.values() if row.id == installation_id
        )
        updated = replace(current, status=status)
        self.installations[current.plugin_id] = updated
        self.status_changes.append((installation_id, status, actor_id))
        return updated

    async def register_installation(
        self, candidate, source_type, source_ref, content_hash, actor_id, audience
    ):
        self.registrations.append(
            (candidate, source_type, source_ref, content_hash, actor_id)
        )
        self.installations[candidate.plugin_id] = candidate
        await self.replace_audience(candidate.id, audience, actor_id)
        return candidate

    async def delete_installation(self, installation_id, actor_id):
        self.deleted.append((installation_id, actor_id))
        for plugin_id, row in list(self.installations.items()):
            if row.id == installation_id:
                del self.installations[plugin_id]


def installation(*, status: str = "active") -> PluginInstallation:
    return PluginInstallation(
        id=uuid4(),
        plugin_id="demo-app",
        version="1.2.3",
        plugin_type="app",
        status=status,
    )


@pytest.mark.asyncio
async def test_member_cannot_replace_global_plugin_audience() -> None:
    row = installation()
    repo = MemoryPluginRepository([row])
    service = PluginGovernanceService(repo)

    with pytest.raises(AuthorizationDeniedError):
        await service.replace_audience(
            actor(PlatformRole.MEMBER),
            row.plugin_id,
            AppAudience(mode="all_members"),
        )

    assert repo.replacements == []


@pytest.mark.asyncio
async def test_admin_lists_all_installations_for_governance() -> None:
    rows = [
        installation(),
        replace(installation(), plugin_id="disabled", status="disabled"),
    ]
    service = PluginGovernanceService(MemoryPluginRepository(rows))

    result = await service.list_manageable(actor(PlatformRole.ADMIN))

    assert [row.plugin_id for row in result] == ["demo-app", "disabled"]


@pytest.mark.asyncio
async def test_member_cannot_list_global_installations() -> None:
    service = PluginGovernanceService(MemoryPluginRepository([installation()]))

    with pytest.raises(AuthorizationDeniedError):
        await service.list_manageable(actor(PlatformRole.MEMBER))


@pytest.mark.asyncio
async def test_all_members_grant_exposes_only_active_plugin() -> None:
    user = actor(PlatformRole.MEMBER)
    active = installation()
    disabled = replace(active, id=uuid4(), plugin_id="disabled-app", status="disabled")
    repo = MemoryPluginRepository(
        [active, disabled],
        {
            active.id: {"all_members"},
            disabled.id: {"all_members"},
        },
    )

    visible = await PluginGovernanceService(repo).list_authorized(user)

    assert [row.plugin_id for row in visible] == ["demo-app"]


@pytest.mark.asyncio
async def test_selected_users_grant_does_not_leak_to_other_member() -> None:
    allowed = actor(PlatformRole.MEMBER)
    denied = actor(PlatformRole.MEMBER)
    row = installation()
    repo = MemoryPluginRepository([row], {row.id: {allowed.user_id}})
    service = PluginGovernanceService(repo)

    assert [item.plugin_id for item in await service.list_authorized(allowed)] == [
        "demo-app"
    ]
    assert await service.list_authorized(denied) == []
    with pytest.raises(PluginAccessError, match="plugin_unavailable_or_forbidden"):
        await service.require_app_access(denied, row.plugin_id)


@pytest.mark.asyncio
async def test_admin_replaces_audience_with_normalized_selected_users() -> None:
    admin = actor(PlatformRole.ADMIN)
    first, second = uuid4(), uuid4()
    row = installation()
    repo = MemoryPluginRepository([row])
    service = PluginGovernanceService(repo)

    await service.replace_audience(
        admin,
        row.plugin_id,
        AppAudience(
            mode="selected_users",
            selected_user_ids=(second, first, second),
        ),
    )

    _, saved, saved_by = repo.replacements[0]
    assert saved.mode == "selected_users"
    assert saved.selected_user_ids == tuple(sorted((first, second), key=str))
    assert saved_by == admin.user_id


@pytest.mark.asyncio
async def test_admin_disables_and_enables_plugin_without_losing_grants() -> None:
    admin = actor(PlatformRole.ADMIN)
    member = actor(PlatformRole.MEMBER)
    row = installation()
    repo = MemoryPluginRepository([row], {row.id: {member.user_id}})
    service = PluginGovernanceService(repo)

    disabled = await service.set_status(admin, row.plugin_id, enabled=False)
    assert disabled.status == "disabled"
    assert await service.list_authorized(member) == []

    active = await service.set_status(admin, row.plugin_id, enabled=True)
    assert active.status == "active"
    assert [item.plugin_id for item in await service.list_authorized(member)] == [
        "demo-app"
    ]
    assert repo.grants[row.id] == {member.user_id}


@pytest.mark.asyncio
async def test_member_cannot_change_global_plugin_status() -> None:
    row = installation()
    repo = MemoryPluginRepository([row])

    with pytest.raises(AuthorizationDeniedError):
        await PluginGovernanceService(repo).set_status(
            actor(PlatformRole.MEMBER), row.plugin_id, enabled=False
        )

    assert repo.status_changes == []


@pytest.mark.asyncio
async def test_admin_registers_installation_and_explicit_empty_audience() -> None:
    admin = actor(PlatformRole.ADMIN)
    candidate = installation()
    repo = MemoryPluginRepository([])
    service = PluginGovernanceService(repo)

    saved = await service.register_installation(
        admin,
        candidate,
        source_type="url",
        source_ref="https://plugins.invalid/demo.zip",
        content_hash="a" * 64,
        audience=AppAudience(mode="selected_users"),
    )

    assert saved == candidate
    assert repo.registrations[0][1:4] == (
        "url",
        "https://plugins.invalid/demo.zip",
        "a" * 64,
    )
    assert repo.replacements[0][1] == AppAudience(mode="selected_users")


@pytest.mark.asyncio
async def test_member_cannot_register_plugin_installation() -> None:
    repo = MemoryPluginRepository([])

    with pytest.raises(AuthorizationDeniedError):
        await PluginGovernanceService(repo).register_installation(
            actor(PlatformRole.MEMBER),
            installation(),
            source_type="upload",
            source_ref="upload.zip",
            content_hash="b" * 64,
            audience=AppAudience(mode="all_members"),
        )

    assert repo.registrations == []


@pytest.mark.asyncio
async def test_admin_uninstall_uses_revoked_intermediate_state_then_deletes() -> None:
    admin = actor(PlatformRole.ADMIN)
    row = installation()
    repo = MemoryPluginRepository([row], {row.id: {"all_members"}})
    service = PluginGovernanceService(repo)

    pending = await service.begin_uninstall(admin, row.plugin_id)
    assert pending.status == "uninstalling"
    assert await service.list_authorized(actor(PlatformRole.MEMBER)) == []

    await service.complete_uninstall(admin, row.plugin_id)
    assert repo.deleted == [(row.id, admin.user_id)]
    assert await repo.get_installation(row.plugin_id) is None


@pytest.mark.asyncio
async def test_failed_uninstall_stays_revoked_and_diagnosable() -> None:
    admin = actor(PlatformRole.ADMIN)
    row = installation()
    repo = MemoryPluginRepository([row], {row.id: {"all_members"}})
    service = PluginGovernanceService(repo)
    await service.begin_uninstall(admin, row.plugin_id)

    failed = await service.fail_uninstall(admin, row.plugin_id)

    assert failed.status == "failed"
    assert await service.list_authorized(actor(PlatformRole.MEMBER)) == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "role",
    [AgentResourceRole.OWNER, AgentResourceRole.COLLABORATOR],
)
async def test_agent_editor_can_save_authorized_active_plugin_setting(role) -> None:
    user = actor(PlatformRole.MEMBER)
    row = installation()
    repo = MemoryPluginRepository([row], {row.id: {user.user_id}})
    service = PluginGovernanceService(repo)
    access = SimpleNamespace(agent_id=uuid4(), role=role, historical_read_only=False)

    saved = await service.save_agent_setting(
        user,
        access,
        row.plugin_id,
        enabled=True,
        config={"mode": "safe"},
    )

    assert saved == {
        "enabled": True,
        "config": {"mode": "safe"},
        "updated_by": user.user_id,
    }


@pytest.mark.asyncio
async def test_agent_setting_uses_trusted_agent_access_key() -> None:
    user = actor(PlatformRole.MEMBER)
    row = installation()
    repo = MemoryPluginRepository([row], {row.id: {user.user_id}})
    access = AgentAccessRecord(
        agent_key="trusted-agent",
        owner_user_id=user.user_id,
        role=AgentResourceRole.OWNER,
        status="active",
        visibility=AgentVisibility.PRIVATE,
    )

    await PluginGovernanceService(repo).save_agent_setting(
        user, access, row.plugin_id, enabled=True, config={}
    )

    assert (agent_database_id("trusted-agent"), row.id) in repo.settings


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("role", "status", "granted"),
    [
        (AgentResourceRole.USER, "active", True),
        (AgentResourceRole.OWNER, "disabled", True),
        (AgentResourceRole.OWNER, "active", False),
    ],
)
async def test_agent_setting_rejects_non_editor_disabled_or_ungranted_plugin(
    role, status, granted
) -> None:
    user = actor(PlatformRole.MEMBER)
    row = installation(status=status)
    repo = MemoryPluginRepository([row], {row.id: {user.user_id}} if granted else {})
    access = SimpleNamespace(agent_id=uuid4(), role=role, historical_read_only=False)

    with pytest.raises(PluginAccessError):
        await PluginGovernanceService(repo).save_agent_setting(
            user,
            access,
            row.plugin_id,
            enabled=True,
            config={},
        )

    assert repo.settings == {}


def plugin_http(role: PlatformRole) -> TestClient:
    app = FastAPI()

    @app.middleware("http")
    async def actor_middleware(request, call_next):
        request.state.actor = actor(role)
        return await call_next(request)

    app.include_router(plugin_router.router)
    return TestClient(app)


@pytest.mark.parametrize(
    ("method", "path", "body"),
    [
        ("get", "/plugins", None),
        ("get", "/plugins/catalog", None),
        ("post", "/plugins/install", {"source": "C:/synthetic-plugin"}),
        ("delete", "/plugins/demo-app", None),
        ("get", "/plugins/demo-app/status", None),
    ],
)
def test_member_cannot_reach_plugin_governance_routes(method, path, body) -> None:
    response = plugin_http(PlatformRole.MEMBER).request(method, path, json=body)

    assert response.status_code == 403
    assert response.json() == {"detail": "forbidden"}


class AuthorizedService:
    def __init__(self, allowed: set[str]) -> None:
        self.allowed = allowed

    async def list_authorized(self, _actor):
        return [
            replace(installation(), plugin_id=plugin_id)
            for plugin_id in sorted(self.allowed)
        ]

    async def require_app_access(self, _actor, plugin_id):
        if plugin_id not in self.allowed:
            raise PluginAccessError("plugin_unavailable_or_forbidden")
        return replace(installation(), plugin_id=plugin_id)


class FrontendLoader:
    def __init__(self) -> None:
        entry = SimpleNamespace(frontend="dist/index.js")
        self.records = {
            plugin_id: SimpleNamespace(
                manifest=SimpleNamespace(
                    id=plugin_id,
                    name=plugin_id,
                    version="1.0.0",
                    description="",
                    author="test",
                    plugin_type="app",
                    entry=entry,
                    meta={"pawapp": {"category": "test"}},
                ),
                enabled=True,
            )
            for plugin_id in ("allowed-app", "denied-app")
        }

    def get_all_loaded_plugins(self):
        return self.records

    def get_loaded_plugin(self, plugin_id):
        return self.records.get(plugin_id)


def test_frontend_plugin_list_only_returns_actor_authorized_bundles(
    monkeypatch,
) -> None:
    app = FastAPI()
    app.state.plugin_loader = FrontendLoader()

    @app.middleware("http")
    async def actor_middleware(request, call_next):
        request.state.actor = actor(PlatformRole.MEMBER)
        return await call_next(request)

    monkeypatch.setattr(
        frontend_plugin, "is_multi_user_enabled", lambda: True, raising=False
    )
    monkeypatch.setattr(
        frontend_plugin,
        "get_plugin_governance_service",
        lambda: AuthorizedService({"allowed-app"}),
        raising=False,
    )
    app.include_router(frontend_plugin.router)

    response = TestClient(app).get("/frontend_plugin")

    assert response.status_code == 200
    assert [item["id"] for item in response.json()] == ["allowed-app"]


def test_pawapp_list_and_detail_hide_ungranted_application(monkeypatch) -> None:
    app = FastAPI()
    loader = FrontendLoader()
    app.state.plugin_loader = loader
    app.state.plugin_registry = SimpleNamespace(
        get_all_plugin_manifests=lambda: {
            key: {
                "id": record.manifest.id,
                "name": record.manifest.name,
                "version": record.manifest.version,
                "meta": record.manifest.meta,
            }
            for key, record in loader.records.items()
        }
    )

    @app.middleware("http")
    async def actor_middleware(request, call_next):
        request.state.actor = actor(PlatformRole.MEMBER)
        return await call_next(request)

    monkeypatch.setattr(pawapps, "is_multi_user_enabled", lambda: True, raising=False)
    monkeypatch.setattr(
        pawapps,
        "get_plugin_governance_service",
        lambda: AuthorizedService({"allowed-app"}),
        raising=False,
    )
    app.include_router(pawapps.router)
    client = TestClient(app)

    listing = client.get("/pawapps")
    denied = client.get("/pawapps/denied-app")

    assert [item["id"] for item in listing.json()["apps"]] == ["allowed-app"]
    assert denied.status_code == 404


def test_admin_install_persists_explicit_audience_after_loader_success(
    monkeypatch,
) -> None:
    admin = actor(PlatformRole.ADMIN)
    captured = []
    record = SimpleNamespace(
        manifest=SimpleNamespace(
            id="demo-app",
            name="Demo",
            version="2.0.0",
            description="demo",
            author="tester",
            plugin_type="app",
        ),
        source_path=__file__,
    )

    class CaptureService:
        async def register_installation(self, *args, **kwargs):
            captured.append((args, kwargs))

    async def loaded(*_args, **_kwargs):
        return record

    app = FastAPI()
    app.state.plugin_loader = object()

    @app.middleware("http")
    async def actor_middleware(request, call_next):
        request.state.actor = admin
        return await call_next(request)

    monkeypatch.setattr(
        plugin_router,
        "_load_plugin_with_optional_force_reinstall",
        loaded,
    )
    monkeypatch.setattr(
        plugin_router, "is_multi_user_enabled", lambda: True, raising=False
    )
    monkeypatch.setattr(
        plugin_router,
        "get_plugin_governance_service",
        lambda: CaptureService(),
        raising=False,
    )
    app.include_router(plugin_router.router)

    response = TestClient(app).post(
        "/plugins/install",
        json={
            "source": __file__,
            "audience_mode": "selected_users",
            "selected_user_ids": [str(admin.user_id)],
        },
    )

    assert response.status_code == 200
    _, kwargs = captured[0]
    assert kwargs["audience"] == AppAudience(
        mode="selected_users", selected_user_ids=(admin.user_id,)
    )
    assert kwargs["source_type"] == "path"


@pytest.mark.asyncio
async def test_governance_failure_compensates_loaded_plugin(monkeypatch) -> None:
    record = SimpleNamespace(manifest=SimpleNamespace(id="failed-app"))
    unloaded = []

    class Loader:
        async def unload_plugin(self, plugin_id, *, delete_files):
            unloaded.append((plugin_id, delete_files))

    async def failed(*_args, **_kwargs):
        raise PluginAccessError("plugin_audience_user_invalid")

    monkeypatch.setattr(plugin_router, "_persist_plugin_installation", failed)

    with pytest.raises(PluginAccessError, match="plugin_audience_user_invalid"):
        await plugin_router._persist_or_compensate_plugin_installation(
            SimpleNamespace(),
            Loader(),
            record,
            source_type="upload",
            source_ref="failed.zip",
            audience=AppAudience(mode="selected_users"),
        )

    assert unloaded == [("failed-app", True)]


def test_admin_updates_audience_and_global_status_through_api(monkeypatch) -> None:
    admin = actor(PlatformRole.ADMIN)
    calls = []

    class CaptureService:
        async def replace_audience(self, current, plugin_id, audience):
            calls.append(("audience", current, plugin_id, audience))

        async def set_status(self, current, plugin_id, *, enabled):
            calls.append(("status", current, plugin_id, enabled))
            return replace(
                installation(),
                plugin_id=plugin_id,
                status="active" if enabled else "disabled",
            )

    app = FastAPI()
    app.state.plugin_loader = FrontendLoader()

    @app.middleware("http")
    async def actor_middleware(request, call_next):
        request.state.actor = admin
        return await call_next(request)

    monkeypatch.setattr(
        plugin_router,
        "get_plugin_governance_service",
        lambda: CaptureService(),
    )
    app.include_router(plugin_router.router)
    client = TestClient(app)

    audience = client.put(
        "/plugins/allowed-app/audience",
        json={"mode": "selected_users", "selected_user_ids": [str(admin.user_id)]},
    )
    disabled = client.post("/plugins/allowed-app/disable")
    enabled = client.post("/plugins/allowed-app/enable")

    assert audience.status_code == 200
    assert disabled.json()["status"] == "disabled"
    assert enabled.json()["status"] == "active"
    assert calls[0][3] == AppAudience(
        mode="selected_users", selected_user_ids=(admin.user_id,)
    )


def test_agent_setting_api_ignores_body_agent_id_and_uses_authorized_context(
    monkeypatch,
) -> None:
    member = actor(PlatformRole.MEMBER)
    saved = []

    class CaptureService:
        async def save_agent_setting(
            self, current, access, plugin_id, *, enabled, config
        ):
            saved.append((current, access.agent_key, plugin_id, enabled, config))
            return {"enabled": enabled, "config": config}

    async def trusted_agent(request, agent_id=None):
        assert agent_id is None
        request.state.agent_access = AgentAccessRecord(
            agent_key="trusted-agent",
            owner_user_id=member.user_id,
            role=AgentResourceRole.OWNER,
            status="active",
        )
        return SimpleNamespace(agent_id="trusted-agent")

    app = FastAPI()

    @app.middleware("http")
    async def actor_middleware(request, call_next):
        request.state.actor = member
        return await call_next(request)

    monkeypatch.setattr(
        plugin_router, "get_plugin_governance_service", lambda: CaptureService()
    )
    monkeypatch.setattr(
        plugin_router, "get_agent_for_request", trusted_agent, raising=False
    )
    app.include_router(plugin_router.agent_settings_router)

    response = TestClient(app).put(
        "/plugins/demo-app/agent-setting",
        headers={"X-Agent-Id": "trusted-agent"},
        json={"enabled": True, "config": {"mode": "safe"}, "agent_id": "forged"},
    )

    assert response.status_code == 200
    assert saved[0][1:] == (
        "trusted-agent",
        "demo-app",
        True,
        {"mode": "safe"},
    )


def test_agent_plugin_config_rejects_undeclared_fields() -> None:
    request = SimpleNamespace(
        app=SimpleNamespace(
            state=SimpleNamespace(
                plugin_loader=SimpleNamespace(
                    get_loaded_plugin=lambda _plugin_id: SimpleNamespace(
                        manifest=SimpleNamespace(
                            meta={
                                "settings": [{"name": "theme"}],
                                "tools": [{"config_fields": [{"name": "api_key"}]}],
                            }
                        )
                    )
                )
            )
        )
    )

    plugin_router._validate_agent_plugin_config(
        request, "demo-app", {"theme": "dark", "api_key": "secret"}
    )
    with pytest.raises(HTTPException) as exc_info:
        plugin_router._validate_agent_plugin_config(
            request, "demo-app", {"forged": True}
        )
    assert exc_info.value.status_code == 422


@pytest.mark.asyncio
async def test_pawapp_context_uses_actor_and_ignores_forged_identity(
    monkeypatch,
) -> None:
    member = actor(PlatformRole.MEMBER)
    request = SimpleNamespace(
        state=SimpleNamespace(actor=member, app_id="demo-app"),
        app=SimpleNamespace(state=SimpleNamespace()),
        query_params={"user_id": "forged-user", "agent_id": "forged-agent"},
        headers={"X-User-Id": "forged-header", "X-Agent-Id": "forged-agent-header"},
        url=SimpleNamespace(path="/api/demo-app/data"),
    )

    class AllowService:
        async def require_app_access(self, current, plugin_id):
            assert current == member
            assert plugin_id == "demo-app"
            return installation()

    monkeypatch.setattr("qwenpaw.pawapp.deps.is_multi_user_enabled", lambda: True)
    monkeypatch.setattr(
        "qwenpaw.pawapp.deps._plugin_governance_service", lambda: AllowService()
    )
    monkeypatch.setattr("qwenpaw.pawapp.deps._get_session", lambda _request: None)

    context = await get_ctx(request)

    assert context.user_id == str(member.user_id)
    assert context.agent_id == "default"
    assert context.storage._namespace == f"pawapp:demo-app:{member.user_id}"
