# -*- coding: utf-8 -*-
"""无有效凭据的 Agent 可移植 ZIP 包。"""

from __future__ import annotations

import io
import json
import zipfile
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Mapping

FORMAT_NAME = "qwenpaw-agent"
FORMAT_VERSION = 1
MAX_ENTRY_BYTES = 16 * 1024 * 1024
MAX_TOTAL_BYTES = 64 * 1024 * 1024
MAX_ENTRIES = 4096

_EXCLUDED_NAMES = {
    ".env",
    "agent.json",
    "credentials.yaml",
    "credentials.yml",
    "sessions.json",
    "chats.json",
    "jobs.json",
}
_EXCLUDED_SUFFIXES = {".key", ".p12", ".pfx", ".pem"}
_EXCLUDED_DIRS = {
    ".git",
    ".qwenpaw",
    "browser",
    "browser_profiles",
    "checkpoints",
    "media",
    "sessions",
}
_SECRET_KEY_PARTS = (
    "api_key",
    "apikey",
    "authorization",
    "credential",
    "cookie",
    "password",
    "private_key",
    "secret",
    "token",
)


class PortablePackageError(ValueError):
    """可移植包无效或超过安全限制。"""


@dataclass(frozen=True, slots=True)
class PortableAgentPackage:
    """校验后的导入数据；文件键均为 workspace 内相对 POSIX 路径。"""

    config: dict[str, Any]
    dependencies: dict[str, list[str]]
    files: dict[str, bytes]


def _is_secret_key(key: str) -> bool:
    normalized = key.lower().replace("-", "_")
    return normalized == "headers" or any(
        part in normalized for part in _SECRET_KEY_PARTS
    )


def _remove_secrets(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            str(key): _remove_secrets(item)
            for key, item in value.items()
            if not _is_secret_key(str(key))
        }
    if isinstance(value, list):
        return [_remove_secrets(item) for item in value]
    return value


def _disable_mapping_entries(value: Any) -> None:
    if not isinstance(value, dict):
        return
    for item in value.values():
        if isinstance(item, dict):
            if "enabled" in item:
                item["enabled"] = False


def sanitize_agent_config(agent_config: Mapping[str, Any]) -> dict[str, Any]:
    """移除源身份、运行投递状态和所有可用 Secret。"""
    sanitized = _remove_secrets(deepcopy(dict(agent_config)))
    sanitized["id"] = ""
    sanitized["workspace_dir"] = ""
    sanitized["project_dir"] = None
    sanitized["last_dispatch"] = None
    sanitized["last_dispatch_by_user"] = {}
    channels = sanitized.get("channels")
    _disable_mapping_entries(channels)
    mcp = sanitized.get("mcp")
    if isinstance(mcp, dict):
        clients = mcp.get("clients")
        _disable_mapping_entries(clients)
        if isinstance(clients, dict):
            for client in clients.values():
                if isinstance(client, dict):
                    client["args"] = []
                    client["env"] = {}
                    client["oauth"] = None
    return sanitized


def _dependency_manifest(
    agent_config: Mapping[str, Any],
    workspace_dir: Path,
) -> dict[str, list[str]]:
    models: list[str] = []
    active_model = agent_config.get("active_model")
    if isinstance(active_model, Mapping):
        provider = str(active_model.get("provider_id") or "").strip()
        model = str(active_model.get("model") or "").strip()
        if provider and model:
            models.append(f"{provider}/{model}")
    skills_dir = workspace_dir / "skills"
    skills = (
        sorted(
            child.name
            for child in skills_dir.iterdir()
            if child.is_dir() and not child.is_symlink()
        )
        if skills_dir.is_dir()
        else []
    )
    mcp_clients: list[str] = []
    mcp = agent_config.get("mcp")
    if isinstance(mcp, Mapping) and isinstance(mcp.get("clients"), Mapping):
        mcp_clients = sorted(str(name) for name in mcp["clients"])
    channels = agent_config.get("channels")
    channel_names = (
        sorted(str(name) for name in channels) if isinstance(channels, Mapping) else []
    )
    return {
        "models": sorted(set(models)),
        "skills": skills,
        "mcp_clients": mcp_clients,
        "channels": channel_names,
    }


