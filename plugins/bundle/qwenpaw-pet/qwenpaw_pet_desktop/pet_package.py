# -*- coding: utf-8 -*-
"""Load and install Codex-compatible pet packages."""

from __future__ import annotations

import json
import os
import shutil
import tempfile
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from PIL import Image

from . import runtime
from .sprites import ATLAS_HEIGHT, ATLAS_WIDTH


# The snowpaw default-pet spritesheet (1.6 MB webp) is fetched lazily so
# it does not have to ship inside the plugin package itself. On first
# use it is downloaded into ``runtime.home_dir() / "cache"`` and re-used
# across runs. Set ``QWENPAW_PET_SNOWPAW_URL`` to point at a mirror.
SNOWPAW_PET_ID = "snowpaw"
SNOWPAW_SPRITESHEET_URL = os.environ.get(
    "QWENPAW_PET_SNOWPAW_URL",
    (
        "https://img.alicdn.com/imgextra/i1/"
        "O1CN01cCPEw11K5LZ95E2Ex_!!6000000001112-49-tps-1536-1872.webp"
    ),
)
_DOWNLOAD_TIMEOUT_S = 60.0
# Alicdn (and other CDN edges) reject the default ``Python-urllib/*``
# User-Agent with HTTP 420, so we send a generic browser-style UA and
# leave a small identifier in parentheses so CDN operators can still
# attribute the traffic if they ever care to.
_DOWNLOAD_UA = (
    "Mozilla/5.0 (compatible; qwenpaw-pet/desktop; +https://qwenpaw.dev)"
)


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


def _snowpaw_cache_path() -> Path:
    """Where the on-demand snowpaw spritesheet download lives."""
    return runtime.home_dir() / "cache" / "snowpaw-spritesheet.webp"


def _is_valid_atlas(path: Path) -> bool:
    """Return True iff *path* is a non-empty image with the expected size."""
    try:
        if not path.is_file() or path.stat().st_size <= 0:
            return False
        with Image.open(path) as image:
            return image.size == (ATLAS_WIDTH, ATLAS_HEIGHT)
    except (OSError, ValueError):
        return False


def _atomic_download(
    url: str,
    dest: Path,
    *,
    timeout: float = _DOWNLOAD_TIMEOUT_S,
) -> None:
    """Stream *url* into *dest* via a sibling tempfile + atomic rename.

    Network errors are re-raised as ``RuntimeError`` with the URL in the
    message. The tempfile is removed on any failure so the cache dir
    never accumulates ``.part`` leftovers.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp_fd, tmp_name = tempfile.mkstemp(
        prefix=dest.name + ".",
        suffix=".part",
        dir=str(dest.parent),
    )
    tmp_path = Path(tmp_name)
    req = urllib.request.Request(
        url,
        headers={"User-Agent": _DOWNLOAD_UA, "Accept": "*/*"},
    )
    try:
        with os.fdopen(tmp_fd, "wb") as out:
            try:
                with urllib.request.urlopen(req, timeout=timeout) as resp:
                    shutil.copyfileobj(resp, out, length=64 * 1024)
            except (urllib.error.URLError, TimeoutError, OSError) as exc:
                raise RuntimeError(
                    f"failed to download {url}: {exc}",
                ) from exc
        os.replace(tmp_path, dest)
    finally:
        if tmp_path.exists():
            try:
                tmp_path.unlink()
            except OSError:
                pass


def _ensure_snowpaw_spritesheet() -> Path:
    """Resolve a local path to snowpaw's spritesheet, fetching once if needed.

    Resolution order:

    1. ``assets/default-pet/snowpaw/spritesheet.webp`` inside the plugin
       package — present in offline / dev installs that choose to ship
       the asset directly.
    2. cached download under ``runtime.home_dir() / "cache"`` — re-used
       across runs and process restarts.
    3. fresh ``GET`` from ``SNOWPAW_SPRITESHEET_URL`` into the cache.

    A bad cached file (e.g. a redirect-HTML page saved as ``.webp``) is
    detected via :func:`_is_valid_atlas` and re-downloaded on the next
    call rather than silently re-used.
    """
    bundle = bundled_default_pet_dir() / "spritesheet.webp"
    if _is_valid_atlas(bundle):
        return bundle
    cache = _snowpaw_cache_path()
    if _is_valid_atlas(cache):
        return cache
    _atomic_download(SNOWPAW_SPRITESHEET_URL, cache)
    if not _is_valid_atlas(cache):
        try:
            cache.unlink()
        except OSError:
            pass
        raise RuntimeError(
            "downloaded snowpaw spritesheet at "
            f"{SNOWPAW_SPRITESHEET_URL} is not a "
            f"{ATLAS_WIDTH}x{ATLAS_HEIGHT} image",
        )
    return cache


def install_default_pet() -> Path:
    """Install the snowpaw default pet into ``<WORKING_DIR>/pets/snowpaw/``.

    The atlas image is fetched from ``SNOWPAW_SPRITESHEET_URL`` (and
    cached under ``runtime.home_dir() / "cache"``) when it is not
    already available locally, then copied alongside ``pet.json`` into
    the user's pets directory.

    Ordering matters: we resolve the spritesheet (which may raise on a
    failed download) **before** touching the target directory, so a
    transient CDN error never leaves a half-written pet folder behind
    that would later fool :func:`resolve_pet_dir` into skipping the
    install.
    """
    source = bundled_default_pet_dir()
    manifest_path = source / "pet.json"
    if not manifest_path.is_file():
        raise ValueError(
            f"bundled default pet manifest missing: {manifest_path}",
        )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    pet_id = str(manifest.get("id") or source.name)
    sprite_name = manifest.get("spritesheetPath")
    if not isinstance(sprite_name, str) or not sprite_name:
        raise ValueError("default pet.json must contain spritesheetPath")

    sprite_src = _ensure_snowpaw_spritesheet()

    runtime.ensure_runtime()
    target = runtime.pets_dir() / pet_id
    target.mkdir(parents=True, exist_ok=True)
    shutil.copy2(manifest_path, target / "pet.json")
    shutil.copy2(sprite_src, target / sprite_name)

    validate_pet_package(target)
    return target


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
        # Self-heal: an earlier run may have left snowpaw with a
        # manifest but no spritesheet (e.g. a CDN download failed
        # mid-install). Wipe the broken folder and re-run the default
        # install so the network/cache fallback chain gets another
        # chance. User-managed pets are left untouched.
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
