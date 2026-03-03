# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Optional, Tuple

from ..constant import (
    HEARTBEAT_FILE,
    JOBS_FILE,
    CHATS_FILE,
    PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH_ENV,
    RUNNING_IN_CONTAINER,
    WORKING_DIR,
)
from .config import Config, HeartbeatConfig, LastApiConfig, LastDispatchConfig


def get_playwright_chromium_executable_path() -> Optional[str]:
    """Chromium path from env when set and existing file (e.g. container).
    In container, if env unset or path missing, try common system paths.
    """
    path = os.environ.get(PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH_ENV)
    if path and os.path.isfile(path):
        return path
    if is_running_in_container():
        for candidate in (
            "/usr/bin/chromium",
            "/usr/bin/chromium-browser",
            "/usr/lib/chromium/chromium",
        ):
            if os.path.isfile(candidate):
                return candidate
    return None


def get_available_channels() -> Tuple[str, ...]:
    """Return channel keys enabled for this run (built-in + entry point
    copaw.channels), filtered by COPAW_ENABLED_CHANNELS when set.
    """
    from ..app.channels.registry import get_channel_registry

    registry = get_channel_registry()
    all_keys = tuple(registry.keys())
    raw = os.environ.get("COPAW_ENABLED_CHANNELS", "").strip()
    if not raw:
        return all_keys
    enabled = tuple(ch.strip() for ch in raw.split(",") if ch.strip())
    return tuple(k for k in all_keys if k in enabled) or all_keys


def is_running_in_container() -> bool:
    """Return True if running inside a container (Docker/Kubernetes).
    Prefer env COPAW_RUNNING_IN_CONTAINER (1/true/yes) at call time so
    supervisord child gets correct value; else check /.dockerenv and cgroup.
    """
    if os.environ.get("COPAW_RUNNING_IN_CONTAINER", "").strip().lower() in (
        "1",
        "true",
        "yes",
    ):
        return True
    if RUNNING_IN_CONTAINER.strip().lower() in ("1", "true", "yes"):
        return True
    if os.path.exists("/.dockerenv"):
        return True
    try:
        with open("/proc/1/cgroup", encoding="utf-8") as f:
            content = f.read()
            return "docker" in content or "kubepods" in content
    except (OSError, FileNotFoundError):
        return False


def get_config_path() -> Path:
    """Get the path to the config file."""
    return WORKING_DIR.joinpath("config.json")


def get_heartbeat_query_path() -> Path:
    """Get path to heartbeat query file (HEARTBEAT.md in working dir)."""
    return get_config_path().parent.joinpath(HEARTBEAT_FILE)


def load_config(config_path: Optional[Path] = None) -> Config:
    """Load config from file. Returns default Config if file is missing."""
    if config_path is None:
        config_path = get_config_path()
    if not config_path.is_file():
        return Config()
    with open(config_path, "r", encoding="utf-8") as file:
        data = json.load(file)
    # Backward compat: top-level last_api_host / last_api_port -> last_api
    if "last_api_host" in data or "last_api_port" in data:
        la = data.setdefault("last_api", {})
        if "host" not in la and "last_api_host" in data:
            la["host"] = data.get("last_api_host")
        if "port" not in la and "last_api_port" in data:
            la["port"] = data.get("last_api_port")
    return Config.model_validate(data)


def save_config(config: Config, config_path: Optional[Path] = None) -> None:
    """Save the config to the file."""
    if config_path is None:
        config_path = get_config_path()
    config_path.parent.mkdir(parents=True, exist_ok=True)
    with open(config_path, "w", encoding="utf-8") as file:
        json.dump(
            config.model_dump(mode="json", by_alias=True),
            file,
            indent=2,
            ensure_ascii=False,
        )


def get_heartbeat_config() -> HeartbeatConfig:
    """Return effective heartbeat config (from file or default 30m/main)."""
    config = load_config()
    hb = config.agents.defaults.heartbeat
    return hb if hb is not None else HeartbeatConfig()


def update_last_dispatch(channel: str, user_id: str, session_id: str) -> None:
    """Persist last user-reply dispatch target (user send+reply only)."""
    config = load_config()
    config.last_dispatch = LastDispatchConfig(
        channel=channel,
        user_id=user_id,
        session_id=session_id,
    )
    save_config(config)


def read_last_api() -> Optional[Tuple[str, int]]:
    """Read last API host/port from config (via config load/save)."""
    config = load_config()
    host = config.last_api.host
    port = config.last_api.port
    if not host or port is None:
        return None
    return host, port


def write_last_api(host: str, port: int) -> None:
    """Write last API host/port to config (via config load/save)."""
    config = load_config()
    config.last_api = LastApiConfig(host=host, port=port)
    save_config(config)


def get_jobs_path() -> Path:
    """Return cron jobs.json path."""

    return (WORKING_DIR / JOBS_FILE).expanduser()


def get_chats_path() -> Path:
    """Return chats.json path."""
    return (WORKING_DIR / CHATS_FILE).expanduser()
