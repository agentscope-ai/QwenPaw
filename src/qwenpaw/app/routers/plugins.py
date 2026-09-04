# -*- coding: utf-8 -*-
# pylint:disable=too-many-branches
"""Plugin API routes: list plugins with UI metadata and serve plugin
static files.  Also provides runtime install / uninstall endpoints."""

import asyncio
import json
import logging
import mimetypes
import re
import shutil
import tempfile
import urllib.request
import zipfile
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException, Request, UploadFile, File
from fastapi.responses import FileResponse
from pydantic import BaseModel

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/plugins", tags=["plugins"])


def _log_safe(value: object) -> str:
    """Strip CR/LF so request-derived values cannot forge log entries."""
    return str(value).replace("\r", "").replace("\n", "")


# ── Helpers ──────────────────────────────────────────────────────────────


def _list_plugins_from_disk() -> list[dict]:
    """Read plugin manifests directly from the plugins directory on disk.

    Used as a fallback when the plugin loader has not finished
    initialising (e.g. the frontend opens before the backend startup
    coroutine completes).  Returns the same shape as the normal list
    endpoint so the frontend does not need to handle a different schema.
    """
    from ...config.utils import get_plugins_dir

    plugins_dir: Path = get_plugins_dir()
    if not plugins_dir.exists():
        return []

    from ...plugins.loader import _is_disabled_plugin_dir

    result: list[dict] = []
    for item in sorted(plugins_dir.iterdir()):
        if not item.is_dir():
            continue
        if _is_disabled_plugin_dir(item):
            continue
        manifest_path = item / "plugin.json"
        if not manifest_path.exists():
            continue
        try:
            with open(manifest_path, encoding="utf-8") as f:
                manifest = json.load(f)
        except Exception as exc:
            logger.warning("Failed to read %s: %s", manifest_path, exc)
            continue

        plugin_id = manifest.get("id", item.name)
        frontend_entry = manifest.get("entry", {}).get("frontend")

        from ...plugins.architecture import PluginManifest
        from ...plugins.settings import is_plugin_enabled

        disk_manifest = PluginManifest.from_dict(manifest)
        raw = _plugin_config_row(plugin_id)
        result.append(
            {
                "id": plugin_id,
                "name": manifest.get("name", plugin_id),
                "version": manifest.get("version", "0.0.0"),
                "description": manifest.get("description", ""),
                "author": manifest.get("author", ""),
                "enabled": is_plugin_enabled(raw),
                "loaded": False,
                "plugin_type": disk_manifest.plugin_type,
                "frontend_entry": frontend_entry,
            },
        )
    return result


def _plugin_config_row(plugin_id: str) -> dict:
    from ...config.utils import load_config

    return dict((load_config().plugins or {}).get(plugin_id) or {})


def _safe_extract_zip(
    zip_ref: zipfile.ZipFile,
    extract_path: Path,
) -> None:
    """Extract zip safely, rejecting any Zip Slip path traversal.

    Args:
        zip_ref: Open ZipFile object
        extract_path: Destination directory (must be resolved)

    Raises:
        ValueError: If any member would escape extract_path
    """
    extract_resolved = extract_path.resolve()
    for member in zip_ref.namelist():
        member_path = (extract_path / member).resolve()
        if not member_path.is_relative_to(extract_resolved):
            raise ValueError(
                f"Zip Slip detected: {member} would extract "
                "outside the target directory",
            )
    zip_ref.extractall(extract_path)


def _find_plugin_dir(base: Path) -> Path:
    """Return the directory that contains plugin.json.

    Args:
        base: Root of the extracted archive

    Returns:
        Directory containing plugin.json

    Raises:
        ValueError: If no plugin.json found
    """
    if (base / "plugin.json").exists():
        return base
    sub_dirs = [d for d in base.iterdir() if d.is_dir()]
    for sub in sub_dirs:
        if (sub / "plugin.json").exists():
            return sub
    raise ValueError(
        "No plugin.json found in archive root or top-level subdirectory",
    )


