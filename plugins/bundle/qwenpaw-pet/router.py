# -*- coding: utf-8 -*-
"""QwenPaw plugin HTTP routes."""

from __future__ import annotations

import json
import mimetypes
import re
import shutil
import tempfile
import zipfile
from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, model_validator

from emitter import (
    desktop_status_summary,
    emit_pet_event,
    start_desktop_interactive,
    switch_pet_desktop,
)
from pet_paths import list_installed_pets, pets_install_dir


class SwitchPetRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    pet_dir: str | None = None
    pet_id: str | None = None

    @model_validator(mode="after")
    def _one_target(self) -> SwitchPetRequest:
        d = (self.pet_dir or "").strip()
        i = (self.pet_id or "").strip()
        if bool(d) == bool(i):
            raise ValueError("provide exactly one of pet_dir or pet_id")
        return self


class EmitPayload(BaseModel):
    event: str
    text: str | None = None
    state: str | None = None
    duration_ms: int | None = None


class ImportPetRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # Absolute path to either:
    #   * a folder containing ``pet.json`` + ``spritesheet.webp``, or
    #   * a ``.zip`` whose top level (or single nested folder) contains
    #     ``pet.json`` + ``spritesheet.webp``.
    path: str
    # Overwrite an already-installed pet with the same id.
    replace: bool = True


_SAFE_PET_FOLDER = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._-]{0,127}$")
# Used to validate the pet id we derive from pet.json / the source folder
# before it becomes a directory under ``<WORKING_DIR>/pets/`` — keeps an
# untrusted manifest from creating ``../etc/foo`` etc.
_SAFE_PET_ID = _SAFE_PET_FOLDER


def _safe_extract_zip(zip_path: Path, dest: Path) -> None:
    """Extract *zip_path* into *dest*, rejecting any entry that escapes it.

    Guards against zip-slip: every member's resolved path must stay
    under ``dest``. Windows-style backslashes are normalised before the
    check so cross-platform archives behave the same way.
    """
    dest_resolved = dest.resolve()
    with zipfile.ZipFile(zip_path) as zf:
        for info in zf.infolist():
            name = info.filename.replace("\\", "/")
            parts = Path(name).parts
            if name.startswith("/") or ".." in parts:
                raise HTTPException(
                    status_code=400,
                    detail=f"unsafe zip entry: {info.filename}",
                )
            target = (dest_resolved / name).resolve()
            try:
                target.relative_to(dest_resolved)
            except ValueError as exc:
                raise HTTPException(
                    status_code=400,
                    detail=f"zip entry escapes target: {info.filename}",
                ) from exc
        zf.extractall(dest_resolved)


def _resolve_pet_source(extracted: Path) -> Path:
    """Locate the pet package root inside an unpacked directory.

    Supports two layouts so both ``zip -r foo.zip pet-dir/`` and Finder's
    "Compress" produce a usable archive:

    1. ``<extracted>/pet.json``                — flat archive
    2. ``<extracted>/<single subdir>/pet.json`` — nested in one folder
    """
    if (extracted / "pet.json").is_file():
        return extracted
    children = [p for p in extracted.iterdir() if p.is_dir()]
    if len(children) == 1 and (children[0] / "pet.json").is_file():
        return children[0]
    raise HTTPException(
        status_code=400,
        detail="pet package must contain pet.json at its root",
    )


def _install_from_source(source: Path, *, replace: bool) -> dict[str, object]:
    """Validate ``source`` as a pet package and install it.

    Common tail shared by every import path (JSON ``path`` body and
    multipart upload). Returns the JSON response payload; raises
    ``HTTPException`` for any user-visible failure.
    """
    # Lazy import: pulls Pillow + the desktop runtime package only for
    # callers that actually import a pet.
    from qwenpaw_pet_desktop import pet_package

    try:
        manifest, _sheet = pet_package.validate_pet_package(source)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    pet_id = str(manifest.get("id") or source.name)
    if not _SAFE_PET_ID.fullmatch(pet_id):
        raise HTTPException(
            status_code=400,
            detail=(
                f"pet id {pet_id!r} is not a safe folder name "
                "(letters, digits, '.', '_', '-' only)"
            ),
        )

    try:
        target = pet_package.install_pet(source, replace=replace)
    except FileExistsError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    return {
        "ok": True,
        "petId": pet_id,
        "path": str(target),
        "displayName": str(
            manifest.get("displayName") or manifest.get("name") or pet_id,
        ),
    }


