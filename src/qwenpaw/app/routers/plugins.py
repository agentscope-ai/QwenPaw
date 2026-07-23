# -*- coding: utf-8 -*-
# pylint:disable=too-many-branches
"""Plugin API routes: list plugins with UI metadata and serve plugin
static files.  Also provides runtime install / uninstall endpoints."""

import asyncio
import inspect
import json
import logging
import mimetypes
import shutil
import tempfile
import urllib.request
import zipfile
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException, Request, UploadFile, File
from fastapi.responses import FileResponse
from pydantic import BaseModel

from ..utils import schedule_agent_reload

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/plugins", tags=["plugins"])

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

        disk_manifest = PluginManifest.from_dict(manifest)

        result.append(
            {
                "id": plugin_id,
                "name": manifest.get("name", plugin_id),
                "version": manifest.get("version", "0.0.0"),
                "description": manifest.get("description", ""),
                "author": manifest.get("author", ""),
                "enabled": True,
                "loaded": False,
                "plugin_type": disk_manifest.plugin_type,
                "frontend_entry": frontend_entry,
            },
        )
    return result


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
                provider_manager.register_plugin_provider(
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
    for hook in registry.get_startup_hooks():
        if hook.plugin_id != plugin_id:
            continue
        try:
            result = hook.callback()
            if inspect.iscoroutine(result) or inspect.isawaitable(result):
                await result
        except Exception as exc:
            logger.error(
                f"Startup hook '{hook.hook_name}' failed: {exc}",
            )

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
                    f"Failed to remove tools from agent '{agent_id}': {exc}",
                )
    except Exception as exc:
        logger.warning(
            f"Tool removal from agents skipped for '{plugin_id}': {exc}",
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


async def _schedule_all_agents_reload(request: Request) -> None:
    """Schedule a reload for every configured agent.

    Args:
        request: FastAPI request (for app.state access)
    """
    try:
        from ...config.utils import load_config

        config = await asyncio.to_thread(load_config)
        if not config.agents or not config.agents.profiles:
            return
        for agent_id in config.agents.profiles:
            schedule_agent_reload(request, agent_id)
    except Exception as exc:
        logger.warning(f"Could not schedule agent reloads: {exc}")


def _post_unload_cleanup(
    request: Request,
    plugin_id: str,
    provider_ids: list,
    command_names: list,
) -> None:
    """Clean up runtime registrations after a plugin has been unloaded.

    Removes the plugin's providers from ``provider_manager`` and its
    control commands from both the handler registry and the priority
    registry.  Called after ``loader.unload_plugin()`` so that UI lists
    and command routing reflect the removal immediately.

    Args:
        request: FastAPI request (for ``app.state`` access).
        plugin_id: ID of the unloaded plugin (for logging).
        provider_ids: Provider IDs that were registered by this plugin.
        command_names: Command names that were registered by this plugin.
    """
    # ── Providers ────────────────────────────────────────────────────────
    provider_manager = getattr(
        request.app.state,
        "provider_manager",
        None,
    )
    if provider_manager is not None:
        for pid in provider_ids:
            try:
                provider_manager.unregister_plugin_provider(pid)
            except Exception as exc:
                logger.warning(
                    f"Could not unregister provider '{pid}' "
                    f"for plugin '{plugin_id}': {exc}",
                )

    # ── Control commands ─────────────────────────────────────────────────
    if command_names:
        try:
            from ...runtime.commands.control import (
                unregister_command as unregister_handler,
            )
            from ...app.channels.command_registry import CommandRegistry

            command_registry = CommandRegistry()
            for cmd_name in command_names:
                try:
                    unregister_handler(cmd_name)
                except Exception as exc:
                    logger.warning(
                        f"Could not unregister handler '{cmd_name}': {exc}",
                    )
                try:
                    command_registry.unregister_command(f"/{cmd_name}")
                except Exception as exc:
                    logger.warning(
                        f"Could not unregister priority for"
                        f" '/{cmd_name}': {exc}",
                    )
        except Exception as exc:
            logger.warning(
                f"Command cleanup skipped for plugin '{plugin_id}': {exc}",
            )


def _collect_plugin_runtime_ids(
    registry,
    plugin_id: str,
) -> tuple:
    """Collect provider IDs and command names registered by a plugin.

    Must be called *before* ``loader.unload_plugin()`` clears the
    registry entries.

    Args:
        registry: ``PluginRegistry`` instance.
        plugin_id: Plugin whose registrations should be collected.

    Returns:
        ``(provider_ids, command_names)`` tuple of lists.
    """
    provider_ids = [
        pid
        for pid, reg in registry.get_all_providers().items()
        if reg.plugin_id == plugin_id
    ]
    command_names = [
        cmd_reg.handler.command_name
        for cmd_reg in registry.get_control_commands()
        if cmd_reg.plugin_id == plugin_id
    ]
    return provider_ids, command_names


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
        "provider_ids": [],
        "command_names": [],
        "old_tools": set(),
    }

    def _before_force_unload(plugin_id: str) -> None:
        logger.info(
            "Force-reinstall: unloading '%s' before re-installing",
            plugin_id,
        )
        provider_ids, command_names = _collect_plugin_runtime_ids(
            loader.registry,
            plugin_id,
        )
        collected["provider_ids"] = provider_ids
        collected["command_names"] = command_names
        # Snapshot under the lifecycle lock (caller holds it).
        old_record = loader.get_loaded_plugin(plugin_id)
        if old_record is not None:
            collected["old_tools"] = set(
                _tool_names_from_meta(old_record.manifest.meta or {}),
            )

    def _after_force_unload(plugin_id: str) -> None:
        _post_unload_cleanup(
            request,
            plugin_id,
            collected["provider_ids"],
            collected["command_names"],
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
        after_force_unload=_after_force_unload if force else None,
        after_load=_after_load,
    )


