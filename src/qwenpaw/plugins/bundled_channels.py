# -*- coding: utf-8 -*-
"""One-time, offline migration of formerly built-in channel implementations.

Never touch agent.json, credentials or channel state. The marker survives
uninstall so an explicit removal does not resurrect a plugin on next boot.
"""

from __future__ import annotations

import json
import shutil
import tempfile
from pathlib import Path

from .install_lock import plugin_install_lock


def bundled_channel_root() -> Path:
    return Path(__file__).resolve().parents[1] / "bundled_plugins" / "channel"


def ensure_bundled_channel_plugins(plugins_dir: Path) -> None:
    """Seed once and atomically; preserve installed versions."""
    plugins_dir.mkdir(parents=True, exist_ok=True)
    migrations = plugins_dir / ".channel-migrations"
    migrations.mkdir(exist_ok=True)
    with plugin_install_lock(
        migrations / "migration.lock",
        timeout=30,
    ) as locked:
        if not locked:
            raise RuntimeError("Channel migration is busy; retry startup")
        for source in sorted(bundled_channel_root().iterdir()):
            manifest_path = source / "plugin.json"
            if not source.is_dir() or not manifest_path.is_file():
                continue
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            plugin_id = manifest["id"]
            marker = migrations / f"{plugin_id}-v1.json"
            if marker.exists():
                continue
            # Respect manually installed or deliberately disabled copies,
            # including a directory whose name differs from the plugin ID.
            installed = False
            for candidate in plugins_dir.iterdir():
                existing = candidate / "plugin.json"
                if existing.is_file():
                    try:
                        existing_manifest = json.loads(
                            existing.read_text(encoding="utf-8"),
                        )
                        installed |= (
                            isinstance(existing_manifest, dict)
                            and existing_manifest.get("id") == plugin_id
                        )
                    except (OSError, ValueError):
                        continue
            target = plugins_dir / plugin_id
            if not installed:
                if target.exists():
                    raise RuntimeError(
                        f"Cannot migrate channel: {target} already exists "
                        "without a valid manifest",
                    )
                with tempfile.TemporaryDirectory(
                    prefix=".channel-stage-",
                    dir=plugins_dir,
                ) as temp:
                    staged = Path(temp) / plugin_id
                    shutil.copytree(
                        source,
                        staged,
                        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
                    )
                    staged.rename(target)
            temporary_marker = marker.with_suffix(".tmp")
            temporary_marker.write_text(
                json.dumps(
                    {"plugin_id": plugin_id, "version": manifest["version"]},
                )
                + "\n",
                encoding="utf-8",
            )
            temporary_marker.replace(marker)
