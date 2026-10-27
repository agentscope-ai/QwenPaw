# -*- coding: utf-8 -*-
# pylint:disable=too-many-return-statements,too-many-branches
# pylint:disable=too-many-statements
"""Plugin management CLI commands."""

import asyncio
import json
import logging
import os
import shutil
import tempfile
import urllib.request
import zipfile
from pathlib import Path
from typing import Optional

import click
import httpx

from ..config import utils as config_utils
from ..utils.runtime_api import api_client, read_runtime_api

from ..plugins.validation import (
    validate_plugin_module as _validate_plugin_module,
)

logger = logging.getLogger(__name__)


# ── Live-API helpers ──────────────────────────────────────────────────────


def _get_api_base() -> Optional[str]:
    """Return the base URL of the running QwenPaw API, or None.

    Returns:
        Base URL string such as ``http://127.0.0.1:8088/api`` if the
        app is running, otherwise ``None``.
    """
    api_info = read_runtime_api()
    if os.environ.get("QWENPAW_RUNTIME_ID") and api_info is None:
        raise click.ClickException("Managed runtime endpoint is unavailable")
    api_info = api_info or config_utils.read_last_api()
    if api_info is None:
        return None
    host, port = api_info
    return f"http://{host}:{port}/api"


def _api_install_plugin(source: str, force: bool = False) -> bool:
    """Send a hot-install request to the running QwenPaw API.

    Authenticates to the current managed runtime when required.

    Args:
        source: Local directory path or HTTP(S) URL of the plugin
        force: Unload existing plugin first if already loaded

    Returns:
        ``True`` on success, ``False`` otherwise
    """
    base = _get_api_base()
    if base is None:
        return False

    try:
        with api_client(base, timeout=120) as client:
            response = client.post(
                "plugins/install",
                json={"source": source, "force": force},
                follow_redirects=True,
            )
            response.raise_for_status()
            body = response.json()
        name = body.get("name", source)
        click.echo(
            f"✅ Plugin '{name}' installed and loaded (hot reload).",
        )
        for diagnostic in body.get("diagnostics", []):
            click.echo(diagnostic)
        return True
    except httpx.HTTPStatusError as exc:
        try:
            detail = exc.response.json().get("detail", str(exc))
        except Exception:
            detail = str(exc)
        click.echo(f"❌ API install failed: {detail}", err=True)
        if os.environ.get("QWENPAW_RUNTIME_ID"):
            raise click.ClickException(str(exc)) from exc
        return False
    except Exception as exc:
        if os.environ.get("QWENPAW_RUNTIME_ID"):
            raise click.ClickException(str(exc)) from exc
        click.echo(f"❌ API request failed: {exc}", err=True)
        return False


def _api_upload_plugin(zip_path: Path, force: bool = False) -> bool:
    """Send a ZIP file to the running QwenPaw API for hot-install.

    Args:
        zip_path: Path to the plugin .zip archive
        force: Unload existing plugin first if already loaded

    Returns:
        ``True`` on success, ``False`` otherwise
    """
    base = _get_api_base()
    if base is None:
        return False

    # Build a minimal multipart/form-data body by hand so we avoid
    # depending on the ``requests`` library.
    boundary = "----QwenPawPluginUpload"
    content = zip_path.read_bytes()
    body = (
        (
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="file"; '
            f'filename="{zip_path.name}"\r\n'
            f"Content-Type: application/zip\r\n\r\n"
        ).encode()
        + content
        + f"\r\n--{boundary}--\r\n".encode()
    )

    force_param = "true" if force else "false"
    try:
        with api_client(base, timeout=120) as client:
            response = client.post(
                "plugins/upload",
                params={"force": force_param},
                content=body,
                follow_redirects=True,
                headers={
                    "Content-Type": (
                        "multipart/form-data; " f"boundary={boundary}"
                    ),
                },
            )
            response.raise_for_status()
            result = response.json()
        name = result.get("name", zip_path.name)
        click.echo(
            f"✅ Plugin '{name}' installed and loaded (hot reload).",
        )
        for diagnostic in result.get("diagnostics", []):
            click.echo(diagnostic)
        return True
    except httpx.HTTPStatusError as exc:
        try:
            detail = exc.response.json().get("detail", str(exc))
        except Exception:
            detail = str(exc)
        click.echo(f"❌ API upload failed: {detail}", err=True)
        if os.environ.get("QWENPAW_RUNTIME_ID"):
            raise click.ClickException(str(exc)) from exc
        return False
    except Exception as exc:
        if os.environ.get("QWENPAW_RUNTIME_ID"):
            raise click.ClickException(str(exc)) from exc
        click.echo(f"❌ API request failed: {exc}", err=True)
        return False


