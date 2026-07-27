# -*- coding: utf-8 -*-
# pylint: disable=protected-access
"""Per-plugin lifecycle lock serializes load/unload/reinstall."""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from qwenpaw.app.routers.plugins import (
    _finish_plugin_install_after_load,
    _tool_names_from_meta,
)
from qwenpaw.governance.tool_registry import (
    DEFAULT_REGISTRY,
    register_tool_governance,
)
from qwenpaw.plugins.api import (
    _TOOL_PLUGIN_OWNERS,
    release_tool_ownership_for_plugin,
)
from qwenpaw.plugins.architecture import (
    PluginEntryPoints,
    PluginManifest,
    PluginRecord,
)
from qwenpaw.plugins.loader import (
    PluginLoader,
    _norm_realpath,
    resolved_plugin_manifest_path,
)
from qwenpaw.plugins.registry import PluginRegistry


def test_tool_names_from_meta_supports_legacy_and_multi():
    assert _tool_names_from_meta({"tool_name": "a"}) == ["a"]
    assert _tool_names_from_meta(
        {"tools": [{"name": "b"}, {"name": "c"}, {"other": 1}]},
    ) == ["b", "c"]
    assert _tool_names_from_meta(
        {"tool_name": "a", "tools": [{"name": "b"}]},
    ) == ["a", "b"]


def test_tool_names_from_meta_tolerates_malformed_tools():
    """``meta.tools`` must never raise — install runs this post-load."""
    for bad_tools in (None, "not-a-list", {"name": "x"}):
        names = _tool_names_from_meta({"tools": bad_tools})
        assert isinstance(names, list)
        assert not names
    assert _tool_names_from_meta(
        {
            "tool_name": " legacy ",
            "tools": [
                {"name": "a"},
                None,
                "skip",
                {"name": 123},
                {"name": "  a  "},
                {"name": "b"},
                {"name": ""},
                {"name": "   "},
            ],
        },
    ) == ["legacy", "a", "b"]


def test_force_reinstall_removed_tools_are_old_minus_new():
    """Only tools dropped by the new manifest should be cleaned up."""
    old_tools = set(
        _tool_names_from_meta(
            {"tools": [{"name": "old_tool"}, {"name": "shared"}]},
        ),
    )
    new_tools = set(
        _tool_names_from_meta(
            {"tools": [{"name": "shared"}, {"name": "new_tool"}]},
        ),
    )
    assert sorted(old_tools - new_tools) == ["old_tool"]


@pytest.mark.asyncio
async def test_force_reinstall_removes_obsolete_tools_before_reload():
    """Agent reload must not run before obsolete tool configs are deleted."""
    order: list[str] = []

    async def _fake_post_load(_request, _plugin_id):
        order.append("post_load_setup")

    def _fake_remove(plugin_id, tool_names):
        del plugin_id
        order.append(f"remove:{','.join(tool_names)}")

    async def _fake_reload(_request):
        order.append("schedule_reload")

    record = MagicMock()
    record.manifest.id = "plug"
    record.manifest.meta = {
        "tools": [{"name": "shared"}, {"name": "new_tool"}],
    }

    with (
        patch(
            "qwenpaw.app.routers.plugins._post_load_setup",
            new=AsyncMock(side_effect=_fake_post_load),
        ),
        patch(
            "qwenpaw.app.routers.plugins._remove_named_tools_from_agents",
            side_effect=_fake_remove,
        ),
        patch(
            "qwenpaw.app.routers.plugins._schedule_all_agents_reload",
            new=AsyncMock(side_effect=_fake_reload),
        ),
        patch(
            "qwenpaw.app.routers.plugins.asyncio.to_thread",
            new=AsyncMock(
                side_effect=lambda fn, *args: fn(*args),
            ),
        ),
    ):
        await _finish_plugin_install_after_load(
            MagicMock(),
            record,
            force=True,
            old_tools={"old_tool", "shared"},
        )

    assert order == [
        "post_load_setup",
        "remove:old_tool",
        "schedule_reload",
    ]