def _safe_join(root: Path, relative: str) -> Path:
    """Resolve ``relative`` under ``root`` rejecting any escape attempt.

    Normalises ``\\`` to ``/`` so cross-platform multipart uploads (the
    browser sends ``webkitRelativePath`` with forward slashes; Windows
    archivers occasionally use backslashes) all land in the same tree.
    """
    name = relative.replace("\\", "/").strip()
    if not name:
        raise HTTPException(status_code=400, detail="upload entry has no name")
    parts = Path(name).parts
    if name.startswith("/") or ".." in parts:
        raise HTTPException(
            status_code=400,
            detail=f"unsafe upload entry: {relative}",
        )
    root_r = root.resolve()
    dest = (root_r / name).resolve()
    try:
        dest.relative_to(root_r)
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=f"upload entry escapes target: {relative}",
        ) from exc
    return dest


def _resolved_pet_spritesheet_path(folder: str) -> Path:
    """Return spritesheet path for ``pets/<folder>`` or raise HTTPException."""
    if not _SAFE_PET_FOLDER.fullmatch(folder):
        raise HTTPException(status_code=400, detail="invalid pet folder name")
    root = pets_install_dir().resolve()
    pet_dir = (root / folder).resolve()
    try:
        pet_dir.relative_to(root)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="pet not found") from exc
    if not pet_dir.is_dir():
        raise HTTPException(status_code=404, detail="pet not found")
    manifest_path = pet_dir / "pet.json"
    if not manifest_path.is_file():
        raise HTTPException(status_code=404, detail="missing pet.json")
    try:
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        # The manifest came in via ``/import-pet`` / ``/import-pet-upload``
        # — so a malformed ``pet.json`` is client-supplied data, not a
        # server-internal fault. Return 400 instead of 500 so the
        # console can surface the right message to the user.
        raise HTTPException(
            status_code=400,
            detail="invalid pet.json",
        ) from exc
    except OSError as exc:
        # The ``is_file()`` check above raced with a concurrent delete
        # or the file became unreadable: that *is* a server-side I/O
        # failure, so 500 is the correct code.
        raise HTTPException(
            status_code=500,
            detail=f"failed to read pet.json: {exc}",
        ) from exc
    rel = data.get("spritesheetPath")
    if not isinstance(rel, str) or not rel.strip():
        raise HTTPException(status_code=404, detail="missing spritesheetPath")
    sheet = (pet_dir / rel).resolve()
    try:
        sheet.relative_to(pet_dir)
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail="invalid spritesheet path",
        ) from exc
    if not sheet.is_file():
        raise HTTPException(status_code=404, detail="spritesheet file missing")
    return sheet