def _api_uninstall_plugin(plugin_id: str) -> bool:
    """Send a hot-uninstall request to the running QwenPaw API.

    Args:
        plugin_id: ID of the plugin to remove

    Returns:
        ``True`` on success, ``False`` otherwise
    """
    base = _get_api_base()
    if base is None:
        return False

    try:
        with api_client(base) as client:
            response = client.delete(f"plugins/{plugin_id}")
            response.raise_for_status()
            body = response.json()
        click.echo(
            body.get(
                "message",
                f"✅ Plugin '{plugin_id}' uninstalled.",
            ),
        )
        return True
    except httpx.HTTPStatusError as exc:
        try:
            detail = exc.response.json().get("detail", str(exc))
        except Exception:
            detail = str(exc)
        click.echo(f"❌ API uninstall failed: {detail}", err=True)
        if os.environ.get("QWENPAW_RUNTIME_ID"):
            raise click.ClickException(str(exc)) from exc
        return False
    except Exception as exc:
        if os.environ.get("QWENPAW_RUNTIME_ID"):
            raise click.ClickException(str(exc)) from exc
        click.echo(f"❌ API request failed: {exc}", err=True)
        return False


def _is_running() -> bool:
    """Return whether QwenPaw is currently running.

    Returns:
        ``True`` if the API is reachable, ``False`` otherwise.
    """
    from ..config.utils import is_qwenpaw_running

    return is_qwenpaw_running()


def _safe_extract_zip(zip_ref: zipfile.ZipFile, extract_path: Path):
    """Safely extract zip file, preventing Zip Slip attacks.

    Args:
        zip_ref: ZipFile object
        extract_path: Target extraction directory

    Raises:
        ValueError: If any zip member attempts path traversal
    """
    extract_resolved = extract_path.resolve()
    for member in zip_ref.namelist():
        member_path = (extract_path / member).resolve()
        if not member_path.is_relative_to(extract_resolved):
            raise ValueError(
                f"Zip Slip detected: {member} attempts to extract "
                f"outside target directory",
            )
    zip_ref.extractall(extract_path)


def _download_plugin_from_url(url: str) -> tuple[Path, Path]:
    """Download and extract plugin from URL.

    Args:
        url: Plugin zip file URL

    Returns:
        Tuple of (plugin_directory_path, temp_directory_for_cleanup)

    Raises:
        Exception: If download or extraction fails
    """
    click.echo(f"📥 Downloading plugin from {url}")

    # Download to temporary file
    with tempfile.NamedTemporaryFile(suffix=".zip", delete=False) as tmp_file:
        urllib.request.urlretrieve(url, tmp_file.name)
        zip_path = Path(tmp_file.name)

    # Extract to temporary directory
    temp_dir = Path(tempfile.mkdtemp())
    try:
        with zipfile.ZipFile(zip_path, "r") as zip_ref:
            # Safe extraction with Zip Slip protection
            _safe_extract_zip(zip_ref, temp_dir)
        click.echo("✓ Downloaded and extracted")

        # Find the plugin directory (should be the only directory or root)
        plugin_dirs = [d for d in temp_dir.iterdir() if d.is_dir()]
        if len(plugin_dirs) == 1:
            return plugin_dirs[0], temp_dir
        if (temp_dir / "plugin.json").exists():
            return temp_dir, temp_dir
        raise ValueError("Invalid plugin archive structure")
    finally:
        # Clean up zip file
        zip_path.unlink()


@click.group()
def plugin():
    """Plugin management commands."""


