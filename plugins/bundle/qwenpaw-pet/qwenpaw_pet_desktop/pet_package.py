# -*- coding: utf-8 -*-
"""Load and install Codex-compatible pet packages."""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

from PIL import Image

from . import runtime
from .sprites import ATLAS_HEIGHT, ATLAS_WIDTH

SNOWPAW_PET_ID = "snowpaw"


def validate_pet_package(pet_dir: Path) -> tuple[dict[str, Any], Path]:
    manifest_path = pet_dir / "pet.json"
    if not manifest_path.is_file():
        raise ValueError(f"missing pet.json: {manifest_path}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    spritesheet_rel = manifest.get("spritesheetPath")
    if not isinstance(spritesheet_rel, str) or not spritesheet_rel:
        raise ValueError("pet.json must contain spritesheetPath")
    spritesheet_path = pet_dir / spritesheet_rel
    if not spritesheet_path.is_file():
        raise ValueError(f"missing spritesheet: {spritesheet_path}")
    with Image.open(spritesheet_path) as image:
        if image.size != (ATLAS_WIDTH, ATLAS_HEIGHT):
            raise ValueError(
                "spritesheet must be "
                f"{ATLAS_WIDTH}x{ATLAS_HEIGHT}; got {image.size}",
            )
    pet_id = manifest.get("id") or pet_dir.name
    if not isinstance(pet_id, str) or not pet_id.strip():
        raise ValueError("pet.json must contain a non-empty id")
    return manifest, spritesheet_path


def install_pet(source_dir: Path, *, replace: bool = True) -> Path:
    manifest, _sheet = validate_pet_package(source_dir)
    pet_id = manifest.get("id") or source_dir.name
    target = runtime.pets_dir() / str(pet_id)
    runtime.ensure_runtime()
    if target.exists() and not replace:
        raise FileExistsError(f"pet already exists: {target}")
    target.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source_dir / "pet.json", target / "pet.json")
    spritesheet_name = manifest["spritesheetPath"]
    shutil.copy2(source_dir / spritesheet_name, target / spritesheet_name)
    return target


def bundled_default_pet_dir() -> Path:
    # The plugin lives on disk (loaded via sys.path injection by
    # plugin.py), so importlib.resources is overkill — resolving
    # relative to ``__file__`` is mypy-clean and works the same way.
    return (
        Path(__file__).resolve().parent / "assets" / "default-pet" / "snowpaw"
    )


def install_default_pet() -> Path:
    """Install the bundled snowpaw pet into ``<WORKING_DIR>/pets/snowpaw/``."""
    return install_pet(bundled_default_pet_dir(), replace=True)


def resolve_pet_dir(pet_dir: str | None = None) -> Path:
    if pet_dir:
        path = Path(pet_dir).expanduser().resolve()
        validate_pet_package(path)
        return path
    runtime.ensure_runtime()
    installed = sorted(
        p for p in runtime.pets_dir().iterdir() if (p / "pet.json").is_file()
    )
    if not installed:
        return install_default_pet()
    first = installed[0]
    try:
        validate_pet_package(first)
        return first
    except ValueError:
        # Self-heal: an earlier run may have left snowpaw with a broken
        # or partial install. Wipe the folder and reinstall from the
        # bundled default. User-managed pets are left untouched.
        if first.name == SNOWPAW_PET_ID:
            shutil.rmtree(first, ignore_errors=True)
            return install_default_pet()
        raise


def resolve_switch_pet_path(
    *,
    pet_dir: str | None = None,
    pet_id: str | None = None,
) -> Path:
    """Resolve a pet folder for hot-switch.

    Exactly one of *pet_dir* or *pet_id* must be supplied. *pet_id* may
    be either the directory name under ``pets/`` (e.g. ``goose``) or
    the manifest ``id`` from ``pet.json`` (e.g. ``goose-default``)
    when those differ.
    """
    dir_s = (pet_dir or "").strip()
    id_s = (pet_id or "").strip()
    if bool(dir_s) == bool(id_s):
        raise ValueError("provide exactly one of pet_dir or pet_id")
    runtime.ensure_runtime()
    if dir_s:
        path = Path(dir_s).expanduser().resolve()
        validate_pet_package(path)
        return path
    if any(c in id_s for c in "/\\"):
        raise ValueError(
            "pet_id must be a plain name (folder under pets/), not a path",
        )
    pets_root = runtime.pets_dir().resolve()

    def _under_pets(p: Path) -> Path:
        resolved = p.resolve()
        try:
            resolved.relative_to(pets_root)
        except ValueError as exc:
            raise ValueError(
                "pet_id resolves outside the pets directory",
            ) from exc
        return resolved

    direct = _under_pets(pets_root / id_s)
    if direct.is_dir():
        try:
            validate_pet_package(direct)
            return direct
        except ValueError:
            pass

    for child in sorted(pets_root.iterdir(), key=lambda p: p.name.lower()):
        if not child.is_dir():
            continue
        manifest_path = child / "pet.json"
        if not manifest_path.is_file():
            continue
        try:
            raw = json.loads(manifest_path.read_text(encoding="utf-8"))
        except Exception:
            continue
        mid = raw.get("id")
        if isinstance(mid, str) and mid.strip() == id_s:
            try:
                validate_pet_package(child)
                return child.resolve()
            except ValueError:
                continue

    raise ValueError(
        f"no pet folder or pet.json id matching {id_s!r} under {pets_root}",
    )
