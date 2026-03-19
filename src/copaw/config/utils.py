# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import os
import plistlib
import subprocess
import sys
from pathlib import Path
from typing import Optional, Tuple
from pydantic import ValidationError

from ..constant import (
    HEARTBEAT_FILE,
    JOBS_FILE,
    CHATS_FILE,
    PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH_ENV,
    RUNNING_IN_CONTAINER,
    WORKING_DIR,
)
from .config import (
    Config,
    HeartbeatConfig,
    LastApiConfig,
    LastDispatchConfig,
    load_agent_config,
    save_agent_config,
)


def _normalize_working_dir_bound_paths(data: object) -> object:
    """Normalize legacy ~/.copaw-bound paths to current WORKING_DIR.

    This keeps COPAW_WORKING_DIR effective even if user config files contain
    older hard-coded paths like "~/.copaw/media" or
    "/Users/x/.copaw/workspaces/...".
    Only rewrites known working-dir-bound keys.
    """
    legacy_root_tilde = "~/.copaw"
    legacy_root_abs = str(Path(legacy_root_tilde).expanduser().resolve())
    new_root_abs = str(WORKING_DIR)

    def _rewrite_path_value(v: object) -> object:
        if not isinstance(v, str) or not v:
            return v
        if v.startswith(legacy_root_tilde):
            return new_root_abs + v[len(legacy_root_tilde) :]
        if v.startswith(legacy_root_abs):
            return new_root_abs + v[len(legacy_root_abs) :]
        return v

    def _walk(obj: object, key: str | None = None) -> object:
        if isinstance(obj, dict):
            out: dict = {}
            for k, v in obj.items():
                out[k] = _walk(v, str(k))
            return out
        if isinstance(obj, list):
            return [_walk(x, key) for x in obj]
        if key in {"workspace_dir", "media_dir"}:
            return _rewrite_path_value(obj)
        return obj

    return _walk(data, None)


def _discover_system_chromium_path() -> Optional[str]:
    """Scan common locations for Chrome/Chromium/Edge so we can use existing
    browser instead of downloading via Playwright. Returns first found path.
    """
    candidates: list[Path] = []
    if sys.platform == "win32":
        pf = os.environ.get("ProgramFiles", "C:\\Program Files")
        pf86 = os.environ.get("ProgramFiles(x86)", "C:\\Program Files (x86)")
        candidates = [
            Path(pf) / "Google" / "Chrome" / "Application" / "chrome.exe",
            Path(pf86) / "Google" / "Chrome" / "Application" / "chrome.exe",
            Path(pf) / "Microsoft" / "Edge" / "Application" / "msedge.exe",
            Path(pf86) / "Microsoft" / "Edge" / "Application" / "msedge.exe",
            Path(pf) / "Chromium" / "Application" / "chrome.exe",
        ]
    elif sys.platform == "darwin":
        candidates = [
            Path(
                "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
            ),
            Path("/Applications/Chromium.app/Contents/MacOS/Chromium"),
            Path(
                "/Applications/Microsoft Edge.app/Contents/MacOS/"
                "Microsoft Edge",
            ),
        ]
    else:
        # Linux and other
        candidates = [
            Path("/usr/bin/google-chrome"),
            Path("/usr/bin/google-chrome-stable"),
            Path("/usr/bin/chromium"),
            Path("/usr/bin/chromium-browser"),
            Path("/usr/lib/chromium/chromium"),
        ]
    for p in candidates:
        if p.is_file():
            return str(p.resolve())
    return None


