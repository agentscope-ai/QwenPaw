# -*- coding: utf-8 -*-
"""Bundled local provider source and one-time legacy data migration."""

from pathlib import Path

from ..config.utils import load_config, mutate_config
from ..utils.io_utils import run_sync_io

PLUGIN_ID = "local-llamacpp"


def bundled_local_source() -> Path:
    """Locate dormant provider files without importing their implementation."""
    package = Path(__file__).resolve().parents[1]
    root = package / "plugins/bundled/provider"
    if not root.is_dir():
        root = package.parent.parent / "plugins/provider"
    return root / PLUGIN_ID


def _used_local_models():
    from ..constant import DEFAULT_LOCAL_PROVIDER_DIR
    from ..providers.provider_manager import ProviderManager
    from ._providers import configured_models

    selected = configured_models(ProviderManager.get_instance())
    return (
        any(
            slot.provider_id in {"qwenpaw-local", "copaw-local"}
            for slot in selected
        )
        or (DEFAULT_LOCAL_PROVIDER_DIR / "config.json").is_file()
        or any((DEFAULT_LOCAL_PROVIDER_DIR / "models").rglob("*.gguf"))
        or any((DEFAULT_LOCAL_PROVIDER_DIR / "bin").rglob("llama-server*"))
    )


async def migrate_local_model_plugin(loader) -> dict[str, str]:
    """Migrate legacy users once without installing or executing packages."""
    try:
        async with loader.plugin_lifecycle(PLUGIN_ID):
            config = await run_sync_io(load_config)
            if config.local_model_plugin_migrated:
                return {}
            used = await run_sync_io(_used_local_models)
            if used and loader.find_installed_plugin_dir(PLUGIN_ID) is None:
                source = await run_sync_io(bundled_local_source)
                _, manifest = await run_sync_io(
                    loader.read_source_manifest,
                    source,
                )
                if manifest.id != PLUGIN_ID:
                    raise ValueError(
                        "Bundled local provider identity mismatch",
                    )
                await loader._seed_bundled_source(source, manifest)

            def completed(root):
                if used:
                    root.plugins.setdefault(PLUGIN_ID, {"enabled": True})
                root.local_model_plugin_migrated = True

            await run_sync_io(mutate_config, completed)
        return {}
    except Exception as exc:
        return {PLUGIN_ID: str(exc)}


async def prepare_local_model_upgrade() -> dict[str, str]:
    """Prepare installed local dependencies during an explicit upgrade."""
    from ..config.utils import get_plugins_dir
    from .channel_bootstrap import resolve_default_channel_runtime
    from .lifecycle import UnloadMode
    from .loader import PluginLoader
    from .settings import is_plugin_enabled

    config = await run_sync_io(load_config)
    if not is_plugin_enabled(config.plugins.get(PLUGIN_ID)):
        return {}
    if config.local_model_plugin_migrated:
        source = get_plugins_dir() / PLUGIN_ID
        if not source.is_dir():
            return {}
    elif not await run_sync_io(_used_local_models):
        return {}
    loader = await PluginLoader.create(
        [get_plugins_dir()],
        channel_runtime=await run_sync_io(resolve_default_channel_runtime),
    )
    try:
        errors = await migrate_local_model_plugin(loader)
        if errors:
            return errors
        source = loader.find_installed_plugin_dir(PLUGIN_ID)
        _, manifest = await run_sync_io(loader.read_source_manifest, source)
        async with loader.plugin_lifecycle(PLUGIN_ID):
            binding = await run_sync_io(
                loader.backend_resolver.resolve,
                source,
                manifest,
            )
            await loader.lifecycle.preflight_backend(
                binding,
                allow_install=True,
                probe=False,
            )
        return {}
    except Exception as exc:
        return {PLUGIN_ID: str(exc)}
    finally:
        reports = await loader.lifecycle.unload_all(UnloadMode.SHUTDOWN)
        if any(
            not row.clean or not row.quiescent or row.needs_restart
            for row in reports
        ):
            raise RuntimeError("Local provider upgrade cleanup incomplete")
