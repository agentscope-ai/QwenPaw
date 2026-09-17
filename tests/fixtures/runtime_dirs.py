# -*- coding: utf-8 -*-
"""Safe, isolated filesystem resources for pytest runs."""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from pathlib import Path

import pytest

_MARKER_NAME = ".qwenpaw-test-root"
_RUNTIME_ENV_KEYS = (
    "QWENPAW_TEST_ROOT",
    "QWENPAW_WORKING_DIR",
    "COPAW_WORKING_DIR",
    "QWENPAW_SECRET_DIR",
    "QWENPAW_BACKUP_DIR",
)


class UnsafeTestPathError(ValueError):
    """Raised when a test resource could overlap non-test data."""


@dataclass(frozen=True)
class RuntimeDirs:
    """Resolved directories owned by one test or test session."""

    root: Path
    working_dir: Path
    secret_dir: Path
    backup_dir: Path

    @property
    def resource_dirs(self) -> tuple[Path, Path, Path]:
        return (self.working_dir, self.secret_dir, self.backup_dir)

    def as_report(self) -> dict[str, str]:
        return {
            "root": str(self.root),
            "working": str(self.working_dir),
            "secret": str(self.secret_dir),
            "backup": str(self.backup_dir),
        }


@dataclass(frozen=True)
class SessionRuntime:
    """Session bootstrap state used to restore the caller environment."""

    dirs: RuntimeDirs
    workspace_root: Path
    home_dir: Path
    existing_data_dirs: tuple[Path, ...]
    original_env: dict[str, str | None]


_SESSION_RUNTIME: SessionRuntime | None = None


def _resolve(path: Path) -> Path:
    return path.expanduser().resolve()


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
    except ValueError:
        return False
    return True


def validate_test_root(
    test_root: Path,
    *,
    workspace_root: Path,
    home_dir: Path,
    existing_data_dirs: Iterable[Path],
) -> Path:
    """Resolve and reject roots that can overlap project or live data."""
    resolved = _resolve(test_root)
    workspace = _resolve(workspace_root)
    home = _resolve(home_dir)
    live_dirs = tuple(_resolve(path) for path in existing_data_dirs)

    if _is_relative_to(resolved, home) or _is_relative_to(home, resolved):
        raise UnsafeTestPathError(
            f"Test root must not be the user home or its ancestor: {resolved}",
        )
    if _is_relative_to(resolved, workspace) or _is_relative_to(
        workspace,
        resolved,
    ):
        raise UnsafeTestPathError(
            f"Test root must not overlap the workspace: {resolved}",
        )
    for live_dir in live_dirs:
        if _is_relative_to(resolved, live_dir) or _is_relative_to(
            live_dir,
            resolved,
        ):
            raise UnsafeTestPathError(
                f"Test root must not overlap existing data: {resolved}",
            )
    return resolved


def create_runtime_dirs(
    test_root: Path,
    *,
    workspace_root: Path,
    home_dir: Path,
    existing_data_dirs: Iterable[Path],
) -> RuntimeDirs:
    """Create one marked test root with distinct runtime directories."""
    root = validate_test_root(
        test_root,
        workspace_root=workspace_root,
        home_dir=home_dir,
        existing_data_dirs=existing_data_dirs,
    )
    root.mkdir(parents=True, exist_ok=True)
    marker = root / _MARKER_NAME
    marker.write_text("qwenpaw isolated test root\n", encoding="utf-8")

    runtime = RuntimeDirs(
        root=root,
        working_dir=root / "working",
        secret_dir=root / "secret",
        backup_dir=root / "backup",
    )
    for path in runtime.resource_dirs:
        path.mkdir(parents=True, exist_ok=False)
    return runtime


def cleanup_runtime_dirs(runtime: RuntimeDirs) -> None:
    """Remove only marked resources that resolve below their test root."""
    root = _resolve(runtime.root)
    marker = root / _MARKER_NAME
    if not marker.is_file():
        raise UnsafeTestPathError(f"Test root marker is missing: {root}")

    resolved_resources = tuple(_resolve(path) for path in runtime.resource_dirs)
    for resource in resolved_resources:
        if resource == root or not _is_relative_to(resource, root):
            raise UnsafeTestPathError(
                f"Refusing to clean resource outside test root: {resource}",
            )

    for resource in runtime.resource_dirs:
        if resource.exists() or resource.is_symlink():
            if resource.is_symlink():
                resource.unlink()
            else:
                shutil.rmtree(resource)
    marker.unlink()
    root.rmdir()


