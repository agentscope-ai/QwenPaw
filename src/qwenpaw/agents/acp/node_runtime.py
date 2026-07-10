# -*- coding: utf-8 -*-
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

from pydantic import BaseModel, Field

from ...constant import WORKING_DIR

DESKTOP_NODE_RUNTIME_ENV = "QWENPAW_DESKTOP_NODE_RUNTIME"
NPM_CACHE_ENV = "NPM_CONFIG_CACHE"


class ACPNodeRuntimeCandidate(BaseModel):
    key: str
    label: str
    node_path: str = ""
    npx_path: str = ""
    node_version: str = ""
    npx_version: str = ""
    available: bool = False
    reason_code: str = ""
    reason: str = ""


class ACPNodeRuntimeStatus(BaseModel):
    node_path: str = ""
    effective_node_path: str = ""
    candidates: list[ACPNodeRuntimeCandidate] = Field(default_factory=list)


def get_node_runtime_status(node_path: str = "") -> ACPNodeRuntimeStatus:
    candidates: list[ACPNodeRuntimeCandidate] = []
    configured = node_path.strip()

    bundled_path = _bundled_node_path()
    if bundled_path:
        candidates.append(
            resolve_node_runtime(
                str(bundled_path),
                key="bundled",
                label="bundled",
            ),
        )

    system_node = shutil.which("node")
    if system_node:
        _append_unique(
            candidates,
            resolve_node_runtime(
                system_node,
                key="system",
                label="system",
            ),
        )
    else:
        candidates.append(
            ACPNodeRuntimeCandidate(
                key="system",
                label="system",
                reason_code="system_node_missing",
                reason="System Node was not detected",
            ),
        )

    if configured and not any(
        _same_path(configured, candidate.node_path) for candidate in candidates
    ):
        candidates.append(
            resolve_node_runtime(
                configured,
                key="custom",
                label="custom",
            ),
        )

    effective = _effective_node_path(configured, candidates)
    return ACPNodeRuntimeStatus(
        node_path=configured,
        effective_node_path=effective,
        candidates=candidates,
    )


def resolve_node_runtime(
    node_path: str,
    *,
    key: str = "custom",
    label: str = "custom",
) -> ACPNodeRuntimeCandidate:
    node = _normalize_node_path(node_path)
    candidate = ACPNodeRuntimeCandidate(
        key=key,
        label=label,
        node_path=str(node),
    )
    if not node.is_file():
        candidate.reason_code = "node_missing"
        candidate.reason = "Node path does not exist"
        return candidate

    env = _prepend_path(dict(os.environ), node.parent)
    node_version, error = _version(str(node), env)
    if error:
        candidate.reason_code = "version_check_failed"
        candidate.reason = error
        return candidate

    npx = _npx_path(node)
    if not npx:
        candidate.node_version = node_version
        candidate.reason_code = "npx_missing"
        candidate.reason = "npx was not found"
        return candidate

    npx_version, error = _version(str(npx), env)
    if error:
        candidate.node_version = node_version
        candidate.npx_path = str(npx)
        candidate.reason_code = "version_check_failed"
        candidate.reason = error
        return candidate

    candidate.node_version = node_version
    candidate.npx_path = str(npx)
    candidate.npx_version = npx_version
    candidate.available = True
    return candidate


def build_acp_process_env(base_env: dict[str, str]) -> dict[str, str]:
    from ...config import load_config

    env = dict(base_env)
    node_path = _effective_node_path_for_process(
        load_config().acp.node_path,
        env,
    )
    if node_path:
        env = _prepend_path(env, node_path.parent)
    env.setdefault(NPM_CACHE_ENV, str(WORKING_DIR / "npm-cache"))
    return env


def _effective_node_path_for_process(
    node_path: str,
    env: dict[str, str],
) -> Path | None:
    configured = node_path.strip()
    if configured:
        node = _normalize_node_path(configured)
        if _runtime_files_available(node):
            return node

    bundled = _bundled_node_path()
    if _runtime_files_available(bundled):
        return bundled

    system_node = shutil.which("node", path=env.get(_path_env_key(env)))
    if system_node:
        node = _normalize_node_path(system_node)
        if _runtime_files_available(node):
            return node
    return None


def _effective_node_path(
    configured: str,
    candidates: list[ACPNodeRuntimeCandidate],
) -> str:
    if configured:
        for candidate in candidates:
            if candidate.available and _same_path(
                configured,
                candidate.node_path,
            ):
                return candidate.node_path
    for key in ("bundled", "system"):
        for candidate in candidates:
            if candidate.key == key and candidate.available:
                return candidate.node_path
    return ""


def _bundled_node_path() -> Path | None:
    root = os.environ.get(DESKTOP_NODE_RUNTIME_ENV, "").strip()
    if not root:
        return None
    return _normalize_node_path(_strip_windows_extended_prefix(root))


def _normalize_node_path(value: str) -> Path:
    path = Path(os.path.expandvars(value)).expanduser()
    if path.is_dir():
        path = path / ("node.exe" if os.name == "nt" else "bin/node")
    return path


def _strip_windows_extended_prefix(value: str) -> str:
    if os.name != "nt":
        return value
    if value.startswith("\\\\?\\UNC\\"):
        return "\\\\" + value[8:]
    if value.startswith("\\\\?\\"):
        return value[4:]
    return value


def _npx_path(node: Path) -> Path | None:
    names = ["npx.cmd", "npx.exe"] if os.name == "nt" else ["npx"]
    for name in names:
        candidate = node.parent / name
        if candidate.is_file():
            return candidate
    found = shutil.which("npx", path=str(node.parent))
    return Path(found) if found else None


def _runtime_files_available(node: Path | None) -> bool:
    return bool(node and node.is_file() and _npx_path(node))


def _prepend_path(env: dict[str, str], path: Path) -> dict[str, str]:
    key = _path_env_key(env)
    existing = env.get(key, "")
    env[key] = (
        os.pathsep.join([str(path), existing]) if existing else str(path)
    )
    for other in list(env):
        if other != key and other.lower() == "path":
            env.pop(other)
    return env


def _path_env_key(env: dict[str, str]) -> str:
    key = "Path" if os.name == "nt" else "PATH"
    for name in env:
        if name.lower() == "path":
            key = name
    return key


def _version(executable: str, env: dict[str, str]) -> tuple[str, str]:
    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        result = subprocess.run(
            [executable, "--version"],
            capture_output=True,
            text=True,
            timeout=5,
            env=env,
            creationflags=creationflags,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return "", f"{Path(executable).name} --version failed: {exc}"
    if result.returncode != 0:
        return (
            "",
            (result.stderr or result.stdout or "version check failed").strip(),
        )
    return (result.stdout or result.stderr).strip(), ""


def _append_unique(
    candidates: list[ACPNodeRuntimeCandidate],
    candidate: ACPNodeRuntimeCandidate,
) -> None:
    if candidate.node_path and any(
        _same_path(candidate.node_path, existing.node_path)
        for existing in candidates
    ):
        return
    candidates.append(candidate)


def _same_path(left: str, right: str) -> bool:
    if not left or not right:
        return False
    return os.path.normcase(os.path.abspath(left)) == os.path.normcase(
        os.path.abspath(right),
    )
