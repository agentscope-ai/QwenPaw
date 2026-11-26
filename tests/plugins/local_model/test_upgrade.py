# -*- coding: utf-8 -*-
"""Dependency preparation through the local plugin upgrade entry points."""
import pytest

from qwenpaw.plugins.local_model_legacy import migrate_local_model_plugin
from qwenpaw.plugins.testing import PluginTestHost

PLUGIN_ID = "local-llamacpp"


@pytest.mark.parametrize("entry", ["cli", "cli-offline", "cloud-startup"])
async def test_bundle_upgrade_repairs_missing_download_dependencies(
    tmp_path,
    monkeypatch,
    entry,
):
    from unittest.mock import AsyncMock
    from qwenpaw.plugins import dependency_gate, local_model_legacy
    from qwenpaw.plugins.loader import PluginLoader

    missing = {"modelscope-hub", "huggingface-hub"}
    original = dependency_gate.is_requirement_satisfied
    version = dependency_gate._dist_version

    def version_of(name):
        if name.replace("_", "-") in missing:
            raise dependency_gate.PackageNotFoundError(name)
        return version(name)

    monkeypatch.setattr(dependency_gate, "_dist_version", version_of)

    def satisfied(req):
        return (
            False if req.name.replace("_", "-") in missing else original(req)
        )

    async with PluginTestHost(tmp_path / "host") as host:
        monkeypatch.setattr(
            local_model_legacy,
            "_used_local_models",
            lambda _path: True,
        )
        monkeypatch.setattr(
            dependency_gate,
            "is_requirement_satisfied",
            satisfied,
        )

        async def install(path, plugin_id, **kwargs):
            assert plugin_id == PLUGIN_ID
            assert set(path.read_text().splitlines()) == {
                "modelscope-hub>=0.7.1",
                "huggingface_hub>=0.20.0",
            }
            if entry == "cli-offline":
                raise RuntimeError("download dependencies unavailable")
            missing.clear()

        installer = AsyncMock(side_effect=install)
        monkeypatch.setattr(
            host._loader,
            "_prepare_python_dependencies",
            installer,
        )
        loader = host._loader
        if entry == "cloud-startup":
            from qwenpaw.providers.provider_manager import ProviderManager

            deferred = await local_model_legacy.prepare_startup_local_model(
                loader,
                ProviderManager.get_instance(),
            )
            assert deferred == (PLUGIN_ID,)
            await loader.load_all_plugins(exclude=deferred, activate=True)
            assert loader.registry.get_provider("qwenpaw-local") is None
            installer.assert_not_awaited()
            await local_model_legacy.load_upgraded_local_model(loader)
            assert loader.registry.get_provider("qwenpaw-local") is not None
        else:
            monkeypatch.setattr(
                PluginLoader,
                "create",
                AsyncMock(return_value=loader),
            )
            errors = await local_model_legacy.prepare_local_model_upgrade()
            if entry == "cli-offline":
                assert "download dependencies unavailable" in errors[PLUGIN_ID]
            else:
                assert errors == {}
            assert loader.registry.get_provider("qwenpaw-local") is None
        installer.assert_awaited_once()
        assert loader.find_installed_plugin_dir(PLUGIN_ID) is not None
