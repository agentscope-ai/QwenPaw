# -*- coding: utf-8 -*-
# pylint: disable=protected-access
"""Shared plugin test isolation."""

import pytest

from qwenpaw.plugins.registry import PluginRegistry


@pytest.fixture
def bounded_dependency_environment(tmp_path, monkeypatch):
    """Keep real dependency admission, with a small fixture-owned inventory."""
    from qwenpaw.plugins import python_backend

    site = tmp_path / "dependency-site"
    metadata = site / "lifecycle_fixture-1.0.dist-info"
    metadata.mkdir(parents=True)
    (metadata / "METADATA").write_text(
        "Metadata-Version: 2.1\nName: lifecycle-fixture\nVersion: 1.0\n",
        encoding="utf-8",
    )
    (metadata / "RECORD").write_text(
        f"{metadata.name}/METADATA,,\n{metadata.name}/RECORD,,\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        python_backend,
        "_host_paths",
        lambda cwd: (str(site),),
    )
    return site


@pytest.fixture(name="short_interrupt_timeout")
def bounded_interrupt_timeout(monkeypatch):
    """Exercise blocked lifecycle retries without the production 5s wait."""
    from qwenpaw.plugins import activity

    monkeypatch.setattr(activity, "INTERRUPT_TIMEOUT_SECONDS", 0.2)
    return activity.INTERRUPT_TIMEOUT_SECONDS


@pytest.fixture()
def fresh_registry():
    """Reset the singleton and restore it even if a test fails."""
    old = PluginRegistry._instance
    PluginRegistry._instance = None
    try:
        yield PluginRegistry()
    finally:
        PluginRegistry._instance = old


@pytest.fixture()
def sdk_component(tmp_path):
    """Real SDK activation/disposal, retaining Host's process isolation only."""
    from contextlib import asynccontextmanager

    from qwenpaw.plugins.api import PluginApi
    from qwenpaw.plugins.lifecycle import UnloadMode
    from qwenpaw.plugins.sdk import PluginContext
    from qwenpaw.plugins.testing import PluginTestHost

    @asynccontextmanager
    async def component(
        declare=lambda ctx: None,
        *,
        plugin_id="resource-contract",
        capabilities=("resources",),
        config=None,
    ):
        async with PluginTestHost(tmp_path / "component") as host:
            loader = host._loader
            instance = loader.lifecycle.ensure_instance(
                plugin_id,
                generation=1,
            )
            api = PluginApi(
                plugin_id,
                config or {},
                {
                    "id": plugin_id,
                    "version": "1.0.0",
                    "sdk": {
                        "version": "1.0",
                        "capabilities": list(capabilities),
                    },
                },
            )
            api.set_registry(loader.registry)
            api._instance, api._loader = instance, loader
            ctx = PluginContext(api)
            instance.sdk_context = ctx
            try:
                declare(ctx)
                await loader.lifecycle.activate(plugin_id)
                yield host, ctx
            finally:
                async with instance.activity.mutation():
                    report = await instance.dispose(UnloadMode.UNLOAD)
                assert report.clean and report.quiescent
                assert ctx.resources.snapshot()["resources"] == ()
                assert not instance.activity.tasks
                assert not instance.activity.cleanup_tasks
                assert not loader.registry.leftover_registrations(plugin_id)
                assert not any(
                    intent.plugin_id == plugin_id
                    for intent in loader.registry.projector._intents
                )
                from qwenpaw.plugins.workspace_projector import scan_owner_rows

                assert not scan_owner_rows(
                    plugin_id,
                    list(host._workspaces.values()),
                ).stamped_leaks
                loader.registry.unregister_plugin(plugin_id)
                loader.lifecycle.drop_instance(plugin_id)

    return component
