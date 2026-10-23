# -*- coding: utf-8 -*-
"""Actual lifespan construction and loaded retired-Workspace fencing.

Migration/telemetry and unused legacy platform inventory are isolated inputs.
All Service/Sessions/Loader/Manager/Workspace constructors and their lifecycle
methods delegate to production; no started flag or binding is synthesized.
"""

import asyncio
from hashlib import sha256
from importlib import import_module
from pathlib import Path
import sys

from fastapi import FastAPI
import pytest

from management_process_suite import (
    KEY,
    management_runtime,
    local_management_http,
)
from wechat_w2_config_support import write_profiles
from wechat_w2_session_suite import qr, narrow_legacy_test_guard

__all__ = ["qr", "narrow_legacy_test_guard"]


@pytest.mark.asyncio
async def test_actual_lifespan_constructs_single_service_sessions_and_exact_bindings(
    tmp_path, monkeypatch
):
    from qwenpaw.app.channels.management import ChannelManagementService
    from qwenpaw.app.channels.qrcode_sessions import ChannelQRCodeSessions
    from qwenpaw.app.workspace_registry import WorkspaceRegistry
    from qwenpaw.plugins.channel_adapter import ChannelRuntimeSettings
    from qwenpaw.plugins.loader import PluginLoader
    from qwenpaw.plugins.registry import PluginRegistry

    monkeypatch.setenv("QWENPAW_TELEMETRY_DISABLED", "1")
    monkeypatch.setattr(PluginRegistry, "_instance", None)
    write_profiles(tmp_path, monkeypatch, "wechat", {})
    monkeypatch.setattr(
        "qwenpaw.config.utils.get_plugins_dir", lambda: tmp_path / "installed"
    )
    app_module = import_module("qwenpaw.app._app")
    # Reuse the existing real-lifespan tests' migration isolation boundary;
    # unrelated historical filesystem migrations do not establish W3 wiring.
    for name in (
        "migrate_legacy_workspace_to_default_agent",
        "migrate_legacy_skills_to_skill_pool",
        "ensure_default_agent_exists",
        "ensure_qa_agent_exists",
    ):
        monkeypatch.setattr(app_module, name, lambda: None)
    runtime = ChannelRuntimeSettings(
        python_executable=sys.executable,
        support_root=Path(__file__).resolve().parents[3] / "src",
        qwenpaw_version="2.2.2b4",
        selected_channels=frozenset(),
    )
    monkeypatch.setattr(
        "qwenpaw.plugins.official_channels.resolve_default_channel_runtime",
        lambda: runtime,
    )
    monkeypatch.setattr(app_module.ProviderManager, "_instance", None)
    monkeypatch.setattr(app_module.LocalModelManager, "_instance", None)
    made = {name: [] for name in ("loader", "service", "sessions", "manager")}
    for cls, name in (
        (PluginLoader, "loader"),
        (ChannelManagementService, "service"),
        (ChannelQRCodeSessions, "sessions"),
        (WorkspaceRegistry, "manager"),
    ):
        original = cls.__init__

        def construct(
            instance, *args, _original=original, _name=name, **kwargs
        ):
            _original(instance, *args, **kwargs)
            made[_name].append(instance)

        monkeypatch.setattr(cls, "__init__", construct)
    entered, hold, cancelled = (
        asyncio.Event(),
        asyncio.Event(),
        asyncio.Event(),
    )
    original_load = PluginLoader.load_all_plugins
    calls = []

    async def gated_load(loader, *args, **kwargs):
        calls.append((loader, kwargs))
        entered.set()
        try:
            await hold.wait()
            return await original_load(loader, *args, **kwargs)
        except asyncio.CancelledError:
            cancelled.set()
            raise

    monkeypatch.setattr(PluginLoader, "load_all_plugins", gated_load)
    closed = []
    for cls, name in (
        (ChannelQRCodeSessions, "sessions"),
        (ChannelManagementService, "service"),
    ):
        original_close = cls.aclose

        async def close(instance, _original=original_close, _name=name):
            closed.append((_name, instance))
            return await _original(instance)

        monkeypatch.setattr(cls, "aclose", close)
    app = FastAPI(lifespan=app_module.lifespan)
    async with app.router.lifespan_context(app):
        async with asyncio.timeout(10):
            await entered.wait()
        assert {name: len(instances) for name, instances in made.items()} == {
            "loader": 1,
            "service": 1,
            "sessions": 1,
            "manager": 1,
        }
        loader, service, sessions, manager = (
            made[name][0]
            for name in ("loader", "service", "sessions", "manager")
        )
        assert calls == [
            (
                loader,
                {
                    "configs": {},
                    "types": ["channel", "memory", "hub"],
                    "activate": False,
                },
            )
        ]
        assert app.state.plugin_loader is loader
        assert app.state.plugin_registry is loader.registry
        assert (
            app.state.channel_management is service
            and service._loader is loader
        )
        assert app.state.channel_qrcode_sessions is sessions
        assert sessions._loader is loader and sessions._management is service
        assert (
            app.state.workspace_registry
            is app.state.multi_agent_manager
            is manager
        )
        assert manager.channel_qrcode_sessions is sessions
        assert loader.registry._workspace_manager is manager
        assert (
            not manager.agents and not sessions._closed and not service._closed
        )
    assert cancelled.is_set()
    assert closed[:2] == [("sessions", sessions), ("service", service)]
    assert sessions._closed and service._closed and manager._closing
    assert all(
        instance is sessions for name, instance in closed if name == "sessions"
    )
    assert all(
        instance is service for name, instance in closed if name == "service"
    )