async def _finish_plugin_install_after_load(
    request: Request,
    record,
    *,
    force: bool,
    old_tools: set,
) -> None:
    """Post-load setup with force-reinstall tool cleanup before reload.

    Guaranteed order:
    1. sync new tools / providers / hooks (``_post_load_setup``)
    2. remove obsolete tools (``old_tools - new_tools``) when *force*
    3. schedule agent reload
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
    await _schedule_all_agents_reload(request)


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

    result = []
    for _plugin_id, record in loader.get_all_loaded_plugins().items():
        manifest = record.manifest
        result.append(
            {
                "id": manifest.id,
                "name": manifest.name,
                "version": manifest.version,
                "description": manifest.description,
                "author": manifest.author,
                "enabled": record.enabled,
                "loaded": True,
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
            logger.info(f"Downloading plugin from {source}")
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
        "Unload and permanently delete a plugin.  All agents are "
        "reloaded in the background so tool changes take effect "
        "immediately."
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
            if record is None:
                raise KeyError(f"Plugin '{plugin_id}' is not loaded.")
            meta: dict = record.manifest.meta or {}

            provider_ids, command_names = _collect_plugin_runtime_ids(
                loader.registry,
                plugin_id,
            )
            await loader.unload_plugin(plugin_id, delete_files=True)
            _post_unload_cleanup(
                request,
                plugin_id,
                provider_ids,
                command_names,
            )
            await asyncio.to_thread(
                _remove_plugin_tools_from_agents,
                plugin_id,
                meta,
            )
            await _schedule_all_agents_reload(request)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        logger.error(
            f"Plugin uninstall failed for '{plugin_id}': {exc}",
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


@router.get(
    "/{plugin_id}/status",
    summary="Get plugin status",
    description="Return the runtime status of a single plugin.",
)
async def get_plugin_status(plugin_id: str, request: Request):
    """Return the runtime status of a plugin."""
    loader = getattr(request.app.state, "plugin_loader", None)

    if loader is not None:
        record = loader.get_loaded_plugin(plugin_id)
        if record is not None:
            return {
                "id": plugin_id,
                "loaded": True,
                "enabled": record.enabled,
                "version": record.manifest.version,
            }

    # Check disk even if loader is not ready or plugin is not loaded
    from ...config.utils import get_plugins_dir

    plugin_dir = get_plugins_dir() / plugin_id
    if plugin_dir.is_dir() and (plugin_dir / "plugin.json").exists():
        return {"id": plugin_id, "loaded": False, "enabled": False}

    raise HTTPException(
        status_code=404,
        detail=f"Plugin '{plugin_id}' not found.",
    )


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

    if content_type:
        return FileResponse(str(full_path), media_type=content_type)

    return FileResponse(str(full_path))


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
