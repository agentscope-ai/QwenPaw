# -*- coding: utf-8 -*-
"""Portable manifest serialization shared by workflow helpers."""

import ast
import hashlib
import json
from pathlib import Path, PurePosixPath

import yaml


def load(path: Path) -> dict:
    """Read YAML or JSON configuration without interpolation."""
    return yaml.safe_load(path.read_text(encoding=f"utf-8"))


def digest(data: dict) -> str:
    """Use a stable digest on Linux, Windows, and macOS."""
    value = json.dumps(data, sort_keys=True, separators=(f",", f":"))
    return hashlib.sha256(value.encode()).hexdigest()


def save(path: Path, data: dict) -> None:
    """Atomically persist a JSON artifact."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(f".tmp")
    temporary.write_text(json.dumps(data, indent=2) + f"\n", encoding=f"utf-8")
    temporary.replace(path)


def tree_hash(root: Path) -> str:
    """Hash every task file, including grader and environment definition."""
    files = {}
    for item in sorted(root.rglob(f"*")):
        if item.is_symlink():
            raise ValueError(f"Task symlinks are not supported: {item}")
        if item.is_file():
            files[item.relative_to(root).as_posix()] = hashlib.sha256(
                item.read_bytes(),
            ).hexdigest()
    return digest(files)


def resolve(root: Path, relative: str) -> Path:
    """Reject escaping or nonportable paths from downloaded manifests."""
    path = PurePosixPath(relative)
    if path.is_absolute() or f".." in path.parts or f"\\" in relative:
        raise ValueError(f"Invalid relative task path")
    result = (root / Path(*path.parts)).resolve()
    if not result.is_relative_to(root.resolve()):
        raise ValueError(f"Task path escapes dataset root")
    return result


def manifest(path: Path) -> dict:
    """Verify manifest integrity before using any run configuration."""
    data = load(path)
    expected = data[f"sha256"]
    payload = {k: v for k, v in data.items() if k != f"sha256"}
    if digest(payload) != expected:
        raise ValueError(f"Manifest checksum mismatch")
    return data


def source_version() -> str:
    """Read the checked-out SDK version without importing the product."""
    path = Path(f"src/qwenpaw/__version__.py")
    module = ast.parse(path.read_text(encoding=f"utf-8"))
    for node in module.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == f"__version__"
            for target in node.targets
        ):
            value = ast.literal_eval(node.value)
            if isinstance(value, str):
                return value
    raise ValueError(f"Missing source SDK version")