@pytest.mark.asyncio
async def test_loaded_retired_workspace_stop_preserves_new_same_id_session_and_claims(
    qr, monkeypatch, tmp_path
):
    from qwenpaw.app.channels import registry as channel_registry
    from qwenpaw.app.channels.wechat_auth_custody import reserve_wechat_auth
    from qwenpaw.app.multi_agent_manager import MultiAgentManager
    from qwenpaw.app.workspace import Workspace
    from qwenpaw.config.config import load_agent_config, save_agent_config

    monkeypatch.setenv("QWENPAW_TELEMETRY_DISABLED", "1")
    # No platform is enabled. Keep console's real class as the sole unrelated
    # legacy inventory item, so this host lifecycle proof imports no SDK.
    monkeypatch.setattr(
        channel_registry,
        "_BUILTIN_SPECS",
        {"console": channel_registry._BUILTIN_SPECS["console"]},
    )
    monkeypatch.setattr(channel_registry, "_BUILTIN_CHANNEL_CACHE", None)
    monkeypatch.setattr(
        channel_registry, "_BUILTIN_CHANNEL_CACHE_SELECTION", None
    )
    for agent_id in qr.paths:
        profile = load_agent_config(agent_id)
        for channel in type(profile.channels).model_fields:
            value = getattr(profile.channels, channel)
            if hasattr(value, "enabled"):
                value.enabled = False
        profile.running.memory_manager_backend = "none"
        save_agent_config(agent_id, profile)
    manager = MultiAgentManager()
    manager.channel_qrcode_sessions = qr.sessions
    qr.rt.loader.registry.set_workspace_manager(manager)
    old = await manager.get_agent("A")
    assert isinstance(old, Workspace) and old._started
    assert old.session is not None and old.channel_manager is not None
    assert old.driver_manager is not None and old.cron_manager is not None
    entered, release = asyncio.Event(), asyncio.Event()
    original_stop = old.stop
    stop_calls = []

    async def gated_real_stop(*args, **kwargs):
        stop_calls.append((args, kwargs))
        entered.set()
        await release.wait()
        return await original_stop(*args, **kwargs)

    monkeypatch.setattr(old, "stop", gated_real_stop)
    reloading = asyncio.create_task(manager.reload_agent("A"))
    try:
        async with asyncio.timeout(10):
            await entered.wait()
        fresh = manager.agents["A"]
        assert isinstance(fresh, Workspace) and fresh is not old
        assert old._started and fresh._started and fresh.session is not None
        assert old.agent_id == fresh.agent_id == "A"
        assert id(old) in manager._retired_instances
        fetched = await qr.sessions.fetch(qr.scope, {})
        current = qr.sessions._sessions[
            sha256(fetched.poll_token.encode()).hexdigest()
        ]
        claims = reserve_wechat_auth(
            qr.rt.loader.registry,
            owner=current.lease,
            workspace_id="A",
            workspace_dir=current.scope.workspace_dir,
            config={
                "bot_token_file": str(
                    tmp_path / "new-instance-auth" / "token"
                ),
                "bot_token": "new-instance-custody-token",
            },
        )
        current.claims = claims
        assert claims and current.lease in qr.rt.owners.leases()
        release.set()
        assert await reloading is True
        assert stop_calls == [((), {"final": False})]
        assert (
            not old._started
            and manager.agents["A"] is fresh
            and fresh._started
        )
        assert id(old) not in manager._retired_instances
        assert current.lease in qr.rt.owners.leases()
        assert qr.rt.owners.resource(current.lease) is current
        assert (
            set(claims).issubset(qr.rt.owners.leases())
            and current.claims == claims
        )
        assert current.status == "waiting"
        result = await qr.sessions.poll(qr.scope, fetched.poll_token)
        assert result.status == "confirmed" and result.credentials == {
            "api_token": "fixture-result-secret"
        }
        assert len(qr.http.requests) == 2
        assert set(claims).issubset(qr.rt.owners.leases())
    finally:
        release.set()
        await asyncio.gather(reloading, return_exceptions=True)
        await manager.stop_all()