async def _post_load_setup(  # pylint: disable=too-many-branches
    request: Request,
    plugin_id: str,
) -> None:
    """Perform post-load integration for a newly loaded plugin.

    Registers newly created providers / control-commands, executes
    startup hooks, and syncs tool entries into agent configs.

    Does **not** schedule agent reloads — callers must do that after any
    follow-up config cleanup (e.g. removing obsolete tools on
    force-reinstall) so reload never races stale tool entries.

    Args:
        request: Current FastAPI request (for app.state access)
        plugin_id: ID of the plugin that was just loaded
    """
    loader = getattr(request.app.state, "plugin_loader", None)
    if loader is None:
        return

    registry = loader.registry

    # Register any providers the plugin registered
    provider_manager = getattr(
        request.app.state,
        "provider_manager",
        None,
    )
    if provider_manager is not None:
        for pid, reg in registry.get_all_providers().items():
            if reg.plugin_id != plugin_id:
                continue
            try:
                await provider_manager.register_plugin_provider_async(
                    provider_id=pid,
                    provider_class=reg.provider_class,
                    label=reg.label,
                    base_url=reg.base_url,
                    metadata=reg.metadata,
                )
            except Exception as exc:
                logger.warning(
                    f"Could not register provider '{pid}': {exc}",
                )

    # Register any control commands the plugin registered
    try:
        from ...runtime.commands.control import register_command
        from ...app.channels.command_registry import CommandRegistry

        command_registry = CommandRegistry()
        for cmd_reg in registry.get_control_commands():
            if cmd_reg.plugin_id != plugin_id:
                continue
            try:
                register_command(cmd_reg.handler)
                command_registry.register_command(
                    f"/{cmd_reg.handler.command_name}",
                    priority_level=cmd_reg.priority_level,
                )
            except Exception as exc:
                logger.warning(
                    f"Could not register control command "
                    f"'{cmd_reg.handler.command_name}': {exc}",
                )
    except Exception as exc:
        logger.warning(f"Control command setup skipped: {exc}")

    # Execute startup hooks for the new plugin
    started = await loader.run_startup_hooks_isolated(plugin_id)
    if not started:
        return

    # Sync the plugin's tools into every agent's builtin_tools config
    # (config file I/O — keep off the event loop).
    await asyncio.to_thread(_sync_plugin_tools_to_agents, loader, plugin_id)


def _tool_names_from_meta(meta: dict) -> list[str]:
    """Extract tool names from plugin manifest ``meta`` (legacy + multi).

    Malformed ``meta.tools`` (``null``, non-list, non-dict entries) must
    never raise — callers run this after the plugin is already loaded.
    """
    tool_names: list[str] = []
    seen: set[str] = set()

    def _add(name: object) -> None:
        if not isinstance(name, str):
            return
        stripped = name.strip()
        if not stripped or stripped in seen:
            return
        seen.add(stripped)
        tool_names.append(stripped)

    _add(meta.get("tool_name"))
    raw_tools = meta.get("tools")
    if not isinstance(raw_tools, list):
        raw_tools = []
    for tool in raw_tools:
        if not isinstance(tool, dict):
            continue
        _add(tool.get("name"))
    return tool_names


def _sync_plugin_tools_to_agents(loader, plugin_id: str) -> None:
    """Add plugin tool entries to all existing agents.

    Supports both old (``meta.tool_name``) and new (``meta.tools[]``)
    manifest formats.

    Args:
        loader: PluginLoader instance
        plugin_id: Plugin whose tools should be synced
    """
    record = loader.get_loaded_plugin(plugin_id)
    if record is None:
        return

    tool_names = _tool_names_from_meta(record.manifest.meta or {})
    if not tool_names:
        return

    try:
        from ...config.utils import load_config
        from ...config.config import (
            BuiltinToolConfig,
            load_agent_config,
            save_agent_config,
        )

        config = load_config()
        if not config.agents or not config.agents.profiles:
            return

        for agent_id in config.agents.profiles:
            try:
                agent_cfg = load_agent_config(agent_id)
                changed = False
                for tool_name in tool_names:
                    if tool_name in agent_cfg.tools.builtin_tools:
                        continue
                    agent_cfg.tools.builtin_tools[
                        tool_name
                    ] = BuiltinToolConfig(
                        name=tool_name,
                        enabled=False,
                        config={},
                    )
                    changed = True
                if changed:
                    save_agent_config(agent_id, agent_cfg)
            except Exception as exc:
                logger.warning(
                    f"Failed to sync tools to agent '{agent_id}': {exc}",
                )
    except Exception as exc:
        logger.warning(f"Tool sync skipped: {exc}")


