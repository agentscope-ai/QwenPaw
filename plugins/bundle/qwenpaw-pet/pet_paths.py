# -*- coding: utf-8 -*-
"""Resolve QwenPaw working dir and list installed pet packages."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


def qwenpaw_working_dir() -> Path:
    """Match ``qwenpaw_pet_desktop.runtime.qwenpaw_working_dir`` precedence."""
    explicit = os.environ.get("QWENPAW_WORKING_DIR") or os.environ.get(
        "COPAW_WORKING_DIR",
    )
    if explicit:
        return Path(explicit).expanduser().resolve()
    try:
        from qwenpaw.constant import WORKING_DIR  # type: ignore

        return Path(WORKING_DIR).expanduser().resolve()
    except Exception:
        legacy = Path("~/.copaw").expanduser()
        if legacy.exists():
            return legacy.resolve()
        return Path("~/.qwenpaw").expanduser().resolve()


def pets_install_dir() -> Path:
    return qwenpaw_working_dir() / "pets"


def list_installed_pets() -> list[dict[str, Any]]:
    """Return one entry per ``<WORKING_DIR>/pets/<x>`` with ``pet.json``."""
    root = pets_install_dir()
    if not root.is_dir():
        return []
    out: list[dict[str, Any]] = []
    for child in sorted(root.iterdir(), key=lambda p: p.name.lower()):
        if not child.is_dir():
            continue
        manifest_path = child / "pet.json"
        if not manifest_path.is_file():
            continue
        try:
            data = json.loads(manifest_path.read_text(encoding="utf-8"))
        except Exception:
            data = {}
        if not isinstance(data, dict):
            data = {}
        raw_id = data.get("id")
        manifest_id = (
            raw_id.strip()
            if isinstance(raw_id, str) and raw_id.strip()
            else None
        )
        folder_name = child.name
        out.append(
            {
                # Directory under pets/ — used by the desktop path.
                "folder": folder_name,
                # pet.json "id" (may differ from folder, e.g.
                # goose-default vs goose).
                "manifestId": manifest_id,
                # Older clients: same as manifestId or folder if missing.
                "id": manifest_id or folder_name,
                "path": str(child.resolve()),
                "displayName": str(
                    data.get("displayName") or data.get("name") or folder_name,
                ),
            },
        )
    return out
