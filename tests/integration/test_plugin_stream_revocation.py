"""Exercise plugin audience changes on ordinary members' open TCP connections."""

import asyncio
import runpy
from contextlib import AsyncExitStack, asynccontextmanager
from pathlib import Path
from time import perf_counter
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import httpx
import pytest
from alembic import command
from fastapi import APIRouter, FastAPI
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from test_live_stream_revocation import next_event, serve
from test_migrations import _alembic_config
from test_multi_user_identity_storage import _runtime
from tests.fixtures.postgres import DockerPostgresAdmin

from qwenpaw.access import agent_repository
from qwenpaw.access.actor import ActorContext, ActorType
from qwenpaw.access.agent_repository import AgentResourceRole, LegacyAgentRecord
from qwenpaw.app import agent_context, auth, stream_access
from qwenpaw.app.routers import auth as login_routes
from qwenpaw.app.routers import frontend_plugin, plugins
from qwenpaw.config import Config
from qwenpaw.identity.models import PlatformRole
from qwenpaw.pawapp import deps
from qwenpaw.pawapp.task import SSEChannel
from qwenpaw.plugins.governance import (
    AppAudience,
    PluginGovernanceService,
    PluginInstallation,
    PostgresPluginGovernanceRepository,
)
from qwenpaw.plugins.registry import PluginRegistry


