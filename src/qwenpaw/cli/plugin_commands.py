# -*- coding: utf-8 -*-
# pylint:disable=too-many-return-statements,too-many-branches
# pylint:disable=too-many-statements
"""Plugin management CLI commands."""

import json
import logging
import shutil
import subprocess
import sys
import tempfile
import urllib.request
import zipfile
from pathlib import Path

import click

logger = logging.getLogger(__name__)


def _check_qwenpaw_not_running():
    """Check if QwenPaw is not running, exit if it is."""
    from ..config.utils import is_qwenpaw_running

    if is_qwenpaw_running():
        click.echo(
            "❌ QwenPaw is currently running. Please stop it first:",
            err=True,
        )
        click.echo("   qwenpaw shutdown", err=True)
        click.echo(
            "\n💡 Plugin operations are only allowed when QwenPaw is stopped.",
        )
        raise click.Abort()


def _safe_extract_zip(zip_ref: zipfile.ZipFile, extract_path: Path):
    """Safely extract zip file, preventing Zip Slip attacks.

    Args:
        zip_ref: ZipFile object
        extract_path: Target extraction directory

    Raises:
        ValueError: If any zip member attempts path traversal
    """
    for member in zip_ref.namelist():
        # Resolve the full path and ensure it's within extract_path
        member_path = (extract_path / member).resolve()
        if not str(member_path).startswith(str(extract_path.resolve())):
            raise ValueError(
                f"Zip Slip detected: {member} attempts to extract "
                f"outside target directory",
            )

    # Safe to extract
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

    from ..config.utils import get_agent_dirs

    agent_dirs = get_agent_dirs()
    if not agent_dirs:
        click.echo("   No agents found, skipping sync")
        return

    synced_count = 0
    for agent_dir in agent_dirs:
        agent_json_path = agent_dir / "agent.json"
        if not agent_json_path.exists():
            continue

        try:
            # Read agent config
            with open(agent_json_path, encoding="utf-8") as f:
                config = json.load(f)

            # Check if tool already exists
            builtin_tools = config.get("tools", {}).get("builtin_tools", {})

            if tool_name in builtin_tools:
                continue

            # Add tool with default disabled state
            if "tools" not in config:
                config["tools"] = {}
            if "builtin_tools" not in config["tools"]:
                config["tools"]["builtin_tools"] = {}

            config["tools"]["builtin_tools"][tool_name] = {
                "name": tool_name,
                "enabled": False,
                "config": {},
            }

            # Save updated config
            with open(agent_json_path, "w", encoding="utf-8") as f:
                json.dump(config, f, indent=2, ensure_ascii=False)

            synced_count += 1

        except Exception as e:
            logger.warning(
                f"Failed to sync tool to {agent_dir.name}: {e}",
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

    removed_count = 0
    for agent_dir in agent_dirs:
        agent_json_path = agent_dir / "agent.json"
        if not agent_json_path.exists():
            continue

        try:
            # Read agent config
            with open(agent_json_path, encoding="utf-8") as f:
                config = json.load(f)

            # Check if tool exists
            builtin_tools = config.get("tools", {}).get("builtin_tools", {})

            if tool_name not in builtin_tools:
                continue

            # Remove tool
            del config["tools"]["builtin_tools"][tool_name]

            # Save updated config
            with open(agent_json_path, "w", encoding="utf-8") as f:
                json.dump(config, f, indent=2, ensure_ascii=False)

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

    Examples:
        qwenpaw plugin install examples/plugins/idealab-provider
        qwenpaw plugin install /path/to/plugin
        qwenpaw plugin install https://example.com/plugin.zip
    """
    from ..config.utils import get_plugins_dir

    # Check if QwenPaw is running
    _check_qwenpaw_not_running()

    # Check if source is a URL
    is_url = source.startswith(("http://", "https://"))
    temp_dir = None

    if is_url:
        try:
            source_path, temp_dir = _download_plugin_from_url(source)
        except Exception as e:
            click.echo(f"❌ Failed to download plugin: {e}", err=True)
            return
    else:
        # Local path
        source_path = Path(source).resolve()
        if not source_path.exists():
            click.echo(f"❌ Path not found: {source}", err=True)
            return

    # Check for plugin.json
    manifest_path = source_path / "plugin.json"
    if not manifest_path.exists():
        click.echo(f"❌ plugin.json not found in {source}", err=True)
        return

    # Read plugin info
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
        click.echo("❌ plugin.json missing required fields: id, name", err=True)
        return

    click.echo(f"📦 Installing plugin: {plugin_name} ({plugin_id})")

    # Target directory
    plugin_dir = get_plugins_dir()
    plugin_dir.mkdir(parents=True, exist_ok=True)
    target_dir = plugin_dir / plugin_id

    # Check if already exists
    if target_dir.exists() and not force:
        click.echo(
            f"❌ Plugin '{plugin_id}' already exists. "
            "Use --force to reinstall.",
            err=True,
        )
        return

    # Remove old version
    if target_dir.exists():
        click.echo("🗑️  Removing old version...")
        shutil.rmtree(target_dir)

    # Copy plugin files
    click.echo("📁 Copying plugin files...")
    try:
        shutil.copytree(source_path, target_dir)
    except Exception as e:
        click.echo(f"❌ Failed to copy plugin files: {e}", err=True)
        return

    # Install dependencies
    requirements_file = target_dir / "requirements.txt"
    if requirements_file.exists():
        click.echo("📦 Installing dependencies...")
        try:
            # Use sys.executable to ensure we use the correct Python
            # environment
            # This works across different platforms (Windows, Linux, macOS)
            _ = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "pip",
                    "install",
                    "-r",
                    str(requirements_file),
                ],
                check=True,
                capture_output=True,
                text=True,
            )
            click.echo("✓ Dependencies installed")
        except subprocess.CalledProcessError as e:
            click.echo("❌ Failed to install dependencies:", err=True)
            click.echo(f"  {e.stderr}", err=True)
            # Clean up the failed installation
            if target_dir.exists():
                shutil.rmtree(target_dir)
            return
        except FileNotFoundError:
            click.echo(
                "⚠️  pip not found. Please install dependencies manually:",
                err=True,
            )
            click.echo(f"   pip install -r {requirements_file}")
            # Clean up the failed installation
            if target_dir.exists():
                shutil.rmtree(target_dir)
            return

    click.echo(f"\n✅ Plugin '{plugin_name}' installed successfully!")
    click.echo(f"📍 Location: {target_dir}")

    # Sync tool plugins to all agents
    _sync_tool_plugin_to_agents(manifest)

    # Clean up temporary directory if source was downloaded
    if is_url and temp_dir:
        try:
            shutil.rmtree(temp_dir)
        except Exception:
            pass  # Ignore cleanup errors

    click.echo("\n💡 Next steps:")
    click.echo("   1. Restart QwenPaw to load the plugin")
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


@plugin.command()
@click.argument("plugin_id")
def uninstall(plugin_id: str):
    """Uninstall a plugin."""
    from ..config.utils import get_plugins_dir

    # Check if QwenPaw is running
    _check_qwenpaw_not_running()

    plugin_dir = get_plugins_dir() / plugin_id

    if not plugin_dir.exists():
        click.echo(f"❌ Plugin '{plugin_id}' not found", err=True)
        return

    # Read manifest before deletion for tool cleanup
    manifest_path = plugin_dir / "plugin.json"
    manifest = None
    if manifest_path.exists():
        try:
            with open(manifest_path, encoding="utf-8") as f:
                manifest = json.load(f)
        except Exception as e:
            logger.warning(f"Failed to read plugin manifest: {e}")

    # Confirm
    if not click.confirm(
        f"Are you sure you want to uninstall '{plugin_id}'?",
    ):
        click.echo("Cancelled.")
        return

    # Remove tool from all agents if this is a tool plugin
    if manifest:
        _remove_tool_plugin_from_agents(manifest)

    # Delete directory
    try:
        shutil.rmtree(plugin_dir)

        click.echo(f"✅ Plugin '{plugin_id}' uninstalled successfully")
        click.echo("💡 Restart QwenPaw to apply changes")
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