def _remove_named_tools_from_agents(
    plugin_id: str,
    tool_names: list[str],
) -> None:
    """Remove the given tool names from all agents' builtin_tools config."""
    if not tool_names:
        return

    try:
        from ...config.utils import load_config
        from ...config.config import load_agent_config, save_agent_config

        config = load_config()
        if not config.agents or not config.agents.profiles:
            return

        for agent_id in config.agents.profiles:
            try:
                agent_cfg = load_agent_config(agent_id)
                changed = False
                for tool_name in tool_names:
                    if tool_name in agent_cfg.tools.builtin_tools:
                        del agent_cfg.tools.builtin_tools[tool_name]
                        changed = True
                if changed:
                    save_agent_config(agent_id, agent_cfg)
            except Exception as exc:
                logger.warning(
                    "Failed to remove tools from agent "
                    f"'{_log_safe(agent_id)}': {_log_safe(exc)}",
                )
    except Exception as exc:
        logger.warning(
            "Tool removal from agents skipped for "
            f"'{_log_safe(plugin_id)}': {_log_safe(exc)}",
        )


def _remove_plugin_tools_from_agents(plugin_id: str, meta: dict) -> None:
    """Remove plugin tool entries from all agents.

    Args:
        plugin_id: Plugin being uninstalled (for logging)
        meta: Plugin manifest ``meta`` section
    """
    _remove_named_tools_from_agents(
        plugin_id,
        _tool_names_from_meta(meta),
    )


async def _load_plugin_with_optional_force_reinstall(
    loader,
    request: Request,
    source_path: Path,
    *,
    force: bool,
):
    """Load a plugin, optionally unloading first under one lifecycle lock.

    Force-reinstall is handled inside
    :meth:`PluginLoader.load_plugin_from_path` so this router never reads
    ``plugin.json`` from a user-supplied path (CodeQL path-injection).

    The full install transaction — unload (if force), load, and
    :func:`_post_load_setup` — runs under one
    :meth:`PluginLoader.plugin_lifecycle` critical section.

    On force-reinstall, tools present in the old manifest but absent from
    the new one are removed from agent configs (``old - new`` only).
    """
    from ...config.utils import get_plugins_dir

    install_dir = get_plugins_dir()
    collected: dict = {
        "old_tools": set(),
    }

    def _before_force_unload(plugin_id: str) -> None:
        logger.info(
            "Force-reinstall: unloading '%s' before re-installing",
            plugin_id,
        )
        # Snapshot under the lifecycle lock (caller holds it).
        old_record = loader.get_loaded_plugin(plugin_id)
        if old_record is not None:
            collected["old_tools"] = set(
                _tool_names_from_meta(old_record.manifest.meta or {}),
            )

    async def _after_load(record) -> None:
        await _finish_plugin_install_after_load(
            request,
            record,
            force=force,
            old_tools=collected["old_tools"],
        )

    return await loader.load_plugin_from_path(
        source_path=source_path,
        install_dir=install_dir,
        force=force,
        before_force_unload=_before_force_unload if force else None,
        after_load=_after_load,
    )


async def _finish_plugin_install_after_load(
    request: Request,
    record,
    *,
    force: bool,
    old_tools: set,
) -> None:
    """Post-load setup with force-reinstall tool cleanup.

    Workspace contributions are projected by startup hooks; agents
    are not rebuilt.
    """
    await _post_load_setup(request, record.manifest.id)
    if force:
        new_tools = set(
            _tool_names_from_meta(record.manifest.meta or {}),
        )
        removed_tools = sorted(old_tools - new_tools)
        if removed_tools:
            await asyncio.to_thread(
                _remove_named_tools_from_agents,
                record.manifest.id,
                removed_tools,
            )