def test_norm_realpath_applies_normcase(tmp_path: Path):
    """Hot-reload path identity must use realpath + normcase."""
    import os

    target = tmp_path / "PluginDir"
    target.mkdir()
    assert _norm_realpath(target) == os.path.normcase(
        os.path.realpath(str(target)),
    )


def test_resolved_plugin_manifest_path_accepts_normal_dir(tmp_path: Path):
    manifest = tmp_path / "plugin.json"
    manifest.write_text('{"id": "demo"}', encoding="utf-8")
    resolved = resolved_plugin_manifest_path(tmp_path)
    assert resolved.is_file()
    assert resolved.name == "plugin.json"
    assert resolved.parent == tmp_path.resolve()


def test_resolved_plugin_manifest_path_rejects_missing(tmp_path: Path):
    with pytest.raises(FileNotFoundError):
        resolved_plugin_manifest_path(tmp_path)


@pytest.mark.asyncio
async def test_plugin_lifecycle_serializes_same_id():
    """Same plugin_id critical sections must not interleave."""
    loader = PluginLoader(plugin_dirs=[])
    order: list[str] = []

    async def hold(tag: str) -> None:
        async with loader.plugin_lifecycle("p1"):
            order.append(f"{tag}-enter")
            await asyncio.sleep(0.05)
            order.append(f"{tag}-exit")

    await asyncio.gather(hold("a"), hold("b"))
    assert order in (
        ["a-enter", "a-exit", "b-enter", "b-exit"],
        ["b-enter", "b-exit", "a-enter", "a-exit"],
    )


@pytest.mark.asyncio
async def test_plugin_lifecycle_allows_different_ids_concurrently():
    """Unrelated plugins may enter lifecycle sections together."""
    loader = PluginLoader(plugin_dirs=[])
    in_critical = 0
    max_in_critical = 0
    lock = asyncio.Lock()

    async def hold(plugin_id: str) -> None:
        nonlocal in_critical, max_in_critical
        async with loader.plugin_lifecycle(plugin_id):
            async with lock:
                in_critical += 1
                max_in_critical = max(max_in_critical, in_critical)
            await asyncio.sleep(0.05)
            async with lock:
                in_critical -= 1

    await asyncio.gather(hold("p-a"), hold("p-b"))
    assert max_in_critical == 2


@pytest.mark.asyncio
async def test_child_task_cannot_bypass_lifecycle_lock():
    """create_task children must not inherit re-entrancy and skip the lock."""
    loader = PluginLoader(plugin_dirs=[])
    child_entered = asyncio.Event()

    async def child_body() -> None:
        async with loader.plugin_lifecycle("p1"):
            child_entered.set()

    async with loader.plugin_lifecycle("p1"):
        child_task = asyncio.create_task(child_body())
        await asyncio.sleep(0.05)
        assert not child_entered.is_set()
        assert not child_task.done()

    await child_task
    assert child_entered.is_set()


@pytest.mark.asyncio
async def test_uninstall_waits_for_full_install_transaction():
    """Uninstall waits until install post-load releases the lock."""
    loader = PluginLoader(plugin_dirs=[])
    plugin_id = "p-tx"
    install_holding = asyncio.Event()
    uninstall_started = asyncio.Event()
    release_install = asyncio.Event()
    order: list[str] = []

    async def install_transaction() -> None:
        # Mimic router: hold lifecycle across load + post-load setup.
        async with loader.plugin_lifecycle(plugin_id):
            order.append("install-enter")
            install_holding.set()
            await uninstall_started.wait()
            await asyncio.sleep(0)
            order.append("install-post-load")
            await release_install.wait()
            order.append("install-exit")

    async def uninstall_transaction() -> None:
        await install_holding.wait()
        uninstall_started.set()
        async with loader.plugin_lifecycle(plugin_id):
            order.append("uninstall-enter")
        order.append("uninstall-exit")

    install_task = asyncio.create_task(install_transaction())
    uninstall_task = asyncio.create_task(uninstall_transaction())

    await asyncio.sleep(0.05)
    assert not uninstall_task.done()
    assert "uninstall-enter" not in order

    release_install.set()
    await asyncio.gather(install_task, uninstall_task)
    assert order == [
        "install-enter",
        "install-post-load",
        "install-exit",
        "uninstall-enter",
        "uninstall-exit",
    ]


