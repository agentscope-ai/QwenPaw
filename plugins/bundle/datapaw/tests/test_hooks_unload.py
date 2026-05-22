# -*- coding: utf-8 -*-
"""Tests for hooks.patch_plugin_loader_unload."""
import asyncio
from unittest.mock import patch


def _build_fake_loader_module():
    fake_module = type("M", (), {})()

    class FakeLoader:
        async def unload_plugin(self, plugin_id, delete_files=False):
            return ("orig", plugin_id, delete_files)

    fake_module.PluginLoader = FakeLoader
    return fake_module, FakeLoader


def test_patch_plugin_loader_unload_runs_uninstall_for_datapaw():
    fake_module, FakeLoader = _build_fake_loader_module()
    calls: list = []

    with patch(
        "hooks.uninstall_builtin_agents",
        side_effect=lambda: calls.append("uninstall"),
    ):
        from hooks import patch_plugin_loader_unload

        patch_plugin_loader_unload(_loader_module=fake_module)

        result = asyncio.run(
            FakeLoader().unload_plugin("datapaw", delete_files=False),
        )

    assert calls == ["uninstall"]
    assert result == ("orig", "datapaw", False)


def test_patch_plugin_loader_unload_skips_for_other_plugins():
    fake_module, FakeLoader = _build_fake_loader_module()
    calls: list = []

    with patch(
        "hooks.uninstall_builtin_agents",
        side_effect=lambda: calls.append("uninstall"),
    ):
        from hooks import patch_plugin_loader_unload

        patch_plugin_loader_unload(_loader_module=fake_module)

        result = asyncio.run(
            FakeLoader().unload_plugin("cloudpaw"),
        )

    assert not calls, "uninstall hook must not fire for non-datapaw plugins"
    assert result == ("orig", "cloudpaw", False)


def test_patch_plugin_loader_unload_idempotent():
    fake_module, FakeLoader = _build_fake_loader_module()
    from hooks import patch_plugin_loader_unload

    patch_plugin_loader_unload(_loader_module=fake_module)
    first = FakeLoader.unload_plugin
    patch_plugin_loader_unload(_loader_module=fake_module)
    assert FakeLoader.unload_plugin is first


def test_patch_plugin_loader_unload_swallows_uninstall_errors():
    """If uninstall raises, host unload still runs (partial cleanup ok)."""
    fake_module, FakeLoader = _build_fake_loader_module()

    def _boom():
        raise RuntimeError("simulated failure")

    with patch("hooks.uninstall_builtin_agents", side_effect=_boom):
        from hooks import patch_plugin_loader_unload

        patch_plugin_loader_unload(_loader_module=fake_module)

        result = asyncio.run(FakeLoader().unload_plugin("datapaw"))

    # Even if uninstall raised, the host unload should still complete.
    assert result == ("orig", "datapaw", False)
