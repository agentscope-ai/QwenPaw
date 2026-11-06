# -*- coding: utf-8 -*-
"""Voice-settings entry to the framework's optional-plugin installer.

Only installation progress and one-time migration live here. The ordinary
plugin directory, loader and SDK own discovery, activation and cleanup.
"""

import asyncio
import logging
import shutil
from importlib import metadata
from pathlib import Path

from ..config import load_config
from ..utils.io_utils import (
    read_json_async,
    run_sync_io,
    write_json_atomic_async,
)
from .settings import is_plugin_enabled

logger = logging.getLogger(__name__)
PLUGIN_ID = "local-whisper"
SOURCE = Path(__file__).parent / "optional" / "local_whisper"
_service = None


def dependency_status() -> dict:
    """Inspect dependencies without importing Torch or loading a model."""
    from .loader import _ensure_plugin_site_on_path

    _ensure_plugin_site_on_path()
    try:
        metadata.version("openai-whisper")
        metadata.version("torch")
        installed = True
    except metadata.PackageNotFoundError:
        installed = False
    ffmpeg = shutil.which("ffmpeg") is not None
    return {
        "available": installed and ffmpeg,
        "whisper_installed": installed,
        "ffmpeg_installed": ffmpeg,
    }


def get_status() -> dict:
    """Use framework state, not dependency presence, to determine readiness."""
    status = dependency_status()
    loader = _service.loader if _service is not None else None
    record = loader.get_loaded_plugin(PLUGIN_ID) if loader else None
    installed = bool(
        record or (loader and loader.find_installed_plugin_dir(PLUGIN_ID)),
    )
    enabled = installed and is_plugin_enabled(
        load_config().plugins.get(PLUGIN_ID),
    )
    plugin_status = (
        record.status if record else "inactive" if installed else "missing"
    )
    error = "; ".join(record.diagnostics or []) if record else ""
    if loader:
        instance = loader.lifecycle.get_instance(PLUGIN_ID)
        if instance is not None and instance.state.value != "active":
            plugin_status = (
                "failed" if instance.state.value == "failed" else "inactive"
            )
    registered = bool(
        loader and loader.registry.get_transcription_backend("local_whisper"),
    )
    available = bool(
        status["available"]
        and enabled
        and plugin_status == "active"
        and registered,
    )
    if not installed:
        state = "missing"
    elif not enabled:
        state = "disabled"
    elif plugin_status == "failed":
        state = "failed"
    elif not status["available"]:
        state = "missing_dependencies"
    else:
        state = "ready" if available else "inactive"
    if _service is not None:
        if _service.task is not None and not _service.task.done():
            state, available = "installing", False
        elif _service.error and not available:
            error = error or _service.error
    status.update(
        available=available,
        plugin_installed=installed,
        plugin_enabled=bool(enabled),
        plugin_status=plugin_status,
        state=state,
        error=error,
    )
    return status


def get_service():
    return _service


class LocalTranscriptionService:
    """A background install job, not an alternate plugin lifecycle."""

    def __init__(self, loader, state_path):
        self.loader = loader
        self.state_path = Path(state_path)
        self.task = None
        self.error = ""

    async def start(self):
        global _service
        _service = self
        try:
            await read_json_async(self.state_path)
        except FileNotFoundError:
            pass
        except (OSError, ValueError) as exc:
            self.error = str(exc)
            return
        else:
            return
        config = await run_sync_io(load_config)
        # Only the first startup considers migrating the old built-in backend.
        installed = await run_sync_io(
            self.loader.find_installed_plugin_dir,
            PLUGIN_ID,
        )
        migrate = (
            installed is None
            and config.agents.transcription_provider_type == "local_whisper"
            and is_plugin_enabled(config.plugins.get(PLUGIN_ID))
        )
        # Persist BEFORE scheduling: interrupted/failed migration requires an
        # explicit retry and cannot resurrect an uninstalled plugin.
        try:
            await write_json_atomic_async(
                self.state_path,
                {
                    "framework_migration": "attempted"
                    if migrate
                    else "not_required",
                },
            )
        except OSError as exc:
            self.error = str(exc)
            return
        if migrate:
            self.request()

    def request(self):
        """Coalesce clicks; the framework serializes lifecycle operations."""
        if self.task is not None and not self.task.done():
            return
        self.error = ""
        self.task = asyncio.create_task(self._install())

    async def _install(self):
        try:
            # One framework transaction covers the existence check and install
            # or repair, so a queued uninstall always runs after activation.
            async with self.loader.plugin_lifecycle(PLUGIN_ID):
                installed = await run_sync_io(
                    self.loader.find_installed_plugin_dir,
                    PLUGIN_ID,
                )
                if installed is None:
                    record = await self.loader.load_plugin_from_path(
                        SOURCE,
                    )
                else:
                    record = await self.loader.repair_dependencies(PLUGIN_ID)
                if record.status == "failed":
                    raise RuntimeError(
                        "; ".join(record.diagnostics or [])
                        or "Plugin activation failed",
                    )
        except Exception as exc:
            self.error = str(exc)
            logger.warning("Local Whisper installation failed: %s", exc)

    async def close(self):
        global _service
        try:
            if self.task is not None and not self.task.done():
                self.task.cancel()
                try:
                    await self.task
                except asyncio.CancelledError:
                    pass
        finally:
            if _service is self:
                _service = None