def _extract_plugin_zip_bytes(content: bytes, temp_dir: Path) -> Path:
    """Write ZIP bytes, safely extract, return plugin dir (sync I/O)."""
    zip_path = temp_dir / "plugin.zip"
    zip_path.write_bytes(content)
    with zipfile.ZipFile(zip_path, "r") as zf:
        _safe_extract_zip(zf, temp_dir)
    zip_path.unlink(missing_ok=True)
    return _find_plugin_dir(temp_dir)


def _extract_downloaded_plugin_zip(zip_path: Path, temp_dir: Path) -> Path:
    """Safely extract an on-disk ZIP and return the plugin dir (sync I/O)."""
    with zipfile.ZipFile(zip_path, "r") as zf:
        _safe_extract_zip(zf, temp_dir)
    zip_path.unlink(missing_ok=True)
    return _find_plugin_dir(temp_dir)


# ── Routes ───────────────────────────────────────────────────────────────


@router.get(
    "",
    summary="List loaded plugins",
    description="Return all loaded plugins with optional UI metadata.",
)
async def list_plugins(request: Request):
    """Return every loaded plugin with basic metadata and entry points.

    If the plugin loader has not yet finished initialising (backend
    still starting up when the frontend first requests the list), the
    response is built by scanning the plugins directory on disk.
    """
    loader = getattr(request.app.state, "plugin_loader", None)

    if loader is None:
        logger.debug(
            "[plugins] plugin_loader not ready, falling back to disk scan",
        )
        return _list_plugins_from_disk()

    from ...plugins.settings import is_plugin_enabled

    result = []
    for plugin_id, record in loader.get_all_loaded_plugins().items():
        manifest = record.manifest
        raw = _plugin_config_row(plugin_id)
        result.append(
            {
                "id": manifest.id,
                "name": manifest.name,
                "version": manifest.version,
                "description": manifest.description,
                "author": manifest.author,
                "enabled": is_plugin_enabled(raw),
                "loaded": True,
                "status": getattr(record, "status", "active"),
                "diagnostics": list(record.diagnostics or []),
                "plugin_type": manifest.plugin_type,
                "frontend_entry": manifest.entry.frontend,
            },
        )

    return result


@router.get(
    "/catalog",
    summary="Official plugin catalog",
    description=(
        "Proxy the download CDN plugin manifest for in-app browsing. "
        "Marks plugins already installed under the working directory."
    ),
)
async def get_plugin_catalog():
    """Return official plugins from OSS metadata (server-side fetch)."""
    from ...plugins.download_catalog import fetch_plugin_catalog_async

    return await fetch_plugin_catalog_async()


class InstallPluginRequest(BaseModel):
    """Request body for installing a plugin from a path or URL."""

    source: str
    force: bool = False