@pytest.mark.asyncio
async def test_stale_unload_cannot_delete_tools_from_concurrent_reload():
    """Unload must not race a force-reinstall and wipe the new tools."""
    plugin_id = "__ut_lifecycle_race__"
    tool_name = "__ut_lifecycle_race_tool__"
    release_tool_ownership_for_plugin(plugin_id)
    DEFAULT_REGISTRY.unregister_python_tool(tool_name)

    old = PluginRegistry._instance
    PluginRegistry._instance = None
    try:
        preg = PluginRegistry()
        loader = PluginLoader(plugin_dirs=[])
        loader.registry = preg
        manifest = PluginManifest(
            id=plugin_id,
            name="Race",
            version="1.0.0",
            entry=PluginEntryPoints(backend="plugin.py"),
            meta={"tool_name": tool_name},
        )
        loader._loaded_plugins[plugin_id] = PluginRecord(
            manifest=manifest,
            source_path=Path("/fake-lifecycle-race"),
            enabled=True,
            instance=None,
        )
        register_tool_governance(
            DEFAULT_REGISTRY,
            python_name=tool_name,
            tool_type="network",
            owner=plugin_id,
        )
        _TOOL_PLUGIN_OWNERS[tool_name] = plugin_id

        reinstall_entered = asyncio.Event()
        unload_started = asyncio.Event()
        release_reinstall = asyncio.Event()

        async def force_reinstall() -> None:
            async with loader.plugin_lifecycle(plugin_id):
                reinstall_entered.set()
                await unload_started.wait()
                # Yield so a racy unload would proceed without the lock.
                await asyncio.sleep(0)
                await loader.unload_plugin(plugin_id)
                # Simulate reload re-claiming the same tool identity.
                register_tool_governance(
                    DEFAULT_REGISTRY,
                    python_name=tool_name,
                    tool_type="shell",
                    target_param="command",
                    owner=plugin_id,
                )
                _TOOL_PLUGIN_OWNERS[tool_name] = plugin_id
                loader._loaded_plugins[plugin_id] = PluginRecord(
                    manifest=manifest,
                    source_path=Path("/fake-lifecycle-race-v2"),
                    enabled=True,
                    instance=None,
                )
                await release_reinstall.wait()

        async def stale_unload() -> None:
            await reinstall_entered.wait()
            unload_started.set()
            await loader.unload_plugin(plugin_id)

        reinstall_task = asyncio.create_task(force_reinstall())
        unload_task = asyncio.create_task(stale_unload())

        # Stale unload must block while reinstall holds the lifecycle lock.
        await asyncio.sleep(0.05)
        assert not unload_task.done()
        assert _TOOL_PLUGIN_OWNERS.get(tool_name) == plugin_id
        assert DEFAULT_REGISTRY.get_owner(tool_name) == plugin_id

        release_reinstall.set()
        await reinstall_task
        await unload_task

        # Stale unload ran only after reinstall finished, so it removed
        # the post-reload registration cleanly (no torn mid-reload state).
        assert tool_name not in _TOOL_PLUGIN_OWNERS
        assert plugin_id not in loader._loaded_plugins
    finally:
        release_tool_ownership_for_plugin(plugin_id)
        DEFAULT_REGISTRY.unregister_python_tool(tool_name)
        PluginRegistry._instance = old
