# -*- coding: utf-8 -*-
"""Lightweight module for reading/writing last API config.

This module is separated from config.utils to avoid importing heavy
dependencies (providers, local_models, etc.) during CLI startup.

IMPORTANT: This module must NOT import any copaw modules to keep it fast.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Optional, Tuple


def get_config_path() -> Path:
    """Get the path to the config file."""
    working_dir = (
        Path(
            os.environ.get("COPAW_WORKING_DIR", "~/.copaw"),
        )
        .expanduser()
        .resolve()
    )
    return working_dir / "config.json"


def read_last_api() -> Optional[Tuple[str, int]]:
    """Read last API host/port from config (lightweight version).

    Returns:
        Tuple of (host, port) if found, None otherwise
    """
    config_path = get_config_path()
    if not config_path.is_file():
        return None

    try:
        with open(config_path, "r", encoding="utf-8") as file:
            data = json.load(file)
    except (json.JSONDecodeError, UnicodeDecodeError, OSError):
        return None

    # Read last_api from config
    last_api = data.get("last_api", {})
    host = last_api.get("host")
    port = last_api.get("port")

    if not host or port is None:
        return None

    return host, port


def write_last_api(host: str, port: int) -> None:
    """Write last API host/port to config (lightweight version).

    Args:
        host: API host
        port: API port
    """
    config_path = get_config_path()

    # Load existing config or create empty dict
    if config_path.is_file():
        try:
            with open(config_path, "r", encoding="utf-8") as file:
                data = json.load(file)
        except (json.JSONDecodeError, UnicodeDecodeError, OSError):
            data = {}
    else:
        data = {}

    # Update last_api section
    data["last_api"] = {"host": host, "port": port}

    # Write back
    config_path.parent.mkdir(parents=True, exist_ok=True)
    with open(config_path, "w", encoding="utf-8") as file:
        json.dump(data, file, indent=2, ensure_ascii=False)
