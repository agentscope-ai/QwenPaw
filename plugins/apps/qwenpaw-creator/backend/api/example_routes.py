# -*- coding: utf-8 -*-
# flake8: noqa: E501
"""OSS-hosted inspiration example Projects.

Example archives are not shipped with the plugin; only a small
``backend/examples/manifest.json`` catalogue is bundled, and each entry points
at a public archive URL (OSS) plus its sha256.  Opening an example lazily
downloads the archive through the shared SSRF-safe transport, verifies the
checksum, and materializes it into ``CREATOR_DATA_ROOT`` under the fixed
project id recorded in the manifest.  A ``BUILTIN_EXAMPLE_MARKER`` file is
staged inside the Project directory before publication, so the example is
excluded from the user's project listing atomically with its appearance.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import shutil
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit
from uuid import uuid4

from fastapi import APIRouter, Depends

from domain.errors import (
    BadRequestError,
    NotFoundError,
    StorageIntegrityError,
)
from services.project_files.facade import CreatorFileServices
from services.project_files.store import (
    BUILTIN_EXAMPLE_MARKER,
    UnsafeProjectPath,
    _safe_project_id,
)
from services.runtime_files.locking import CrossProcessFileLock
from services.storage_root import require_creator_data_root
from utils.logger import setup_logger
from utils.remote_download import download_remote_file

from .dependencies import CreatorErrorRoute, project_file_services
from .project_routes import _validate_import_archive

logger = setup_logger("example_routes")

router = APIRouter(
    prefix="/examples",
    tags=["examples"],
    route_class=CreatorErrorRoute,
)

_SHA256_HEX = re.compile(r"^[0-9a-f]{64}$")


def examples_root() -> Path:
    """Bundled examples directory; module-level so tests can monkeypatch."""

    return Path(__file__).resolve().parent.parent / "examples"


def _valid_archive_url(url: Any) -> bool:
    """Only absolute http(s) URLs may serve example archives."""

    if not isinstance(url, str) or not url:
        return False
    parsed = urlsplit(url)
    return parsed.scheme.casefold() in {"http", "https"} and bool(
        parsed.netloc,
    )


def _load_manifest() -> list[dict[str, Any]]:
    """Return manifest entries carrying a valid archive URL.

    A missing or malformed manifest yields an empty catalogue instead of an
    error: the home page simply hides the inspiration section.
    """

    manifest_path = examples_root() / "manifest.json"
    try:
        raw = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    entries = raw.get("examples") if isinstance(raw, dict) else None
    if not isinstance(entries, list):
        return []
    catalogue: list[dict[str, Any]] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        example_id = entry.get("id")
        title = entry.get("title")
        description = entry.get("description")
        project_id = entry.get("projectId")
        archive_url = entry.get("archiveUrl")
        sha256 = entry.get("sha256")
        if not all(
            isinstance(value, str) and value
            for value in (example_id, title, description, project_id)
        ):
            continue
        try:
            _safe_project_id(project_id)
        except UnsafeProjectPath:
            continue
        if not _valid_archive_url(archive_url):
            continue
        # The checksum is optional but must be well-formed when present.
        if sha256 is not None:
            if not isinstance(sha256, str) or not _SHA256_HEX.fullmatch(
                sha256.casefold(),
            ):
                continue
            sha256 = sha256.casefold()
        catalogue.append(
            {
                "id": example_id,
                "title": title,
                "description": description,
                "projectId": project_id,
                "archiveUrl": archive_url,
                "sha256": sha256,
            },
        )
    return catalogue


def _public_item(entry: dict[str, Any], data_root: Path) -> dict[str, Any]:
    return {
        "id": entry["id"],
        "title": entry["title"],
        "description": entry["description"],
        "projectId": entry["projectId"],
        "installed": (
            data_root / entry["projectId"] / "project.json"
        ).is_file(),
    }


@router.get("")
async def list_examples() -> dict[str, Any]:
    data_root = require_creator_data_root()

    def catalogue() -> list[dict[str, Any]]:
        # Manifest parsing and per-entry installed checks are filesystem
        # I/O, so the whole catalogue is built off the event loop.
        return [_public_item(entry, data_root) for entry in _load_manifest()]

    return {"items": await asyncio.to_thread(catalogue)}


def _download_archive(entry: dict[str, Any], archive_path: Path) -> None:
    """Fetch the example archive from OSS and verify its checksum."""

    try:
        download_remote_file(entry["archiveUrl"], str(archive_path))
    except RuntimeError as exc:
        raise StorageIntegrityError(
            f"灵感示例下载失败: {entry['id']}（{str(exc)[:200]}）",
        ) from exc
    expected = entry.get("sha256")
    if not expected:
        return
    digest = hashlib.sha256()
    with archive_path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    if digest.hexdigest() != expected:
        raise StorageIntegrityError(
            f"灵感示例校验失败（sha256 不匹配）: {entry['id']}",
        )


def _materialize_example(entry: dict[str, Any], data_root: Path) -> str:
    """Idempotently publish the example Project from its remote archive."""

    project_id = entry["projectId"]
    target = data_root / project_id
    if (target / "project.json").is_file():
        return project_id

    staging_root = data_root / ".example-staging"
    staging_root.mkdir(mode=0o700, exist_ok=True)
    extract_dir = staging_root / uuid4().hex
    extract_dir.mkdir(mode=0o700)
    try:
        archive_path = extract_dir / "archive.zip"
        _download_archive(entry, archive_path)
        # Pure ZipInfo-level filesystem preflight; no request-scoped state, so
        # it is safe to run inside asyncio.to_thread worker threads.
        _validate_import_archive(archive_path)
        try:
            shutil.unpack_archive(
                str(archive_path),
                extract_dir=extract_dir,
                format="zip",
            )
        except Exception as exc:
            raise StorageIntegrityError(
                f"灵感示例归档无法解包: {entry['id']}",
            ) from exc
        archive_path.unlink(missing_ok=True)
        staged = extract_dir / project_id
        if not (staged / "project.json").is_file():
            raise StorageIntegrityError(
                f"灵感示例归档缺少 {project_id}/project.json: {entry['id']}",
            )
        # The marker is staged before publication so the example can never be
        # observed without it (and thus never leaks into the project listing).
        (staged / BUILTIN_EXAMPLE_MARKER).write_text(
            json.dumps({"exampleId": entry["id"]}) + "\n",
            encoding="utf-8",
        )
        # Serialize with project creation so a same-id race publishes once.
        with CrossProcessFileLock(data_root / ".example-install.lock"):
            if not (target / "project.json").is_file():
                try:
                    os.rename(staged, target)
                except OSError as exc:
                    if not (target / "project.json").is_file():
                        raise StorageIntegrityError(
                            f"灵感示例发布失败: {entry['id']}",
                        ) from exc
        logger.info(
            "materialized inspiration example %s as %s",
            entry["id"],
            project_id,
        )
        return project_id
    finally:
        shutil.rmtree(extract_dir, ignore_errors=True)


@router.post("/{example_id}/open")
async def open_example(
    example_id: str,
    services: CreatorFileServices = Depends(project_file_services),
) -> dict[str, Any]:
    entries = await asyncio.to_thread(_load_manifest)
    entry = next(
        (item for item in entries if item["id"] == example_id),
        None,
    )
    if entry is None:
        raise NotFoundError(f"灵感示例不存在: {example_id}")
    try:
        project_id = await asyncio.to_thread(
            _materialize_example,
            entry,
            require_creator_data_root(),
        )
    except BadRequestError as exc:
        # A corrupt hosted archive is a publishing integrity problem, not a
        # caller mistake.
        raise StorageIntegrityError(
            f"灵感示例归档已损坏: {example_id}（{exc.message}）",
        ) from exc
    # Prime the poll cache so the project page loads without a first-poll miss.
    try:
        await asyncio.to_thread(services.poller.poll_once, project_id)
    except Exception:  # pragma: no cover - cache warming is best effort
        logger.warning("example poll priming failed", exc_info=True)
    return {"projectId": project_id, "installed": True}