def _iter_workspace_files(workspace_dir: Path):
    if not workspace_dir.is_dir():
        return
    for path in sorted(workspace_dir.rglob("*")):
        if path.is_symlink() or not path.is_file():
            continue
        relative = path.relative_to(workspace_dir)
        if relative.name.lower() in _EXCLUDED_NAMES:
            continue
        if relative.suffix.lower() in _EXCLUDED_SUFFIXES:
            continue
        if any(part.lower() in _EXCLUDED_DIRS for part in relative.parts[:-1]):
            continue
        yield path, relative.as_posix()


def build_portable_package(
    *,
    agent_config: Mapping[str, Any],
    workspace_dir: Path,
) -> bytes:
    """构建版本化可移植包。"""
    sanitized = sanitize_agent_config(agent_config)
    dependencies = _dependency_manifest(agent_config, workspace_dir)
    manifest = {
        "format": FORMAT_NAME,
        "version": FORMAT_VERSION,
        "dependencies": dependencies,
        "requires_reauthorization": True,
    }
    output = io.BytesIO()
    total_size = 0
    entry_count = 2
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(
            "manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2)
        )
        archive.writestr(
            "config/agent.json",
            json.dumps(sanitized, ensure_ascii=False, indent=2),
        )
        for path, relative in _iter_workspace_files(workspace_dir):
            size = path.stat().st_size
            if size > MAX_ENTRY_BYTES:
                raise PortablePackageError("entry_too_large")
            total_size += size
            entry_count += 1
            if total_size > MAX_TOTAL_BYTES:
                raise PortablePackageError("package_too_large")
            if entry_count > MAX_ENTRIES:
                raise PortablePackageError("too_many_entries")
            archive.write(path, f"workspace/{relative}")
    return output.getvalue()


def _validated_name(name: str) -> PurePosixPath:
    path = PurePosixPath(name.replace("\\", "/"))
    if path.is_absolute() or ".." in path.parts or not path.parts:
        raise PortablePackageError("unsafe_path")
    return path


def read_portable_package(data: bytes) -> PortableAgentPackage:
    """校验并读取可移植包，不向文件系统解压。"""
    try:
        archive = zipfile.ZipFile(io.BytesIO(data), "r")
    except (zipfile.BadZipFile, OSError) as exc:
        raise PortablePackageError("invalid_zip") from exc
    with archive:
        infos = archive.infolist()
        if len(infos) > MAX_ENTRIES:
            raise PortablePackageError("too_many_entries")
        total_size = 0
        for info in infos:
            _validated_name(info.filename)
            if info.file_size > MAX_ENTRY_BYTES:
                raise PortablePackageError("entry_too_large")
            total_size += info.file_size
        if total_size > MAX_TOTAL_BYTES:
            raise PortablePackageError("package_too_large")
        try:
            manifest = json.loads(archive.read("manifest.json"))
            config = json.loads(archive.read("config/agent.json"))
        except (KeyError, json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise PortablePackageError("invalid_manifest") from exc
        if (
            manifest.get("format") != FORMAT_NAME
            or manifest.get("version") != FORMAT_VERSION
        ):
            raise PortablePackageError("unsupported_format")
        if not isinstance(config, dict):
            raise PortablePackageError("invalid_config")
        dependencies = manifest.get("dependencies", {})
        if not isinstance(dependencies, dict):
            raise PortablePackageError("invalid_manifest")
        files: dict[str, bytes] = {}
        for info in infos:
            name = _validated_name(info.filename).as_posix()
            if not name.startswith("workspace/") or info.is_dir():
                continue
            relative = name[len("workspace/") :]
            if not relative:
                continue
            files[relative] = archive.read(info)
    return PortableAgentPackage(
        config=sanitize_agent_config(config),
        dependencies={
            key: sorted({str(item) for item in value})
            for key, value in dependencies.items()
            if isinstance(value, list)
        },
        files=files,
    )