@plugin.command()
@click.argument("source")
@click.option(
    "--force",
    is_flag=True,
    help="Force reinstall if already exists",
)
def install(source: str, force: bool):
    """Install a plugin from local path or URL.

    When QwenPaw is running, the plugin is hot-loaded immediately via
    the API (no restart required).  When QwenPaw is stopped, the
    plugin files are copied and will be loaded on next start.

    Examples:
        qwenpaw plugin install examples/plugins/idealab-provider
        qwenpaw plugin install /path/to/plugin
        qwenpaw plugin install https://example.com/plugin.zip
    """
    # If the app is running, delegate to the live API for hot-install
    if os.environ.get("QWENPAW_RUNTIME_ID") or _is_running():
        click.echo(
            "QwenPaw is running — using hot-install via API...",
        )
        is_url = source.startswith(("http://", "https://"))
        if is_url:
            # API accepts URLs directly
            _api_install_plugin(source, force=force)
        else:
            # Check whether the local path is a directory or a zip
            source_path = Path(source).resolve()
            if not source_path.exists():
                click.echo(
                    f"❌ Path not found: {source}",
                    err=True,
                )
                return
            if source_path.is_file() and source_path.suffix == ".zip":
                _api_upload_plugin(source_path, force=force)
            elif source_path.is_dir():
                _api_install_plugin(str(source_path), force=force)
            else:
                click.echo(
                    "❌ Source must be a directory or a .zip file.",
                    err=True,
                )
        return

    # ── Offline install (app is not running) ─────────────────────────

    from ..config.utils import get_plugins_dir

    is_url = source.startswith(("http://", "https://"))
    temp_dir = None

    if is_url:
        try:
            source_path, temp_dir = _download_plugin_from_url(source)
        except Exception as e:
            click.echo(f"❌ Failed to download plugin: {e}", err=True)
            return
    else:
        source_path = Path(source).resolve()
        if not source_path.exists():
            click.echo(f"❌ Path not found: {source}", err=True)
            return

    from ..plugins.loader import PluginLoader

    try:
        loader = PluginLoader([get_plugins_dir()])
        record = asyncio.run(
            loader.install_plugin_files(source_path, force=force),
        )
    except Exception as exc:
        raise click.ClickException(f"Failed to install plugin: {exc}") from exc
    finally:
        if temp_dir is not None:
            try:
                shutil.rmtree(temp_dir, ignore_errors=True)
            except OSError as exc:
                logger.warning("Failed to remove download staging: %s", exc)

    click.echo(
        f"\n✅ Plugin '{record.manifest.name}' installed successfully!",
    )
    click.echo(f"Location: {record.source_path}")
    for diagnostic in record.diagnostics:
        click.echo(diagnostic)
    click.echo("\nNext steps:")
    click.echo("   1. Start QwenPaw to load the plugin")
    click.echo("   2. Configure the plugin in the web UI")


@plugin.command()
def list():  # pylint: disable=redefined-builtin
    """List all installed plugins."""
    from ..config.utils import get_plugins_dir

    plugin_dir = get_plugins_dir()

    if not plugin_dir.exists():
        click.echo("No plugins installed.")
        return

    plugins = []
    for item in plugin_dir.iterdir():
        if not item.is_dir():
            continue

        manifest_path = item / "plugin.json"
        if manifest_path.exists():
            try:
                with open(manifest_path, encoding="utf-8") as f:
                    manifest = json.load(f)
                plugins.append(manifest)
            except Exception as e:
                logger.warning(f"Failed to read {manifest_path}: {e}")

    if not plugins:
        click.echo("No plugins installed.")
        return

    click.echo("\n📦 Installed Plugins:\n")
    for manifest in plugins:
        click.echo(f"  • {manifest['name']} (v{manifest['version']})")
        click.echo(f"    ID: {manifest['id']}")
        click.echo(f"    Description: {manifest.get('description', 'N/A')}")
        click.echo()


@plugin.command()
@click.argument("plugin_id")
def info(plugin_id: str):
    """Show detailed information about a plugin."""
    from ..config.utils import get_plugins_dir

    plugin_dir = get_plugins_dir() / plugin_id

    if not plugin_dir.exists():
        click.echo(f"❌ Plugin '{plugin_id}' not found", err=True)
        return

    manifest_path = plugin_dir / "plugin.json"
    if not manifest_path.exists():
        click.echo(f"❌ plugin.json not found for '{plugin_id}'", err=True)
        return

    try:
        with open(manifest_path, encoding="utf-8") as f:
            manifest = json.load(f)
    except Exception as e:
        click.echo(f"❌ Failed to read plugin.json: {e}", err=True)
        return

    click.echo(f"\n📦 {manifest['name']} (v{manifest['version']})\n")
    click.echo(f"ID: {manifest['id']}")
    click.echo(f"Description: {manifest.get('description', 'N/A')}")
    click.echo(f"Author: {manifest.get('author', 'N/A')}")
    entry = manifest.get("entry", {})
    if entry.get("backend"):
        click.echo(f"Backend Entry: {entry['backend']}")
    if entry.get("frontend"):
        click.echo(f"Frontend Entry: {entry['frontend']}")

    if manifest.get("dependencies"):
        click.echo("Dependencies:")
        for dep in manifest["dependencies"]:
            click.echo(f"  - {dep}")

    # Show meta information if available
    meta = manifest.get("meta", {})
    if meta:
        if meta.get("api_key_url"):
            click.echo("\n🔑 API Key:")
            if meta.get("api_key_hint"):
                hint = meta["api_key_hint"]
                click.echo(f"   {hint}")
            url = meta["api_key_url"]
            click.echo(f"   URL: {url}")

    click.echo(f"\n📍 Location: {plugin_dir}")