@router.post(
    "/install",
    summary="Install plugin from path or URL",
    description=(
        "Install a plugin at runtime from a local directory path or a "
        "remote ZIP URL.  The plugin is loaded immediately — no restart "
        "required."
    ),
)
async def install_plugin(
    body: InstallPluginRequest,
    request: Request,
):
    """Install and hot-load a plugin from a local path or HTTP(S) URL.

    On success the plugin is immediately available; all agents are
    reloaded in the background so that newly registered tools can be
    used without a server restart.
    """
    loader = getattr(request.app.state, "plugin_loader", None)
    if loader is None:
        raise HTTPException(
            status_code=503,
            detail="Plugin loader is not ready yet. Try again shortly.",
        )

    source = body.source.strip()
    is_url = source.startswith(("http://", "https://"))
    temp_dir: Optional[Path] = None

    try:
        if is_url:
            # Download and extract the zip archive
            temp_dir = Path(await asyncio.to_thread(tempfile.mkdtemp))
            zip_path = temp_dir / "plugin.zip"
            logger.info(f"Downloading plugin from {_log_safe(source)}")
            await _async_download(source, zip_path)
            source_path = await asyncio.to_thread(
                _extract_downloaded_plugin_zip,
                zip_path,
                temp_dir,
            )
        else:
            source_path = await asyncio.to_thread(Path(source).resolve)
            if not await asyncio.to_thread(source_path.exists):
                raise HTTPException(
                    status_code=400,
                    detail=f"Path not found: {source}",
                )

        # Load + post-load setup share one lifecycle lock.
        record = await _load_plugin_with_optional_force_reinstall(
            loader,
            request,
            source_path,
            force=body.force,
        )
    except HTTPException:
        raise
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except (FileNotFoundError, RuntimeError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.error(f"Plugin install failed: {exc}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Plugin installation failed: {exc}",
        ) from exc
    finally:
        if temp_dir is not None and await asyncio.to_thread(temp_dir.exists):
            await asyncio.to_thread(shutil.rmtree, temp_dir, True)

    return {
        "id": record.manifest.id,
        "name": record.manifest.name,
        "version": record.manifest.version,
        "description": record.manifest.description,
        "author": record.manifest.author,
        "loaded": True,
        "message": (
            f"Plugin '{record.manifest.name}' installed successfully."
        ),
    }


@router.post(
    "/upload",
    summary="Install plugin from ZIP upload",
    description=(
        "Upload a plugin ZIP file and install it at runtime.  The "
        "plugin is loaded immediately — no restart required.  Pass "
        "``force=true`` as a query parameter to reinstall an already-"
        "loaded plugin."
    ),
)
async def upload_plugin(
    request: Request,
    file: UploadFile = File(..., description="Plugin ZIP archive"),
    force: bool = False,
):
    """Install and hot-load a plugin from an uploaded ZIP file."""
    loader = getattr(request.app.state, "plugin_loader", None)
    if loader is None:
        raise HTTPException(
            status_code=503,
            detail="Plugin loader is not ready yet. Try again shortly.",
        )

    if not file.filename or not file.filename.endswith(".zip"):
        raise HTTPException(
            status_code=400,
            detail="Only .zip archives are accepted.",
        )

    temp_dir = Path(await asyncio.to_thread(tempfile.mkdtemp))
    try:
        content = await file.read()
        source_path = await asyncio.to_thread(
            _extract_plugin_zip_bytes,
            content,
            temp_dir,
        )

        # Load + post-load setup share one lifecycle lock.
        record = await _load_plugin_with_optional_force_reinstall(
            loader,
            request,
            source_path,
            force=force,
        )
    except HTTPException:
        raise
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except (FileNotFoundError, RuntimeError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.error(f"Plugin upload failed: {exc}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Plugin installation failed: {exc}",
        ) from exc
    finally:
        if await asyncio.to_thread(temp_dir.exists):
            await asyncio.to_thread(shutil.rmtree, temp_dir, True)

    return {
        "id": record.manifest.id,
        "name": record.manifest.name,
        "version": record.manifest.version,
        "description": record.manifest.description,
        "author": record.manifest.author,
        "loaded": True,
        "message": (
            f"Plugin '{record.manifest.name}' installed successfully."
        ),
    }


@router.delete(
    "/{plugin_id}",
    summary="Uninstall a plugin",
    description=(
        "Unload and permanently delete a plugin, including plugins "
        "that are not currently loaded (disabled or FAILED)."
    ),
)
async def uninstall_plugin(plugin_id: str, request: Request):
    """Unload and delete a plugin by ID."""
    loader = getattr(request.app.state, "plugin_loader", None)
    if loader is None:
        raise HTTPException(
            status_code=503,
            detail="Plugin loader is not ready yet.",
        )

    # Full uninstall transaction under one lifecycle lock so record/meta
    # capture, unload, and agent-config cleanup cannot race a concurrent
    # reinstall of the same id (stale meta must not delete the wrong tools).
    try:
        async with loader.plugin_lifecycle(plugin_id):
            record = loader.get_loaded_plugin(plugin_id)
            meta: dict = {}
            if record is not None:
                meta = record.manifest.meta or {}
            else:
                source = loader.find_installed_plugin_dir(plugin_id)
                if source is not None:
                    _path, manifest = await asyncio.to_thread(
                        loader.read_source_manifest,
                        source,
                    )
                    del _path
                    meta = manifest.meta or {}

            from ...plugins.lifecycle import UnloadMode

            await loader.unload_plugin(
                plugin_id,
                delete_files=True,
                mode=UnloadMode.UNINSTALL,
            )
            await asyncio.to_thread(
                _remove_plugin_tools_from_agents,
                plugin_id,
                meta,
            )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        logger.error(
            f"Plugin uninstall failed for '{_log_safe(plugin_id)}': {exc}",
            exc_info=True,
        )
        raise HTTPException(
            status_code=500,
            detail=f"Plugin uninstallation failed: {exc}",
        ) from exc

    return {
        "id": plugin_id,
        "message": f"Plugin '{plugin_id}' uninstalled successfully.",
    }


@router.post(
    "/{plugin_id}/unload",
    summary="Unload a plugin without deleting user data",
    description=(
        "Remove the plugin from the process (mode=unload). "
        "agent.json and config.plugins are left unchanged."
    ),
)
async def unload_plugin_keep_config(plugin_id: str, request: Request):
    """Callable entry for ``unload(mode=unload)``."""
    loader = getattr(request.app.state, "plugin_loader", None)
    if loader is None:
        raise HTTPException(
            status_code=503,
            detail="Plugin loader is not ready yet.",
        )
    from ...plugins.lifecycle import UnloadMode

    try:
        async with loader.plugin_lifecycle(plugin_id):
            report = await loader.unload_plugin(
                plugin_id,
                delete_files=False,
                mode=UnloadMode.UNLOAD,
            )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {
        "id": plugin_id,
        "clean": report.clean,
        "errors": report.errors,
        "message": f"Plugin '{plugin_id}' unloaded.",
    }


@router.post(
    "/{plugin_id}/repair-dependencies",
    summary="Repair plugin dependencies",
    description=(
        "Explicitly install missing plugin dependencies, then load. "
        "Host-package upgrades are rejected and require a backend restart."
    ),
)
async def repair_plugin_dependencies(plugin_id: str, request: Request):
    """User-triggered dependency repair (boot never installs)."""
    loader = getattr(request.app.state, "plugin_loader", None)
    if loader is None:
        raise HTTPException(
            status_code=503,
            detail="Plugin loader is not ready yet.",
        )
    try:
        record = await loader.repair_dependencies(plugin_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except Exception as exc:
        logger.error(
            "Repair dependencies failed for '%s': %s",
            _log_safe(plugin_id),
            exc,
            exc_info=True,
        )
        raise HTTPException(
            status_code=500,
            detail=f"Repair failed: {exc}",
        ) from exc
    return {
        "id": plugin_id,
        "status": record.status,
        "enabled": record.enabled,
        "diagnostics": list(record.diagnostics or []),
        "message": (
            f"Plugin '{plugin_id}' repaired."
            if record.status != "failed"
            else f"Plugin '{plugin_id}' still failed."
        ),
    }


@router.get(
    "/{plugin_id}/status",
    summary="Get plugin status",
    description="Return the runtime status of a single plugin.",
)
async def get_plugin_status(plugin_id: str, request: Request):
    """Return the runtime status of a plugin."""
    loader = getattr(request.app.state, "plugin_loader", None)

    from ...plugins.settings import is_plugin_enabled

    raw = _plugin_config_row(plugin_id)
    enabled = is_plugin_enabled(raw)
    if loader is not None:
        record = loader.get_loaded_plugin(plugin_id)
        if record is not None:
            return {
                "id": plugin_id,
                "loaded": True,
                "enabled": enabled,
                "status": getattr(record, "status", "active"),
                "diagnostics": list(record.diagnostics or []),
                "version": record.manifest.version,
            }

    # Check disk even if loader is not ready or plugin is not loaded
    from ...config.utils import get_plugins_dir

    plugin_dir = get_plugins_dir() / plugin_id
    if plugin_dir.is_dir() and (plugin_dir / "plugin.json").exists():
        return {
            "id": plugin_id,
            "loaded": False,
            "enabled": enabled,
        }

    raise HTTPException(
        status_code=404,
        detail=f"Plugin '{plugin_id}' not found.",
    )


class UpdatePluginConfigRequest(BaseModel):
    """Replace the plugin-facing config without reimporting the module."""

    config: dict
    confirm_legacy: bool = False


class SetPluginEnabledRequest(BaseModel):
    """Enable or disable a plugin via ``config.plugins.<id>.enabled``."""

    enabled: bool


@router.put(
    "/{plugin_id}/config",
    summary="Update plugin configuration",
    description=(
        "Rebuild the plugin's runtime contributions from a new config "
        "without reimporting the module. Legacy uninstall hooks require "
        "``confirm_legacy=true``."
    ),
)
async def update_plugin_config(
    plugin_id: str,
    body: UpdatePluginConfigRequest,
    request: Request,
):
    """Apply a new plugin config, rolling back on a half-finished register."""
    loader = getattr(request.app.state, "plugin_loader", None)
    if loader is None:
        raise HTTPException(
            status_code=503,
            detail="Plugin loader is not ready yet.",
        )
    report = await loader.lifecycle.update_config(
        plugin_id,
        body.config,
        confirm_legacy=body.confirm_legacy,
    )
    if report.requires_confirmation:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "legacy_uninstall_hook",
                "message": (
                    report.errors[0]
                    if report.errors
                    else "legacy uninstall hook requires confirmation"
                ),
                "legacy_hooks": report.legacy_hooks,
                "requires_confirmation": True,
            },
        )
    if not report.ok:
        status = 404 if report.unchanged else 400
        raise HTTPException(
            status_code=status,
            detail={
                "message": (
                    report.errors[0]
                    if report.errors
                    else "config update failed"
                ),
                "errors": report.errors,
                "unchanged": report.unchanged,
            },
        )
    if plugin_id in loader.get_all_loaded_plugins():
        await _post_load_setup(request, plugin_id)
    return {
        "id": plugin_id,
        "ok": True,
        "message": f"Plugin '{plugin_id}' config updated.",
    }


@router.post(
    "/{plugin_id}/enabled",
    summary="Enable or disable a plugin",
    description=(
        "Persist ``enabled`` in config.plugins. Disabling unloads the "
        "instance without deleting files; enabling loads it from disk."
    ),
)
async def set_plugin_enabled(
    plugin_id: str,
    body: SetPluginEnabledRequest,
    request: Request,
):
    """Toggle whether a plugin is loaded on this host."""
    loader = getattr(request.app.state, "plugin_loader", None)
    if loader is None:
        raise HTTPException(
            status_code=503,
            detail="Plugin loader is not ready yet.",
        )
    from ...config.utils import get_plugins_dir

    plugin_dir = get_plugins_dir() / plugin_id
    if not (plugin_dir / "plugin.json").is_file():
        if loader.get_loaded_plugin(plugin_id) is None:
            raise HTTPException(
                status_code=404,
                detail=f"Plugin '{plugin_id}' not found.",
            )
    try:
        if not body.enabled:
            result = await loader.lifecycle.set_enabled(plugin_id, False)
            clean = getattr(result, "clean", True)
            return {
                "id": plugin_id,
                "enabled": False,
                "loaded": False,
                "clean": clean,
                "message": f"Plugin '{plugin_id}' disabled.",
            }
        record = await loader.lifecycle.set_enabled(plugin_id, True)
        if record is not None:
            await _post_load_setup(request, plugin_id)
        return {
            "id": plugin_id,
            "enabled": True,
            "loaded": record is not None,
            "status": getattr(record, "status", "inactive"),
            "message": f"Plugin '{plugin_id}' enabled.",
        }
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        logger.error(
            "Failed to set enabled=%s for plugin '%s': %s",
            body.enabled,
            _log_safe(plugin_id),
            exc,
            exc_info=True,
        )
        raise HTTPException(
            status_code=500,
            detail=f"Failed to update plugin enabled state: {exc}",
        ) from exc


@router.get(
    "/{plugin_id}/files/{file_path:path}",
    summary="Serve plugin static file",
    description="Serve a static file from a plugin's directory.",
)
async def serve_plugin_ui_file(
    plugin_id: str,
    file_path: str,
    request: Request,
):
    """Serve a static file that belongs to a plugin (JS / CSS / images).

    When the plugin loader is ready, the plugin's source path is taken
    from the in-memory record.  If the loader is not yet initialised,
    the file is resolved directly from the plugins directory on disk.

    A path-traversal guard ensures the resolved path stays inside the
    plugin's source directory.
    """
    loader = getattr(request.app.state, "plugin_loader", None)

    if loader is not None:
        record = loader.get_loaded_plugin(plugin_id)
        if record is None:
            raise HTTPException(
                404,
                f"Plugin '{plugin_id}' not found",
            )
        source_path: Path = record.source_path
    else:
        from ...config.utils import get_plugins_dir

        candidate = get_plugins_dir() / plugin_id
        if not candidate.is_dir() or not (candidate / "plugin.json").exists():
            raise HTTPException(
                404,
                f"Plugin '{plugin_id}' not found",
            )
        source_path = candidate

    full_path = (source_path / file_path).resolve()

    if not full_path.is_relative_to(source_path.resolve()):
        raise HTTPException(403, "Access denied")

    if not full_path.exists() or not full_path.is_file():
        raise HTTPException(404, f"File not found: {file_path}")

    content_type, _ = mimetypes.guess_type(str(full_path))

    if full_path.suffix in (".js", ".mjs"):
        content_type = "application/javascript"
    elif full_path.suffix == ".css":
        content_type = "text/css"

    # Content-hashed chunks are safe to cache long-term; entry files must
    # revalidate on every request or browsers keep serving stale bundles
    # after a plugin hot update.
    hashed_asset = re.search(r"-[A-Za-z0-9_]{8,}\.[a-z0-9]+$", full_path.name)
    cache_control = (
        "public, max-age=31536000, immutable" if hashed_asset else "no-cache"
    )
    headers = {"Cache-Control": cache_control}

    if content_type:
        return FileResponse(
            str(full_path),
            media_type=content_type,
            headers=headers,
        )

    return FileResponse(str(full_path), headers=headers)


# ── Plugin market proxy ───────────────────────────────────────────────────

_PLUGIN_MARKET_BASE_URL = "https://platform.agentscope.io"
_PLUGIN_MARKET_TIMEOUT = 15


@router.get(
    "/market/search",
    summary="Search plugins from AgentScope Platform",
)
async def search_market_plugins(
    page_number: int = 1,
    page_size: int = 20,
    search: Optional[str] = None,
    category: Optional[str] = None,
    sort_by: Optional[str] = None,
    is_featured: Optional[bool] = None,
    is_trending: Optional[bool] = None,
):
    """Proxy plugin search to AgentScope Platform to avoid CORS."""
    import httpx

    params: dict = {
        "page_number": page_number,
        "page_size": page_size,
    }
    if search:
        params["search"] = search
    if category:
        params["category"] = category
    if sort_by:
        params["sort_by"] = sort_by
    if is_featured is not None:
        params["is_featured"] = is_featured
    if is_trending is not None:
        params["is_trending"] = is_trending

    try:
        async with httpx.AsyncClient(
            timeout=_PLUGIN_MARKET_TIMEOUT,
        ) as client:
            resp = await client.get(
                f"{_PLUGIN_MARKET_BASE_URL}/openapi/v1/plugins",
                params=params,
            )
            resp.raise_for_status()
            return resp.json()
    except Exception as exc:
        logger.warning("Plugin market search failed: %s", exc)
        raise HTTPException(
            status_code=502,
            detail=f"Failed to fetch from plugin market: {exc}",
        ) from exc


# ── Internal async helpers ────────────────────────────────────────────────


_DOWNLOAD_TIMEOUT = 60  # seconds per read chunk; total limit is implicit

_MAX_DOWNLOAD_BYTES = 500 * 1024 * 1024  # 500 MB safety cap


async def _async_download(url: str, dest: Path) -> None:
    """Download a URL to a file using a thread pool.

    Streams the response in chunks with a per-operation socket timeout
    so a stalled server cannot hang the request indefinitely.

    Args:
        url: HTTP(S) URL to download
        dest: Destination file path

    Raises:
        RuntimeError: If the download exceeds the size cap or times out.
    """

    def _download() -> None:
        with urllib.request.urlopen(
            url,
            timeout=_DOWNLOAD_TIMEOUT,
        ) as resp:
            total = 0
            with open(dest, "wb") as fh:
                while True:
                    chunk = resp.read(65536)
                    if not chunk:
                        break
                    total += len(chunk)
                    if total > _MAX_DOWNLOAD_BYTES:
                        raise RuntimeError(
                            f"Download aborted: response exceeds "
                            f"{_MAX_DOWNLOAD_BYTES // (1024 * 1024)} MB",
                        )
                    fh.write(chunk)

    await asyncio.to_thread(_download)
