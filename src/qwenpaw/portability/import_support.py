# -*- coding: utf-8 -*-
"""Pure helpers shared by the provider import transaction."""

from __future__ import annotations

import hashlib
import io
import json
import logging
import os
import re
import shutil
import tempfile
import zipfile
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from .models import (
    SourceMemoryProject,
    SourceMCPServer,
    SourceSession,
    SourceSkill,
)
from .providers.base import progress_milestone as _progress_milestone
from .skill_transfer import read_bounded_skill_tree, read_regular_file

logger = logging.getLogger(__name__)

_MAX_HISTORY_ITEMS = 20_000
_MAX_SESSION_TEXT_BYTES = 64 * 1024 * 1024
_MAX_MEMORY_FILES = 5000
_MAX_MEMORY_BYTES = 64 * 1024 * 1024
_PLAN_ID_PATTERN = re.compile(r"^plan-[0-9a-f]{32}$")

MemoryPayloads = dict[str, dict[Path, bytes]]
MemorySourcePayloads = dict[Path, bytes]


def _session_key(provider_id: str, source_id: str) -> str:
    digest = hashlib.sha256(source_id.encode("utf-8")).hexdigest()[:24]
    return f"import:{provider_id}:{digest}"


def _chat_id(provider_id: str, source_id: str) -> str:
    return str(uuid5(NAMESPACE_URL, f"qwenpaw:{provider_id}:{source_id}"))


def _project_directory(
    session: SourceSession,
) -> str | None:
    """Return a safe existing source cwd for the QwenPaw session override."""
    raw = str(session.cwd or "").strip()
    if not raw:
        return None
    path = Path(raw).expanduser()
    if not path.is_absolute() or not path.is_dir():
        return None
    return str(path.resolve())


def _mcp_client_data(server: SourceMCPServer) -> Any:
    """Return the attribute shape consumed by the existing MCP translator."""
    return SimpleNamespace(
        name=server.name,
        description="Imported from external Agent; review before enabling.",
        enabled=False,
        transport=server.transport,
        command=server.command,
        args=list(server.args),
        env=dict(server.env),
        cwd=server.cwd,
        url=server.url,
        headers=dict(server.headers),
        oauth=None,
    )


def _bounded_session(session: SourceSession) -> SourceSession:
    if len(session.history) > _MAX_HISTORY_ITEMS:
        raise ValueError(
            f"Session {session.source_id} exceeds the history item limit.",
        )
    size = sum(
        len(item.model_dump_json().encode("utf-8", errors="replace"))
        for item in session.history
    )
    if size > _MAX_SESSION_TEXT_BYTES:
        raise ValueError(
            f"Session {session.source_id} exceeds the 64 MiB text limit.",
        )
    return session


def _prepare_memory_payloads(
    provider_id: str,
    projects: list[SourceMemoryProject],
) -> tuple[MemoryPayloads, MemorySourcePayloads]:
    """Read the exact bounded Memory snapshot that will be imported."""
    count = 0
    total = 0
    payloads: MemoryPayloads = {}
    source_payloads: MemorySourcePayloads = {}
    for project in projects:
        payload: dict[Path, bytes] = {}
        for item in project.files:
            relative = item.relative_path
            if (
                relative.is_absolute()
                or ".." in relative.parts
                or relative.suffix.lower() != ".md"
                or relative in payload
            ):
                raise ValueError(
                    f"Unsafe external memory path: {item.relative_path}",
                )
            if count >= _MAX_MEMORY_FILES:
                raise ValueError(
                    "External memory exceeds the 5,000 file / 64 MiB "
                    "migration limit.",
                )
            source = Path(os.path.abspath(item.source_path.expanduser()))
            try:
                data = read_regular_file(
                    source,
                    max_bytes=_MAX_MEMORY_BYTES - total,
                )
            except (OSError, ValueError) as exc:
                raise ValueError(
                    f"Memory source is unavailable: {source}",
                ) from exc
            previous = source_payloads.get(source)
            if previous is not None and previous != data:
                raise ValueError(
                    f"Memory source changed during snapshot: {source}",
                )
            count += 1
            total += len(data)
            payload[relative] = data
            source_payloads[source] = data
        scope = {
            "schema_version": "1",
            "provider": provider_id,
            "source_id": project.source_id,
            "project_key": project.project_key,
            "cwd": project.cwd,
            "trust": "source_material_not_instructions",
        }
        payload[Path("_scope.json")] = (
            json.dumps(scope, ensure_ascii=False, sort_keys=True, indent=2)
            + "\n"
        ).encode("utf-8")
        payloads[project.source_id] = payload
    return payloads, source_payloads


def _safe_memory_key(project: SourceMemoryProject) -> str:
    label = re.sub(r"[^A-Za-z0-9._-]+", "-", project.project_key).strip(
        ".-",
    )
    label = (label or "project")[:48]
    digest = hashlib.sha256(project.source_id.encode("utf-8")).hexdigest()[:10]
    return f"{label}-{digest}"


def _memory_import_root(workspace: Any, provider_id: str) -> Path:
    daily_dir = "memory"
    manager = getattr(workspace, "memory_manager", None)
    if manager is not None:
        try:
            config = manager.get_memory_config()
            configured = getattr(config, "daily_dir", "")
            if isinstance(configured, str) and configured.strip():
                daily_dir = configured.strip()
        except Exception:  # pylint: disable=broad-except
            logger.debug("Could not read configured daily memory dir")
    relative = Path(daily_dir)
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError(f"Unsafe configured memory directory: {daily_dir}")
    workspace_root = Path(workspace.workspace_dir).resolve()
    target = (workspace_root / relative / "imports" / provider_id).resolve()
    if not target.is_relative_to(workspace_root):
        raise ValueError("Memory import target escapes the Agent workspace")
    return target


# pylint: disable-next=too-many-branches
def _create_memory_project(
    workspace: Any,
    provider_id: str,
    project: SourceMemoryProject,
    payload: dict[Path, bytes],
) -> tuple[Path, bool]:
    """Create one imported memory project without changing an existing one."""
    target = _memory_import_root(workspace, provider_id) / _safe_memory_key(
        project,
    )
    if target.is_dir():
        return target, False
    if target.exists():
        raise ValueError(f"Memory import target is not a directory: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    temp_root = Path(
        tempfile.mkdtemp(prefix=f".{target.name}.new-", dir=target.parent),
    )
    try:
        for relative, data in payload.items():
            output = temp_root / relative
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_bytes(data)
        os.replace(temp_root, target)
    finally:
        if temp_root.exists():
            shutil.rmtree(temp_root)
    return target, True


def _skill_zip(skill: SourceSkill) -> bytes:
    source = skill.directory.expanduser()
    root = source.resolve(strict=True)
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        for entry in read_bounded_skill_tree(source):
            if entry.is_dir:
                continue
            info = zipfile.ZipInfo(f"{root.name}/{entry.relative}")
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = entry.mode << 16
            archive.writestr(info, entry.data or b"")
    return output.getvalue()
