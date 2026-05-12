# -*- coding: utf-8 -*-
# pylint:disable=too-many-return-statements,too-many-branches
# pylint:disable=too-many-statements
"""Plugin management CLI commands."""

import json
import logging
import os
import shutil
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
import zipfile
from pathlib import Path
from typing import Optional

import click

logger = logging.getLogger(__name__)


# ── Live-API helpers ──────────────────────────────────────────────────────


def _get_api_base() -> Optional[str]:
    """Return the base URL of the running QwenPaw API, or None.

    Returns:
        Base URL string such as ``http://127.0.0.1:8088/api`` if the
        app is running, otherwise ``None``.
    """
    from ..config.utils import read_last_api

    api_info = read_last_api()
    if api_info is None:
        return None
    host, port = api_info
    return f"http://{host}:{port}/api"


def _api_install_plugin(source: str, force: bool = False) -> bool:
    """Send a hot-install request to the running QwenPaw API.

    Uses the localhost auth-bypass so no credentials are required.

    Args:
        source: Local directory path or HTTP(S) URL of the plugin
        force: Unload existing plugin first if already loaded

    Returns:
        ``True`` on success, ``False`` otherwise
    """
    base = _get_api_base()
    if base is None:
        return False

    url = f"{base}/plugins/install"
    payload = json.dumps({"source": source, "force": force}).encode()
    req = urllib.request.Request(
        url,
        data=payload,
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:  # noqa: S310
            body = json.loads(resp.read())
        name = body.get("name", source)
        click.echo(
            f"✅ Plugin '{name}' installed and loaded (hot reload).",
        )
        return True
    except urllib.error.HTTPError as exc:
        try:
            detail = json.loads(exc.read()).get("detail", str(exc))
        except Exception:
            detail = str(exc)
        click.echo(f"❌ API install failed: {detail}", err=True)
        return False
    except Exception as exc:
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
    url = f"{base}/plugins/upload?force={force_param}"
    req = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={
            "Content-Type": f"multipart/form-data; boundary={boundary}",
            "Content-Length": str(len(body)),
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:  # noqa: S310
            result = json.loads(resp.read())
        name = result.get("name", zip_path.name)
        click.echo(
            f"✅ Plugin '{name}' installed and loaded (hot reload).",
        )
        return True
    except urllib.error.HTTPError as exc:
        try:
            detail = json.loads(exc.read()).get("detail", str(exc))
        except Exception:
            detail = str(exc)
        click.echo(f"❌ API upload failed: {detail}", err=True)
        return False
    except Exception as exc:
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

    url = f"{base}/plugins/{plugin_id}"
    req = urllib.request.Request(url, method="DELETE")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:  # noqa: S310
            body = json.loads(resp.read())
        click.echo(
            body.get(
                "message",
                f"✅ Plugin '{plugin_id}' uninstalled.",
            ),
        )
        return True
    except urllib.error.HTTPError as exc:
        try:
            detail = json.loads(exc.read()).get("detail", str(exc))
        except Exception:
            detail = str(exc)
        click.echo(f"❌ API uninstall failed: {detail}", err=True)
        return False
    except Exception as exc:
        click.echo(f"❌ API request failed: {exc}", err=True)
        return False


def _find_uv() -> Optional[str]:
    """Return the path to the ``uv`` binary, or ``None`` if not found.

    Checks PATH first (``shutil.which`` handles PATHEXT on Windows),
    then well-known install locations for Unix and Windows.

    Returns:
        Absolute path string to ``uv``, or ``None``.
    """
    # shutil.which honours PATHEXT on Windows (finds uv.exe automatically)
    found = shutil.which("uv")
    if found:
        return found

    home = Path.home()
    candidates = [
        home / ".local" / "bin" / "uv",  # Linux/macOS script install
        home / ".cargo" / "bin" / "uv",  # Linux/macOS cargo install
    ]
    # Windows-specific locations
    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        candidates.append(
            Path(local_app_data) / "Programs" / "uv" / "uv.exe",
        )
    candidates.append(home / ".cargo" / "bin" / "uv.exe")

    for candidate in candidates:
        if candidate.is_file():
            return str(candidate)
    return None


def _install_requirements_cli(
    requirements_file: Path,
    target_dir: Path,
) -> bool:
    """Install requirements.txt using pip or uv (fallback).

    Tries ``python -m pip`` first.  When pip is absent (uv-managed
    venv), falls back to ``uv pip install``.  On any failure the
    ``target_dir`` is removed and an error is printed.

    Args:
        requirements_file: Path to requirements.txt
        target_dir: Plugin directory to clean up on failure.

    Returns:
        ``True`` on success, ``False`` on failure (error already
        printed).
    """
    req = str(requirements_file)
    timeout = 300

    # ── Attempt 1: python -m pip ──────────────────────────────────────
    try:
        result = subprocess.run(  # pylint: disable=subprocess-run-check
            [sys.executable, "-m", "pip", "install", "-r", req],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        click.echo("❌ Dependency installation timed out.", err=True)
        shutil.rmtree(target_dir, ignore_errors=True)
        return False

    if result.returncode == 0:
        click.echo("Dependencies installed")
        return True

    pip_missing = (
        "No module named pip" in result.stderr
        or "No module named pip" in result.stdout
    )
    if not pip_missing:
        click.echo("❌ Failed to install dependencies:", err=True)
        click.echo(f"  {result.stderr}", err=True)
        shutil.rmtree(target_dir, ignore_errors=True)
        return False

    # ── Attempt 2: uv pip install ─────────────────────────────────────
    uv = _find_uv()
    if uv is None:
        click.echo(
            "❌ pip is not available and uv was not found on PATH.\n"
            f"   Install manually: pip install -r {req}",
            err=True,
        )
        shutil.rmtree(target_dir, ignore_errors=True)
        return False

    click.echo("pip not found, retrying with uv...")
    try:
        uv_result = subprocess.run(  # pylint: disable=subprocess-run-check
            [uv, "pip", "install", "--python", sys.executable, "-r", req],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        click.echo(
            "❌ Dependency installation timed out (via uv).",
            err=True,
        )
        shutil.rmtree(target_dir, ignore_errors=True)
        return False

    if uv_result.returncode != 0:
        click.echo(
            "❌ Failed to install dependencies (via uv):",
            err=True,
        )
        click.echo(f"  {uv_result.stderr}", err=True)
        shutil.rmtree(target_dir, ignore_errors=True)
        return False

    click.echo("Dependencies installed (via uv)")
    return True


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


def _sync_tool_plugin_to_agents(manifest: dict):
    """Add tool plugin to all existing agents.

    Args:
        manifest: Plugin manifest dictionary
    """
    meta = manifest.get("meta", {})
    tool_name = meta.get("tool_name")

    # Only process if this is a tool plugin
    if not tool_name:
        return

    click.echo(f"🔄 Syncing tool '{tool_name}' to all agents...")

    from ..config.utils import load_config

    config = load_config()

    if not config.agents or not config.agents.profiles:
        click.echo("   No agents found, skipping sync")
        return

    from ..config.config import (
        BuiltinToolConfig,
        load_agent_config,
        save_agent_config,
    )

    synced_count = 0
    for agent_id in config.agents.profiles.keys():
        try:
            # Load agent config using agent_id
            agent_config = load_agent_config(agent_id)

            # Check if tool already exists
            if tool_name in agent_config.tools.builtin_tools:
                continue

            # Add tool config using Pydantic model
            agent_config.tools.builtin_tools[tool_name] = BuiltinToolConfig(
                name=tool_name,
                enabled=False,
                config={},
            )

            # Save using config system
            save_agent_config(agent_id, agent_config)

            synced_count += 1

        except Exception as e:
            logger.warning(
                f"Failed to sync tool to {agent_id}: {e}",
            )

    if synced_count > 0:
        click.echo(f"✓ Synced tool to {synced_count} agent(s)")
    else:
        click.echo("   All agents already have this tool")


def _remove_tool_plugin_from_agents(manifest: dict):
    """Remove tool plugin from all agents.

    Args:
        manifest: Plugin manifest dictionary
    """
    meta = manifest.get("meta", {})
    tool_name = meta.get("tool_name")

    # Only process if this is a tool plugin
    if not tool_name:
        return

    click.echo(f"🔄 Removing tool '{tool_name}' from all agents...")

    from ..config.utils import get_agent_dirs

    agent_dirs = get_agent_dirs()
    if not agent_dirs:
        click.echo("   No agents found, skipping cleanup")
        return

    from ..config.config import load_agent_config, save_agent_config

    removed_count = 0
    for agent_dir in agent_dirs:
        agent_json_path = agent_dir / "agent.json"
        if not agent_json_path.exists():
            continue

        try:
            # Load agent config using Pydantic model
            config = load_agent_config(str(agent_dir))

            # Check if tool exists
            if tool_name not in config.tools.builtin_tools:
                continue

            # Remove tool
            del config.tools.builtin_tools[tool_name]

            # Save using config system
            save_agent_config(str(agent_dir), config)

            removed_count += 1

        except Exception as e:
            logger.warning(
                f"Failed to remove tool from {agent_dir.name}: {e}",
            )

    if removed_count > 0:
        click.echo(f"✓ Removed tool from {removed_count} agent(s)")
    else:
        click.echo("   No agents had this tool")


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
    if _is_running():
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

    manifest_path = source_path / "plugin.json"
    if not manifest_path.exists():
        click.echo(f"❌ plugin.json not found in {source}", err=True)
        return

    try:
        with open(manifest_path, encoding="utf-8") as f:
            manifest = json.load(f)
    except json.JSONDecodeError as e:
        click.echo(f"❌ Invalid plugin.json: {e}", err=True)
        return
    except Exception as e:
        click.echo(f"❌ Failed to read plugin.json: {e}", err=True)
        return

    plugin_id = manifest.get("id")
    plugin_name = manifest.get("name")

    if not plugin_id or not plugin_name:
        click.echo(
            "❌ plugin.json missing required fields: id, name",
            err=True,
        )
        return

    click.echo(f"Installing plugin: {plugin_name} ({plugin_id})")

    plugin_dir = get_plugins_dir()
    plugin_dir.mkdir(parents=True, exist_ok=True)
    target_dir = plugin_dir / plugin_id

    if target_dir.exists() and not force:
        click.echo(
            f"❌ Plugin '{plugin_id}' already exists. "
            "Use --force to reinstall.",
            err=True,
        )
        return

    click.echo("Validating plugin structure...")
    try:
        backend_entry = manifest.get("entry", {}).get("backend")
        if backend_entry:
            backend_path = source_path / backend_entry
            if not backend_path.exists():
                raise FileNotFoundError(
                    f"Backend entry point not found: {backend_entry}",
                )

            import importlib.util

            spec = importlib.util.spec_from_file_location(
                f"_plugin_validation_{plugin_id}",
                backend_path,
            )
            if spec and spec.loader:
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)

                has_plugin_class = hasattr(module, "Plugin")
                has_plugin_instance = hasattr(module, "plugin")

                if not (has_plugin_class or has_plugin_instance):
                    raise AttributeError(
                        "Plugin module must export a 'Plugin' class "
                        "or 'plugin' instance",
                    )

        click.echo("Plugin validation successful")
    except Exception as e:
        click.echo(f"❌ Plugin validation failed: {e}", err=True)
        return

    if target_dir.exists():
        shutil.rmtree(target_dir)

    click.echo("Copying plugin files...")
    try:
        shutil.copytree(source_path, target_dir)
    except Exception as e:
        click.echo(f"❌ Failed to copy plugin files: {e}", err=True)
        return

    requirements_file = target_dir / "requirements.txt"
    if requirements_file.exists():
        click.echo("Installing dependencies...")
        if not _install_requirements_cli(requirements_file, target_dir):
            return

    click.echo(f"\n✅ Plugin '{plugin_name}' installed successfully!")
    click.echo(f"Location: {target_dir}")

    _sync_tool_plugin_to_agents(manifest)

    if is_url and temp_dir:
        try:
            shutil.rmtree(temp_dir)
        except Exception:
            pass

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
    plugin files are removed from disk.
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
    if _is_running():
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

    if not plugin_dir.exists():
        click.echo(f"❌ Plugin '{plugin_id}' not found", err=True)
        return

    manifest_path = plugin_dir / "plugin.json"
    manifest = None
    if manifest_path.exists():
        try:
            with open(manifest_path, encoding="utf-8") as f:
                manifest = json.load(f)
        except Exception as e:
            logger.warning(f"Failed to read plugin manifest: {e}")

    if not click.confirm(
        f"Uninstall plugin '{plugin_id}'?",
    ):
        click.echo("Cancelled.")
        return

    if manifest:
        _remove_tool_plugin_from_agents(manifest)

    try:
        shutil.rmtree(plugin_dir)
        click.echo(f"✅ Plugin '{plugin_id}' uninstalled successfully")
    except Exception as e:
        click.echo(f"❌ Failed to uninstall plugin: {e}", err=True)


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
            backend_path = plugin_path / backend_entry
            if not backend_path.exists():
                click.echo(
                    f"❌ Backend entry not found: {backend_entry}",
                    err=True,
                )
                return

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
        click.echo(f"❌ Validation error: {e}", err=True)