def build_router() -> APIRouter:
    router = APIRouter()

    @router.get("/status")
    def status():
        return {
            "ok": True,
            "plugin": "qwenpaw-pet",
            "desktop": desktop_status_summary(),
        }

    @router.get("/pets")
    def list_pets():
        return {
            "ok": True,
            "petsDir": str(pets_install_dir()),
            "pets": list_installed_pets(),
        }

    @router.get("/pets/{folder}/spritesheet")
    def pet_spritesheet(folder: str):
        """Serve the raw spritesheet image for console previews.

        Auth via the QwenPaw API.
        """
        sheet = _resolved_pet_spritesheet_path(folder)
        media_type, _ = mimetypes.guess_type(str(sheet))
        if not media_type:
            media_type = "application/octet-stream"
        return FileResponse(sheet, media_type=media_type)

    @router.post("/desktop/start")
    def desktop_start():
        return start_desktop_interactive()

    @router.post("/emit-test")
    def emit_test(payload: EmitPayload):
        emit_pet_event(
            payload.event,
            text=payload.text,
            state=payload.state,
            duration_ms=payload.duration_ms,
            manual=True,
        )
        return {"ok": True}

    @router.post("/switch-pet")
    def switch_pet_route(payload: SwitchPetRequest):
        return switch_pet_desktop(
            pet_dir=payload.pet_dir,
            pet_id=payload.pet_id,
        )

    @router.post("/import-pet")
    def import_pet(payload: ImportPetRequest):
        """Install a pet from a *local* folder or ``.zip`` archive.

        Programmatic / CLI path: the file must already exist on the
        server's filesystem. For browser uploads use
        ``/import-pet-upload`` instead.
        """
        raw = (payload.path or "").strip()
        if not raw:
            raise HTTPException(status_code=400, detail="path is required")
        src = Path(raw).expanduser()
        if not src.is_absolute():
            raise HTTPException(
                status_code=400,
                detail="path must be absolute",
            )
        src = src.resolve()
        if not src.exists():
            raise HTTPException(
                status_code=404,
                detail=f"path not found: {src}",
            )

        tmp_root: Path | None = None
        try:
            if src.is_dir():
                source_dir = src
            elif src.is_file() and src.suffix.lower() == ".zip":
                tmp_root = Path(
                    tempfile.mkdtemp(prefix="qwenpaw-pet-import-"),
                )
                _safe_extract_zip(src, tmp_root)
                source_dir = _resolve_pet_source(tmp_root)
            else:
                raise HTTPException(
                    status_code=400,
                    detail="path must be a directory or a .zip file",
                )
            return _install_from_source(source_dir, replace=payload.replace)
        finally:
            if tmp_root is not None:
                shutil.rmtree(tmp_root, ignore_errors=True)

    @router.post("/import-pet-upload")
    def import_pet_upload(
        files: list[UploadFile] = File(...),
        replace: bool = Form(True),
    ):
        """Install a pet from a multipart upload (browser Dropzone).

        Declared as a **synchronous** route so FastAPI runs it in a
        thread pool — the tempdir writes and ``shutil.copyfileobj``
        would otherwise block the ASGI event loop on large uploads.

        Two upload shapes are supported:

        * **Single ``.zip``** — when exactly one file is uploaded and
          its name ends with ``.zip``, the archive is extracted in a
          tempdir (with zip-slip protection) and the resulting layout
          handled like ``/import-pet``.
        * **Folder upload** — when multiple files are uploaded, each
          file's name (typically ``webkitRelativePath`` set by the
          browser when a directory is dropped) is treated as a path
          relative to a tempdir; the resulting directory is then
          installed.

        The ``replace`` form field accepts the usual truthy strings
        (``true``, ``1``, ``yes``, ``on``).
        """
        if not files:
            raise HTTPException(
                status_code=400,
                detail="no files uploaded",
            )

        tmp_root = Path(tempfile.mkdtemp(prefix="qwenpaw-pet-upload-"))
        extract_root: Path | None = None
        try:
            for uf in files:
                dest = _safe_join(tmp_root, uf.filename or "")
                dest.parent.mkdir(parents=True, exist_ok=True)
                with dest.open("wb") as out:
                    shutil.copyfileobj(uf.file, out)

            children = list(tmp_root.iterdir())
            single_zip = (
                len(children) == 1
                and children[0].is_file()
                and children[0].suffix.lower() == ".zip"
            )
            if single_zip:
                extract_root = Path(
                    tempfile.mkdtemp(prefix="qwenpaw-pet-upload-zip-"),
                )
                _safe_extract_zip(children[0], extract_root)
                source_dir = _resolve_pet_source(extract_root)
            else:
                source_dir = _resolve_pet_source(tmp_root)

            return _install_from_source(source_dir, replace=replace)
        finally:
            shutil.rmtree(tmp_root, ignore_errors=True)
            if extract_root is not None:
                shutil.rmtree(extract_root, ignore_errors=True)

    return router
