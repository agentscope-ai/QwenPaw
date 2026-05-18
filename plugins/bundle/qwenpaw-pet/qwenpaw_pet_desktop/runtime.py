# -*- coding: utf-8 -*-
"""Runtime paths, process state, and small JSON helpers."""

from __future__ import annotations

import json
import os
import signal
import secrets
import time
from pathlib import Path
from typing import Any


def home_dir() -> Path:
    return Path(
        os.environ.get(
            "QWENPAW_PET_HOME",
            str(Path.home() / ".qwenpaw-pet"),
        ),
    )


def qwenpaw_working_dir() -> Path:
    """Return QwenPaw's working directory using QwenPaw's precedence."""
    explicit = os.environ.get("QWENPAW_WORKING_DIR") or os.environ.get(
        "COPAW_WORKING_DIR",
    )
    if explicit:
        return Path(explicit).expanduser().resolve()
    try:
        from qwenpaw.constant import WORKING_DIR  # type: ignore

        return Path(WORKING_DIR).expanduser().resolve()
    except Exception:
        legacy_copaw = Path("~/.copaw").expanduser()
        if legacy_copaw.exists():
            return legacy_copaw.resolve()
        return Path("~/.qwenpaw").expanduser().resolve()


def runtime_dir() -> Path:
    return home_dir() / "runtime"


def pets_dir() -> Path:
    return qwenpaw_working_dir() / "pets"


def state_path() -> Path:
    return runtime_dir() / "state.json"


def bubble_path() -> Path:
    return runtime_dir() / "bubble.json"


def token_path() -> Path:
    return runtime_dir() / "update-token"


def pid_path() -> Path:
    return runtime_dir() / "pet-desktop.pid"


def log_path() -> Path:
    return runtime_dir() / "pet-desktop.log"


def bridge_url_path() -> Path:
    """Path to JSON holding the bridge ``url`` for plugin HTTP clients."""
    return runtime_dir() / "desktop-bridge.json"


def read_bridge_url() -> str | None:
    data = read_json(bridge_url_path(), {})
    u = data.get("url")
    if not isinstance(u, str):
        return None
    u = u.strip().rstrip("/")
    return u or None


def write_bridge_url(base_url: str) -> None:
    """Persist the HTTP bridge base URL (may include a non-default port)."""
    ensure_runtime()
    write_json(
        bridge_url_path(),
        {
            "url": base_url.rstrip("/"),
            "updatedAt": int(time.time() * 1000),
        },
    )


def ensure_runtime() -> None:
    runtime_dir().mkdir(parents=True, exist_ok=True)
    pets_dir().mkdir(parents=True, exist_ok=True)


def read_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(
        json.dumps(value, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )
    tmp.replace(path)


def ensure_token() -> str:
    ensure_runtime()
    existing = read_token()
    if existing:
        return existing
    token = secrets.token_hex(32)
    token_path().write_text(token, encoding="utf-8")
    try:
        token_path().chmod(0o600)
    except OSError:
        pass
    return token


def read_token() -> str | None:
    try:
        token = token_path().read_text(encoding="utf-8").strip()
        return token or None
    except OSError:
        return None


def write_pid(pid: int) -> None:
    ensure_runtime()
    write_json(
        pid_path(),
        {
            "pid": pid,
            "updatedAt": int(time.time() * 1000),
        },
    )


def read_pid() -> int | None:
    data = read_json(pid_path(), {})
    pid = data.get("pid")
    return pid if isinstance(pid, int) and pid > 0 else None


def is_pid_running(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def current_process_status() -> dict[str, Any]:
    pid = read_pid()
    running = bool(pid and is_pid_running(pid))
    return {
        "running": running,
        "pid": pid if running else None,
        "home": str(home_dir()),
        "qwenpawWorkingDir": str(qwenpaw_working_dir()),
        "petsDir": str(pets_dir()),
        "statePath": str(state_path()),
        "bubblePath": str(bubble_path()),
    }


def stop_process() -> dict[str, Any]:
    pid = read_pid()
    if not pid:
        return {"ok": True, "stopped": False, "reason": "no pid file"}
    if not is_pid_running(pid):
        return {"ok": True, "stopped": False, "reason": "not running"}
    os.kill(pid, signal.SIGTERM)
    return {"ok": True, "stopped": True, "pid": pid}
