# -*- coding: utf-8 -*-
"""Resolve QwenPaw-Data package assets without machine coupling."""

from __future__ import annotations

import importlib
import json
import os
import stat
import sys
from importlib.metadata import PackageNotFoundError, distribution
from pathlib import Path


PLUGIN_DIR = Path(__file__).resolve().parent.parent
DEV_DIR = PLUGIN_DIR / ".qwenpaw-data-dev"


def runtime_packages_available() -> bool:
    """Return True when the current interpreter can run both sidecars."""
    for module in (
        "context_manager.api.server",
        "qwenpaw_data.host.core.api.app",
    ):
        try:
            importlib.import_module(module)
        except ImportError:
            return False
    return True


def _runtime_packages_available() -> bool:
    """Return True when the current interpreter can run the context sidecar."""
    return runtime_packages_available()


def context_python() -> Path:
    """Return the Python executable that should run the context sidecar.

    Resolution order:
    1. ``QWENPAW_DATA_CONTEXT_PYTHON`` environment variable.
    2. The plugin-local ``.venv-qwenpaw-data`` virtual environment
       (development).
    3. The current interpreter, if it already has the qwenpaw-data runtime
       packages installed from PyPI.
    4. Fall back to the expected ``.venv-qwenpaw-data`` path so that a missing
       runtime produces a clear "file not found" error downstream.
    """
    configured = os.getenv("QWENPAW_DATA_CONTEXT_PYTHON", "").strip()
    if configured:
        # Do not resolve a venv launcher symlink to the underlying base Python;
        # doing so drops the venv's site-packages at process startup.
        return Path(configured).expanduser().absolute()
    candidates = (
        PLUGIN_DIR / ".venv-qwenpaw-data" / "bin" / "python",
        PLUGIN_DIR / ".venv-qwenpaw-data" / "Scripts" / "python.exe",
    )
    for candidate in candidates:
        if candidate.is_file():
            return candidate.absolute()
    if _runtime_packages_available():
        return Path(sys.executable).absolute()
    return candidates[0]


def context_working_dir() -> Path | None:
    """Return the context service working directory, if one is configured.

    The context service locates its persistent data through
    ``QWENPAW_DATA_HOME``
    rather than ``cwd``, so a plain PyPI install does not need a source
    checkout. This function only returns a directory when the operator or
    development setup explicitly provides one.
    """
    configured = os.getenv("QWENPAW_DATA_CONTEXT_CWD", "").strip()
    if configured:
        return Path(configured).expanduser().resolve()
    source = DEV_DIR / "source"
    return source.resolve() if source.exists() else None


def _installed_skills_root() -> Path | None:
    """Return the skills directory shipped inside qwenpaw-data-skills."""
    try:
        package = distribution("qwenpaw-data-skills")
    except PackageNotFoundError:
        return None
    installed = Path(package.locate_file("qwenpaw_data_skills/skills"))
    return installed.resolve() if installed.is_dir() else None


def skills_root() -> Path | None:
    """Return the root directory that contains skill layers.

    Resolution order:
    1. ``QWENPAW_DATA_SKILLS_DIR`` environment variable.
    2. The skills directory shipped with the ``qwenpaw-data-skills`` PyPI
       package.
    3. The plugin-local ``.qwenpaw-data-dev/skills`` symlink (development).
    """
    configured = os.getenv("QWENPAW_DATA_SKILLS_DIR", "").strip()
    if configured:
        path = Path(configured).expanduser().resolve()
        return path if path.is_dir() else None
    installed = _installed_skills_root()
    if installed is not None:
        return installed
    development = DEV_DIR / "skills"
    return development.resolve() if development.is_dir() else None


def skill_layers(root: Path) -> list[Path]:
    """Return category directories containing immediate skill children."""
    layers: list[Path] = []
    for candidate in sorted(root.iterdir()):
        if not candidate.is_dir():
            continue
        if any(
            (child / "SKILL.md").is_file() for child in candidate.iterdir()
        ):
            layers.append(candidate)
    return layers


DATABRIDGE_MCP_NAME = "databridge"


def provision_engine_mcp(
    engine_home: Path,
    cm_url: str,
    cm_token: str,
) -> Path | None:
    """Upsert the DataBridge MCP entry in the engine workspace ``.mcp``.

    The engine only exposes CM tools to the sandboxed agent through the
    AgentScope ``.mcp`` file; the CLI provisions it via ``qwenpaw-data mcp
    import`` but a managed engine has no such step, leaving agents without
    any datasource. The entry is rewritten on every start because a managed
    context sidecar may come up on a different port, while entries under
    other names are preserved as user configuration.
    """
    if not cm_url:
        return None
    workspace = engine_home / "host" / "workspace"
    workspace.mkdir(parents=True, exist_ok=True)
    mcp_path = workspace / ".mcp"

    flags = os.O_RDWR | os.O_CREAT
    flags |= getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(mcp_path, flags, 0o600)
    with os.fdopen(fd, "r+", encoding="utf-8") as mcp_file:
        if not stat.S_ISREG(os.fstat(mcp_file.fileno()).st_mode):
            raise OSError(f"MCP target is not a regular file: {mcp_path}")
        os.fchmod(mcp_file.fileno(), 0o600)

        entries: list[dict] = []
        try:
            existing = json.load(mcp_file)
        except (OSError, ValueError):
            existing = []
        if isinstance(existing, list):
            entries = [
                item
                for item in existing
                if isinstance(item, dict)
                and item.get("name") != DATABRIDGE_MCP_NAME
            ]

        headers: dict[str, str] = {}
        if cm_token:
            headers["Authorization"] = f"Bearer {cm_token}"
        entries.insert(
            0,
            {
                "name": DATABRIDGE_MCP_NAME,
                "is_stateful": False,
                "mcp_config": {
                    "type": "http_mcp",
                    "url": f"{cm_url.rstrip('/')}/mcp/v1/cm",
                    "headers": headers,
                    "timeout": 2400.0,
                },
                "enable_tools": None,
                "disable_tools": None,
                "execution_timeout": 2400.0,
            },
        )
        mcp_file.seek(0)
        json.dump(entries, mcp_file, indent=2)
        mcp_file.truncate()
    return mcp_path