def _default_live_dirs(home_dir: Path) -> tuple[Path, Path, Path]:
    explicit_working = os.environ.get("QWENPAW_WORKING_DIR") or os.environ.get(
        "COPAW_WORKING_DIR",
    )
    if explicit_working:
        working = _resolve(Path(explicit_working))
    else:
        legacy = home_dir / ".copaw"
        working = _resolve(legacy if legacy.exists() else home_dir / ".qwenpaw")
    secret = _resolve(
        Path(os.environ.get("QWENPAW_SECRET_DIR", f"{working}.secret")),
    )
    backup = _resolve(
        Path(os.environ.get("QWENPAW_BACKUP_DIR", f"{working}.backups")),
    )
    return (working, secret, backup)


def _apply_runtime_env(runtime: RuntimeDirs) -> None:
    values = {
        "QWENPAW_TEST_ROOT": runtime.root,
        "QWENPAW_WORKING_DIR": runtime.working_dir,
        "COPAW_WORKING_DIR": runtime.working_dir,
        "QWENPAW_SECRET_DIR": runtime.secret_dir,
        "QWENPAW_BACKUP_DIR": runtime.backup_dir,
    }
    for key, value in values.items():
        os.environ[key] = str(value)


def bootstrap_test_runtime(workspace_root: Path) -> SessionRuntime:
    """Protect collection-time imports before application modules load."""
    global _SESSION_RUNTIME
    if _SESSION_RUNTIME is not None:
        return _SESSION_RUNTIME

    workspace = _resolve(workspace_root)
    home = _resolve(Path.home())
    live_dirs = _default_live_dirs(home)
    original_env = {key: os.environ.get(key) for key in _RUNTIME_ENV_KEYS}
    session_base = workspace.parent / ".qwenpaw-test-runs"
    session_base.mkdir(parents=True, exist_ok=True)
    session_root = Path(
        tempfile.mkdtemp(prefix="qwenpaw-test-session-", dir=session_base),
    )
    runtime = create_runtime_dirs(
        session_root,
        workspace_root=workspace,
        home_dir=home,
        existing_data_dirs=live_dirs,
    )
    _apply_runtime_env(runtime)
    _SESSION_RUNTIME = SessionRuntime(
        dirs=runtime,
        workspace_root=workspace,
        home_dir=home,
        existing_data_dirs=live_dirs,
        original_env=original_env,
    )
    return _SESSION_RUNTIME


def shutdown_test_runtime() -> None:
    """Restore environment state and safely remove the session resources."""
    global _SESSION_RUNTIME
    session = _SESSION_RUNTIME
    if session is None:
        return
    for key, value in session.original_env.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value
    cleanup_runtime_dirs(session.dirs)
    try:
        session.dirs.root.parent.rmdir()
    except OSError:
        pass
    _SESSION_RUNTIME = None


@pytest.fixture(autouse=True)
def isolated_runtime_dirs(
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[RuntimeDirs]:
    """Give every test unique working, secret, and backup directories."""
    session = _SESSION_RUNTIME
    if session is None:
        raise RuntimeError("bootstrap_test_runtime() must run during conftest import")
    test_root = Path(
        tempfile.mkdtemp(prefix="case-", dir=session.dirs.root),
    )
    runtime = create_runtime_dirs(
        test_root,
        workspace_root=session.workspace_root,
        home_dir=session.home_dir,
        existing_data_dirs=session.existing_data_dirs,
    )
    monkeypatch.setenv("QWENPAW_TEST_ROOT", str(runtime.root))
    monkeypatch.setenv("QWENPAW_WORKING_DIR", str(runtime.working_dir))
    monkeypatch.setenv("COPAW_WORKING_DIR", str(runtime.working_dir))
    monkeypatch.setenv("QWENPAW_SECRET_DIR", str(runtime.secret_dir))
    monkeypatch.setenv("QWENPAW_BACKUP_DIR", str(runtime.backup_dir))

    constant_module = sys.modules.get("qwenpaw.constant")
    if constant_module is not None:
        monkeypatch.setattr(
            constant_module,
            "WORKING_DIR",
            runtime.working_dir,
        )
        monkeypatch.setattr(constant_module, "SECRET_DIR", runtime.secret_dir)
        monkeypatch.setattr(constant_module, "BACKUP_DIR", runtime.backup_dir)

    try:
        yield runtime
    finally:
        cleanup_runtime_dirs(runtime)