def _resolve_plugin_id(plugin_id_or_path: str) -> Optional[str]:
    """Resolve plugin ID from a plugin ID string or a local path.

    If ``plugin_id_or_path`` points to an existing directory that
    contains a ``plugin.json``, the ``id`` field of that manifest is
    returned.  Otherwise the argument is returned as-is so that plain
    IDs like ``gpt-image2-tool`` still work.

    Args:
        plugin_id_or_path: Plugin ID string or path to plugin directory.

    Returns:
        Resolved plugin ID, or ``None`` if the path exists but the
        manifest could not be parsed.
    """
    candidate = Path(plugin_id_or_path)
    if candidate.is_dir():
        manifest_path = candidate / "plugin.json"
        if manifest_path.exists():
            try:
                with open(manifest_path, encoding="utf-8") as fh:
                    return json.load(fh).get("id")
            except Exception as exc:
                logger.warning(
                    f"Failed to read manifest at {manifest_path}: {exc}",
                )
                return None
    return plugin_id_or_path


@plugin.command()
@click.argument("plugin_id")
def uninstall(plugin_id: str):
    """Uninstall a plugin.

    PLUGIN_ID may be either the plugin's ID (e.g. ``gpt-image2-tool``)
    or a path to the plugin directory (e.g. ``plugins/tool/gpt-image2``).

    When QwenPaw is running, the plugin is unloaded immediately via
    the API (no restart required).  When QwenPaw is stopped, only the
    plugin files and owned provisioned resources are removed from disk.
    """
    # Support passing a directory path in addition to a bare plugin ID
    resolved_id = _resolve_plugin_id(plugin_id)
    if resolved_id is None:
        click.echo(
            f"❌ Could not determine plugin ID from '{plugin_id}'",
            err=True,
        )
        return

    # If the app is running, delegate to the live API for hot-uninstall
    if os.environ.get("QWENPAW_RUNTIME_ID") or _is_running():
        click.echo(
            "QwenPaw is running — using hot-uninstall via API...",
        )
        if not click.confirm(
            f"Uninstall plugin '{resolved_id}'?",
        ):
            click.echo("Cancelled.")
            return
        _api_uninstall_plugin(resolved_id)
        return

    plugin_id = resolved_id

    # ── Offline uninstall (app is not running) ────────────────────────

    from ..config.utils import get_plugins_dir

    plugin_dir = get_plugins_dir() / plugin_id

    from ..plugins.provision import inventory_path

    if not plugin_dir.exists() and not inventory_path(plugin_id).is_file():
        click.echo(f"❌ Plugin '{plugin_id}' not found", err=True)
        return

    if not click.confirm(f"Uninstall plugin '{plugin_id}'?"):
        click.echo("Cancelled.")
        return

    from ..plugins.lifecycle import UnloadMode
    from ..plugins.loader import PluginLoader

    try:
        loader = PluginLoader([get_plugins_dir()])
        report = asyncio.run(
            loader.lifecycle.unload(plugin_id, UnloadMode.UNINSTALL),
        )
        if not report.clean or not report.quiescent:
            raise RuntimeError(
                "; ".join(report.errors) or "Cleanup incomplete",
            )
    except Exception as exc:
        raise click.ClickException(
            f"Failed to uninstall plugin: {exc}",
        ) from exc
    click.echo(f"✅ Plugin '{plugin_id}' uninstalled successfully")


@plugin.command()
@click.argument("path")
def validate(path: str):
    """Validate a plugin."""
    plugin_path = Path(path).resolve()

    if not plugin_path.exists():
        click.echo(f"❌ Path not found: {path}", err=True)
        return

    # Check plugin.json
    manifest_path = plugin_path / "plugin.json"
    if not manifest_path.exists():
        click.echo("❌ plugin.json not found", err=True)
        return

    try:
        with open(manifest_path, encoding="utf-8") as f:
            manifest = json.load(f)

        # Validate required fields
        required_fields = ["id", "name", "version"]
        for field in required_fields:
            if field not in manifest:
                click.echo(f"❌ Missing required field: {field}", err=True)
                return

        # Check entry points
        entry = manifest.get("entry", {})
        backend_entry = entry.get("backend")
        if backend_entry:
            _validate_plugin_module(manifest["id"], plugin_path, backend_entry)

        frontend_entry = entry.get("frontend")
        if frontend_entry:
            frontend_path = plugin_path / frontend_entry
            if not frontend_path.exists():
                click.echo(
                    f"⚠️  Frontend entry not found: {frontend_entry} "
                    f"(build may be required)",
                )

        click.echo("✅ Plugin validation passed")
        click.echo(f"\nPlugin: {manifest['name']} (v{manifest['version']})")
        click.echo(f"ID: {manifest['id']}")

    except json.JSONDecodeError as e:
        click.echo(f"❌ Invalid JSON in plugin.json: {e}", err=True)
    except Exception as e:
        click.echo(f"❌ Validation failed: {e}", err=True)