@pytest.mark.asyncio
async def test_kanban_audience_revocation_during_live_stream(
    postgres_test_schema, monkeypatch, tmp_path, record_property
):
    await asyncio.to_thread(command.upgrade, _alembic_config(postgres_test_schema), "head")
    schema = postgres_test_schema.name
    engine = create_async_engine(postgres_test_schema.async_url())
    factory = async_sessionmaker(engine, expire_on_commit=False)

    @asynccontextmanager
    async def sessions():
        async with factory.begin() as session:
            yield session

    runtime = _runtime(schema, sessions)
    agents = agent_repository.PostgresAgentRepository(schema=schema, session_factory=sessions)
    service = PluginGovernanceService(
        PostgresPluginGovernanceRepository(schema=schema, session_factory=sessions)
    )
    monkeypatch.setenv("QWENPAW_MULTI_USER_ENABLED", "true")
    monkeypatch.setenv("QWENPAW_SESSION_COOKIE_SECURE", "false")
    monkeypatch.setattr("qwenpaw.constant.WORKING_DIR", tmp_path)
    for module in (auth, login_routes, stream_access):
        monkeypatch.setattr(module, "get_identity_runtime", lambda: runtime)
    for module in (agent_repository, stream_access):
        monkeypatch.setattr(module, "PostgresAgentRepository", lambda **_: agents)
    for module in (plugins, frontend_plugin):
        monkeypatch.setattr(module, "get_plugin_governance_service", lambda: service)
    monkeypatch.setattr(deps, "_plugin_governance_service", lambda: service)
    config = Config.model_validate(
        {
            "agents": {
                "active_agent": "office",
                "profiles": {
                    "office": {"id": "office", "workspace_dir": str(tmp_path)},
                },
            }
        }
    )
    monkeypatch.setattr(agent_context, "load_config", lambda: config)
    monkeypatch.setattr("qwenpaw.config.load_config", lambda: config)
    monkeypatch.setattr(auth, "_auth_config_cache", (0, None, []))
    app = FastAPI()
    app.add_middleware(stream_access.StreamAccessMiddleware)
    app.add_middleware(auth.AuthMiddleware)
    app.state.multi_agent_manager = SimpleNamespace(
        get_agent=AsyncMock(return_value=SimpleNamespace(agent_id="office"))
    )
    for module in (login_routes, plugins):
        app.include_router(module.router, prefix="/api")
    registry = PluginRegistry()
    registry.set_plugin_http_app(app)
    plugin_file = Path(__file__).resolve().parents[2] / "plugins/apps/agent-kanban/backend/main.py"
    kanban = runpy.run_path(str(plugin_file))
    registry.register_http_router("agent-kanban", kanban["router"], prefix="/plugins/agent-kanban")
    control = SSEChannel()
    control_router = APIRouter()

    @control_router.get("/events")
    async def events():
        return StreamingResponse(control.__aiter__(), media_type="text/event-stream")

    registry.register_http_router("control", control_router, prefix="/control")
    try:
        owner = await runtime.users.create_user("owner", "owner-password", PlatformRole.ADMIN)
        admin = ActorContext(owner.id, ActorType.USER, PlatformRole.ADMIN, True, "seed")
        await agents.register_owner(
            agent=LegacyAgentRecord("office", "Office", "", str(tmp_path), "active"),
            owner_user_id=owner.id,
        )
        members = []
        for name in ("alpha", "bravo"):
            user = await runtime.users.create_user(name, f"{name}-password", PlatformRole.MEMBER)
            await agents.grant_member(
                agent_key="office", user_id=user.id, role=AgentResourceRole.USER, actor=admin
            )
            members.append(user)
        for plugin_id in ("agent-kanban", "control"):
            await service.register_installation(
                admin,
                PluginInstallation(uuid4(), plugin_id, "1", "app", "active"),
                source_type="path",
                source_ref=plugin_id,
                content_hash="a" * 64,
                audience=AppAudience("all_members"),
            )

        async with serve(app) as url, AsyncExitStack() as stack:

            async def login(user):
                client = await stack.enter_async_context(
                    httpx.AsyncClient(base_url=url, trust_env=False, timeout=10)
                )
                response = await client.post(
                    "/api/auth/login",
                    json={"username": user.username, "password": f"{user.username}-password"},
                )
                response.raise_for_status()
                client.headers.update(
                    {"Authorization": f"Bearer {response.json()['token']}", "X-Agent-Id": "office"}
                )
                return client

            alpha, bravo, owner_client = await asyncio.gather(
                *(login(user) for user in (*members, owner))
            )
            base = "/api/frontend_plugin/agent-kanban/runtime/issues"
            issues = []
            for client, member in zip((alpha, bravo), members):
                created = await client.post(
                    base, json={"title": member.username, "status": "backlog"}
                )
                created.raise_for_status()
                issues.append(created.json()["id"])

            async def open_stream(client, path):
                response = await stack.enter_async_context(client.stream("GET", path))
                response.raise_for_status()
                return response.aiter_lines()

            async def transmit(channel, lines, text):
                await channel.send_event({"message": text})
                assert await next_event(lines) == {"message": text}

            async def closed(lines, seconds):
                async with asyncio.timeout(seconds):
                    assert not [line async for line in lines if line.startswith("data:")]

            async def audience(selected):
                response = await owner_client.put(
                    "/api/plugins/agent-kanban/audience",
                    json={
                        "mode": "selected_users",
                        "selected_user_ids": [str(user.id) for user in selected],
                    },
                )
                response.raise_for_status()

            alpha_path = f"{base}/{issues[0]}/stream"
            alpha_lines = await open_stream(alpha, alpha_path)
            # The original plugin URL and the Worker alias have identical governance.
            bravo_lines = await open_stream(
                bravo, f"/api/plugins/agent-kanban/issues/{issues[1]}/stream"
            )
            control_lines = await open_stream(alpha, "/api/control/events")
            channels = kanban["_CHANNELS"]
            alpha_channel, bravo_channel = (channels[issue] for issue in issues)
            await transmit(alpha_channel, alpha_lines, "alpha-before")
            await transmit(bravo_channel, bravo_lines, "bravo-before")
            await transmit(control, control_lines, "other-plugin-before")

            await audience(members[1:])
            start = perf_counter()
            await alpha_channel.send_event({"message": "alpha-after"})
            await closed(alpha_lines, 3)
            record_property("plugin_local_close_ms", round((perf_counter() - start) * 1000, 2))
            assert issues[0] not in channels
            assert (await alpha.get(alpha_path)).status_code == 404
            await transmit(bravo_channel, bravo_lines, "bravo-after")
            await transmit(control, control_lines, "other-plugin-after")

            # Grant both users, reopen, then change the grant in a separate psql process.
            await audience(members)
            alpha_lines = await open_stream(alpha, alpha_path)
            await transmit(channels[issues[0]], alpha_lines, "alpha-reopened")
            await asyncio.to_thread(
                DockerPostgresAdmin(postgres_test_schema.config).execute,
                f"""UPDATE "{schema}".app_grants SET enabled=false
                    WHERE plugin_installation_id=(SELECT id FROM "{schema}".plugin_installations WHERE plugin_id='agent-kanban')
                      AND subject_type='user' AND subject_id='{members[0].id}'""",
            )
            start = perf_counter()
            await closed(alpha_lines, 7)
            record_property("plugin_external_close_ms", round((perf_counter() - start) * 1000, 2))
            assert issues[0] not in channels
            assert (await alpha.get(alpha_path)).status_code == 404
            await transmit(bravo_channel, bravo_lines, "bravo-after-external")
            await transmit(control, control_lines, "other-plugin-after-external")
            await service.set_status(admin, "agent-kanban", enabled=False)
            await closed(bravo_lines, 3)
            await transmit(control, control_lines, "other-plugin-after-disable")
    finally:
        control.close()
        await engine.dispose()
