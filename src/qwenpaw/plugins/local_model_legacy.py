# -*- coding: utf-8 -*-
"""Bundled local provider source and one-time legacy data migration."""

import logging
import os
from pathlib import Path

from ..config.utils import load_config, mutate_config
from ..utils.io_utils import run_sync_io
from .settings import is_plugin_enabled

logger = logging.getLogger(__name__)

PLUGIN_ID = "local-llamacpp"


def bundled_local_source() -> Path:
    """Locate dormant provider files without importing their implementation."""
    package = Path(__file__).resolve().parents[1]
    root = package / "plugins/bundled/provider"
    if not root.is_dir():
        root = package.parent.parent / "plugins/provider"
    return root / PLUGIN_ID


def _legacy_data_dir(config) -> Path:
    from ..constant import DEFAULT_LOCAL_PROVIDER_DIR

    settings = config.plugins.get(PLUGIN_ID) or {}
    return Path(
        settings.get("data_dir", DEFAULT_LOCAL_PROVIDER_DIR),
    ).expanduser()


def _local_model_selected(manager) -> bool:
    from ._providers import configured_models

    return any(
        slot.provider_id in {"qwenpaw-local", "copaw-local"}
        for slot in configured_models(manager)
    )


def _used_local_models(data_dir: Path) -> bool:
    from ..providers.provider_manager import ProviderManager

    manager = ProviderManager.get_instance()
    return (
        (manager.plugin_path / "qwenpaw-local.json").is_file()
        or (data_dir / "config.json").is_file()
        or any((data_dir / "models").rglob("*.gguf"))
        or any((data_dir / "bin").rglob("llama-server*"))
        or _local_model_selected(manager)
    )


async def _prepare_dependencies(loader, activate=False) -> None:
    async with loader.plugin_lifecycle(PLUGIN_ID):
        source = loader.find_installed_plugin_dir(PLUGIN_ID)
        settings = (await run_sync_io(load_config)).plugins.get(PLUGIN_ID)
        # Consume the attempt when this task actually begins preparation.
        await run_sync_io(_mark_upgrade_checked)
        if source is None or not is_plugin_enabled(settings):
            return
        _, manifest = await run_sync_io(loader.read_source_manifest, source)
        if activate:
            await loader.load_plugin(
                manifest,
                source,
                settings,
                allow_install=True,
                activate=True,
            )
        else:
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


def _upgrade_marker() -> Path:
    from ..constant import WORKING_DIR

    marker = os.environ.get("QWENPAW_LOCAL_MODEL_UPGRADE_MARKER")
    if marker:
        return Path(marker)
    return WORKING_DIR / "plugin_runtime/migrations/local-llamacpp.checked"


def _mark_upgrade_checked() -> None:
    marker = _upgrade_marker()
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.touch()


def _preserve_data_directory(data_dir: Path) -> None:
    from ..constant import WORKING_DIR
    from ..utils.io_utils import get_sync_path_lock, write_json_atomic

    if data_dir.is_dir():
        locator = WORKING_DIR / "plugin-data" / PLUGIN_ID / "data-root.json"
        with get_sync_path_lock(locator):
            if not locator.exists():
                locator.parent.mkdir(parents=True, exist_ok=True)
                write_json_atomic(
                    locator,
                    {"data_dir": str(data_dir.resolve())},
                )


async def _seed_legacy_installation(loader, data_dir) -> bool:
    used = await run_sync_io(_used_local_models, data_dir)
    if used:
        await run_sync_io(_preserve_data_directory, data_dir)
    if used and loader.find_installed_plugin_dir(PLUGIN_ID) is None:
        source = await run_sync_io(bundled_local_source)
        _, manifest = await run_sync_io(loader.read_source_manifest, source)
        if manifest.id != PLUGIN_ID:
            raise ValueError("Bundled local provider identity mismatch")
        await loader._seed_bundled_source(source, manifest)

    def completed(root):
        if used:
            root.plugins.setdefault(PLUGIN_ID, {"enabled": True})
        root.local_model_plugin_migrated = True

    await run_sync_io(mutate_config, completed)
    return used


async def migrate_local_model_plugin(loader, refresh=False) -> bool:
    """Seed the legacy profile and report if its dependencies need preparation."""
    async with loader.plugin_lifecycle(PLUGIN_ID):
        config = await run_sync_io(load_config)
        if config.local_model_plugin_migrated:
            if not refresh and await run_sync_io(_upgrade_marker().exists):
                return False
            used = True
        else:
            used = await _seed_legacy_installation(
                loader,
                _legacy_data_dir(config),
            )
        if (
            used
            and is_plugin_enabled(config.plugins.get(PLUGIN_ID))
            and loader.find_installed_plugin_dir(PLUGIN_ID) is not None
        ):
            return True
        await run_sync_io(_mark_upgrade_checked)
        return False


async def load_upgraded_local_model(loader) -> None:
    """Prepare and activate the installed provider if it is still enabled."""
    try:
        await _prepare_dependencies(loader, activate=True)
    except Exception:
        logger.warning("Bundled local provider needs repair", exc_info=True)


async def prepare_startup_local_model(
    loader,
    provider_manager,
) -> tuple[str, ...]:
    """Return provider IDs whose upgrade can follow Agent and plugin startup."""
    try:
        if await migrate_local_model_plugin(loader):
            if not await run_sync_io(_local_model_selected, provider_manager):
                return (PLUGIN_ID,)
            await _prepare_dependencies(loader)
    except Exception:
        logger.warning("Bundled local provider needs repair", exc_info=True)
    return ()


async def prepare_local_model_upgrade() -> dict[str, str]:
    """Prepare installed local dependencies during an explicit upgrade."""
    from ..config.utils import get_plugins_dir

    config = await run_sync_io(load_config)
    if not is_plugin_enabled(config.plugins.get(PLUGIN_ID)):
        return {}
    if config.local_model_plugin_migrated:
        if not (get_plugins_dir() / PLUGIN_ID).is_dir():
            return {}
    elif not await run_sync_io(_used_local_models, _legacy_data_dir(config)):
        return {}

    from .channel_bootstrap import resolve_default_channel_runtime
    from .lifecycle import UnloadMode
    from .loader import PluginLoader

    loader = await PluginLoader.create(
        [get_plugins_dir()],
        channel_runtime=await run_sync_io(resolve_default_channel_runtime),
    )
    try:
        if await migrate_local_model_plugin(loader, refresh=True):
            await _prepare_dependencies(loader)
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
