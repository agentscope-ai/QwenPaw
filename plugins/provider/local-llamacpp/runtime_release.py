# -*- coding: utf-8 -*-
"""Versioned llama.cpp bundles shared by chat and Piccolo models."""

import json
from pathlib import Path
from typing import Any

RELEASE = json.loads(
    Path(__file__)
    .with_name("runtime-release.json")
    .read_text(encoding="utf-8"),
)
RUNTIME_METADATA = "qwenpaw-runtime.json"


def read_runtime_metadata(directory: Path) -> dict[str, Any]:
    """Read the installed bundle identity; legacy bundles have no marker."""
    try:
        data = json.loads(
            (directory / RUNTIME_METADATA).read_text(encoding="utf-8"),
        )
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def matches_release(metadata: dict[str, Any]) -> bool:
    return all(
        metadata.get(key) == RELEASE[key]
        for key in ("release", "upstream_commit", "patch_sha256")
    ) and set(metadata.get("capabilities", [])) >= {"chat", "piccolo"}


def validate_runtime_bundle(directory: Path, target: str) -> None:
    """Check the complete staged bundle before replacing an installation."""
    metadata = read_runtime_metadata(directory)
    if not matches_release(metadata) or metadata.get("target") != target:
        raise ValueError("The downloaded runtime does not match this release.")
    executable = (
        "llama-server.exe" if target.startswith("win-") else "llama-server"
    )
    if not (directory / executable).is_file():
        raise ValueError("The runtime bundle is missing llama-server.")