def get_playwright_chromium_executable_path() -> Optional[str]:
    """Chromium path from env when set and existing file (e.g. container).
    In container, if env unset or path missing, try common system paths.
    When not in container and env unset, scan for installed
    Chrome/Chromium/Edge so we prefer user's browser instead of
    triggering a download.
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
    return _discover_system_chromium_path()


# Bundle ID / ProgId -> (playwright kind, typical path or None for webkit).
_BundleItem = Tuple[str, str, Optional[str]]
_DARWIN_DEFAULT_BROWSER_BUNDLES: Tuple[_BundleItem, ...] = (
    ("com.apple.safari", "webkit", None),
    (
        "com.google.chrome",
        "chromium",
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    ),
    (
        "com.microsoft.edgemac",
        "chromium",
        "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
    ),
    (
        "org.mozilla.firefox",
        "firefox",
        "/Applications/Firefox.app/Contents/MacOS/firefox",
    ),
    (
        "org.mozilla.firefoxdeveloperedition",
        "firefox",
        "/Applications/Firefox Developer Edition.app/Contents/MacOS/firefox",
    ),
    (
        "com.google.chrome.beta",
        "chromium",
        "/Applications/Google Chrome Beta.app/Contents/MacOS/Google Chrome",
    ),
    (
        "com.google.chrome.canary",
        "chromium",
        "/Applications/Google Chrome Canary.app/Contents/MacOS/Google Chrome",
    ),
)


# pylint: disable=too-many-branches
def _get_darwin_default_browser() -> Tuple[Optional[str], Optional[str]]:
    """Return (browser_kind, executable_path) for macOS default HTTP
    handler.
    """
    result: Tuple[Optional[str], Optional[str]] = (None, None)
    pref = "~/Library/Preferences"
    plist_name = (
        "com.apple.LaunchServices.com.apple.launchservices.secure.plist"
    )
    plist_path = Path(os.path.expanduser(pref)) / plist_name
    if not plist_path.is_file():
        return result
    try:
        with open(plist_path, "rb") as f:
            data = plistlib.load(f)
    except (OSError, plistlib.InvalidFileException):
        return result
    handlers = data.get("LSHandlers") or data.get("LSHandler")
    if not isinstance(handlers, list):
        return result
    bundle_id: Optional[str] = None
    for item in handlers:
        if not isinstance(item, dict):
            continue
        if item.get("LSHandlerURLScheme") in ("http", "https"):
            bundle_id = item.get("LSHandlerRoleAll") or item.get(
                "LSHandlerRoleViewer",
            )
            if bundle_id:
                break
    if not bundle_id:
        return result
    for bid, kind, path in _DARWIN_DEFAULT_BROWSER_BUNDLES:
        if bid != bundle_id:
            continue
        if path and Path(path).is_file():
            result = (kind, path)
            break
        if kind == "webkit":
            result = ("webkit", None)
            break
    else:
        if bundle_id == "com.apple.safari":
            result = ("webkit", None)
    return result


def _get_win32_default_browser() -> Tuple[Optional[str], Optional[str]]:
    """Return (browser_kind, executable_path) for Windows default HTTP
    handler.
    """
    try:
        import winreg
    except ImportError:
        return (None, None)
    subkey = (
        r"Software\Microsoft\Windows\Shell\Associations"
        r"\UrlAssociations\http\UserChoice"
    )
    try:
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            subkey,
            0,
            winreg.KEY_READ,
        )
        prog_id, _ = winreg.QueryValueEx(key, "ProgId")
        winreg.CloseKey(key)
    except OSError:
        return (None, None)
    # ProgId -> (kind, path template). %1 is URL.
    prog_to_cmd: dict[str, Tuple[str, str]] = {
        "ChromeHTML": ("chromium", r"Google\Chrome\Application\chrome.exe"),
        "MSEdgeHTM": ("chromium", r"Microsoft\Edge\Application\msedge.exe"),
        "FirefoxURL": ("firefox", r"Mozilla Firefox\firefox.exe"),
    }
    for pid, (kind, suffix) in prog_to_cmd.items():
        if not (prog_id == pid or prog_id.startswith(pid)):
            continue
        for env_key in ("ProgramFiles", "ProgramFiles(x86)"):
            default = (
                "C:\\Program Files"
                if env_key == "ProgramFiles"
                else "C:\\Program Files (x86)"
            )
            base = os.environ.get(env_key, default)
            path = Path(base) / suffix
            if path.is_file():
                return (kind, str(path.resolve()))
    return (None, None)


def _get_linux_default_browser() -> Tuple[Optional[str], Optional[str]]:
    """Return (browser_kind, executable_path) for Linux default HTTP
    handler.
    """
    try:
        out = subprocess.run(
            ["xdg-mime", "query", "default", "x-scheme-handler/http"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        desktop = (out.stdout or "").strip() if out.returncode == 0 else ""
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return (None, None)
    if not desktop:
        return (None, None)
    xdg_home = os.environ.get(
        "XDG_DATA_HOME",
        os.path.expanduser("~/.local/share"),
    )
    for base in [Path(xdg_home), Path("/usr/share")]:
        path = base / "applications" / desktop
        if not path.is_file():
            continue
        try:
            with open(path, encoding="utf-8") as f:
                for line in f:
                    if line.strip().startswith("Exec="):
                        exe = line.split("=", 1)[1].strip().split()[0]
                        if exe.startswith("/") and Path(exe).is_file():
                            return _linux_desktop_to_kind_and_path(exe)
                        for p in ["/usr/bin", "/usr/local/bin"]:
                            candidate = Path(p) / exe
                            if candidate.is_file():
                                return _linux_desktop_to_kind_and_path(
                                    str(candidate),
                                )
                        break
        except OSError:
            continue
    return (None, None)


def _linux_desktop_to_kind_and_path(exe_path: str) -> Tuple[str, str]:
    """Map Linux browser executable name to (kind, path)."""
    name = Path(exe_path).name.lower()
    if "chrome" in name or "chromium" in name:
        return ("chromium", exe_path)
    if "firefox" in name:
        return ("firefox", exe_path)
    if "edge" in name:
        return ("chromium", exe_path)
    return ("chromium", exe_path)


def get_system_default_browser() -> Tuple[Optional[str], Optional[str]]:
    """Return (browser_kind, executable_path) for the OS default HTTP browser.

    browser_kind is 'chromium', 'firefox', or 'webkit'. path is None for
    webkit. Returns (None, None) if detection fails or unsupported.
    """
    if is_running_in_container():
        return (None, None)
    if sys.platform == "darwin":
        return _get_darwin_default_browser()
    if sys.platform == "win32":
        return _get_win32_default_browser()
    if sys.platform.startswith("linux"):
        return _get_linux_default_browser()
    return (None, None)


def get_available_channels() -> Tuple[str, ...]:
    """Return channel keys enabled for this run (built-in + entry point
    copaw.channels), filtered by COPAW_ENABLED_CHANNELS or
    COPAW_DISABLED_CHANNELS when set.

    * COPAW_ENABLED_CHANNELS — whitelist (only these channels are active).
    * COPAW_DISABLED_CHANNELS — blacklist (all channels *except* these).
    * If both are set, COPAW_ENABLED_CHANNELS takes precedence.
    * If neither is set, all discovered channels are returned.
    """
    from ..app.channels.registry import get_channel_registry

    registry = get_channel_registry()
    all_keys = tuple(registry.keys())

    raw_enabled = os.environ.get("COPAW_ENABLED_CHANNELS", "").strip()
    if raw_enabled:
        enabled = {ch.strip() for ch in raw_enabled.split(",") if ch.strip()}
        return tuple(k for k in all_keys if k in enabled) or all_keys

    raw_disabled = os.environ.get("COPAW_DISABLED_CHANNELS", "").strip()
    if raw_disabled:
        disabled = {ch.strip() for ch in raw_disabled.split(",") if ch.strip()}
        return tuple(k for k in all_keys if k not in disabled) or all_keys

    return all_keys


def is_running_in_container() -> bool:
    """Return True if running inside a container (Docker/Kubernetes).
    Prefer env COPAW_RUNNING_IN_CONTAINER (1/true/yes) at call time so
    supervisord child gets correct value; else check /.dockerenv and cgroup.
    """
    if RUNNING_IN_CONTAINER:
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


def _remove_nested_key(data: dict, path: list) -> bool:
    """Remove a nested key from *data* given a path list.

    Returns True if the key was found and removed.
    """
    obj = data
    for segment in path[:-1]:
        if isinstance(segment, str) and isinstance(obj, dict):
            obj = obj.get(segment)
        elif isinstance(segment, int) and isinstance(obj, list):
            try:
                obj = obj[segment]
            except IndexError:
                return False
        else:
            return False
        if obj is None:
            return False
    last = path[-1]
    if isinstance(last, str) and isinstance(obj, dict) and last in obj:
        del obj[last]
        return True
    return False


def _remove_bad_field(data: dict, loc: list) -> bool:
    """Try to remove the field at *loc*; fall back to ancestor keys."""
    if _remove_nested_key(data, loc):
        return True
    for end in range(len(loc) - 1, 0, -1):
        if _remove_nested_key(data, loc[:end]):
            return True
    return False


def load_config(config_path: Optional[Path] = None) -> Config:
    """Load config from file. Returns default Config if file is missing."""
    if config_path is None:
        config_path = get_config_path()
    if not config_path.is_file():
        return Config()

    try:
        with open(config_path, "r", encoding="utf-8") as file:
            data = json.load(file)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return Config()

    data = _normalize_working_dir_bound_paths(data)
    # Backward compat: top-level last_api_host / last_api_port -> last_api
    if "last_api_host" in data or "last_api_port" in data:
        la = data.setdefault("last_api", {})
        if "host" not in la and "last_api_host" in data:
            la["host"] = data.get("last_api_host")
        if "port" not in la and "last_api_port" in data:
            la["port"] = data.get("last_api_port")

    try:
        return Config.model_validate(data)
    except ValidationError as exc:
        fixed_any = False
        for err in exc.errors():
            loc = list(err.get("loc", []))
            if loc and _remove_bad_field(data, loc):
                fixed_any = True
        if not fixed_any:
            raise

    try:
        return Config.model_validate(data)
    except ValidationError:
        return Config()


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


def get_heartbeat_config(agent_id: Optional[str] = None) -> HeartbeatConfig:
    """Return effective heartbeat config (from agent config or default).

    Args:
        agent_id: Agent ID to load config from. If None, tries to load from
                  root config.agents.defaults (legacy behavior).

    Returns:
        HeartbeatConfig: Heartbeat configuration or default.
    """
    if agent_id is not None:
        try:
            agent_config = load_agent_config(agent_id)
            hb = agent_config.heartbeat
            return hb if hb is not None else HeartbeatConfig()
        except Exception:
            return HeartbeatConfig()

    # Legacy: try to load from root config
    config = load_config()
    if config.agents.defaults is None:
        return HeartbeatConfig()
    hb = config.agents.defaults.heartbeat
    return hb if hb is not None else HeartbeatConfig()


def update_last_dispatch(
    channel: str,
    user_id: str,
    session_id: str,
    agent_id: Optional[str] = None,
) -> None:
    """Persist last user-reply dispatch target (user send+reply only).

    Args:
        channel: Channel name
        user_id: User ID
        session_id: Session ID
        agent_id: Agent ID to update. If None, updates root config (legacy).
    """
    if agent_id is not None:
        try:
            agent_config = load_agent_config(agent_id)
            agent_config.last_dispatch = LastDispatchConfig(
                channel=channel,
                user_id=user_id,
                session_id=session_id,
            )
            save_agent_config(agent_id, agent_config)
            return
        except Exception:
            pass

    # Legacy: update root config
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
