# -*- coding: utf-8 -*-
"""Chrome extension setup command."""

from __future__ import annotations

import json
import os
import secrets
import shutil
import stat
import struct
import subprocess
import sys
import webbrowser
from ipaddress import ip_address
from pathlib import Path

from qwenpaw.config.utils import read_last_api
from qwenpaw.utils.io_utils import write_json_atomic

try:
    # Cross-track contract (lands with unified browser, PR #6276).
    from qwenpaw.browser.control_link.chrome.protocol import (
        NM_HOST_BASENAME,
        NM_HOST_WIN_SUFFIX,
    )
except ImportError:  # pre-rebase fallback; values locked 2026-07-27.
    # After rebasing onto a main that contains PR #6276 this branch is
    # dead code: delete the whole except block in the rebase commit.
    NM_HOST_BASENAME = "qwenpaw-nm-host"
    NM_HOST_WIN_SUFFIX = ".bat"

NATIVE_HOST_NAME = "com.qwenpaw.browser"
NATIVE_HOST_REGISTRY_KEY = (
    "Software\\Google\\Chrome\\NativeMessagingHosts\\com.qwenpaw.browser"
)
# EXTENSION_ID is Chrome's deterministic derivation of the manifest "key":
# base64-decode the public key (SubjectPublicKeyInfo DER), sha256 it, take the
# first 32 hex chars, map 0-f to a-p. Pinning "key" keeps the unpacked-mode id
# stable so it matches the Native Messaging allowed_origins. Regenerate via:
#   openssl genrsa 2048 | openssl pkcs8 -topk8 -nocrypt -out key.pem
#   openssl rsa -in key.pem -pubout -outform DER | openssl base64 -A
# Keep key.pem secret and never commit it; only the public "key" ships.
EXTENSION_ID = "nflcgkfjgoiipklkpenmbiificbakoch"
# NOTE: The Chrome Web Store assigns the real id at listing time; this
# placeholder is unused while CWS installation remains unavailable.
CWS_EXTENSION_ID = EXTENSION_ID
CWS_URL = (
    "https://chromewebstore.google.com/detail/"
    f"qwenpaw-chrome/{CWS_EXTENSION_ID}"
)
CWS_COMING_SOON_MESSAGE = (
    "cws install mode is coming soon and not supported in this "
    "Developer Preview"
)
DEFAULT_WS_URL = "ws://127.0.0.1:8088/api/ws/chrome"
CHROME_EXTENSIONS_URL = "chrome://extensions"
LOCAL_BRIDGE_CONFIG_JS = "bridge_config.js"
LOCAL_INITIAL_RECONNECT_BACKOFF_SECONDS = 5
LOCAL_MAX_RECONNECT_BACKOFF_SECONDS = 60
INSTALL_MODE_STATE_FILENAME = "chrome-extension-install.json"
WINDOWS_MAINTENANCE_BACKUP_SUFFIX = ".qwenpaw-maintenance"
WINDOWS_MAINTENANCE_STUB_MARKER = "QWENPAW_INSTALL_MAINTENANCE"
NATIVE_HOST_REPAIR_INSTRUCTION = (
    "Re-run Setup from the Chrome plugin detail page, then reload the Chrome "
    "extension."
)


def native_manifest_path(
    home: Path,
    *,
    platform: str | None = None,
) -> Path:
    platform = platform or sys.platform
    if platform == "darwin":
        return (
            home
            / "Library"
            / "Application Support"
            / "Google"
            / "Chrome"
            / "NativeMessagingHosts"
            / f"{NATIVE_HOST_NAME}.json"
        )
    if platform == "win32":
        return home / ".qwenpaw" / f"{NATIVE_HOST_NAME}.json"
    return (
        home
        / ".config"
        / "google-chrome"
        / "NativeMessagingHosts"
        / f"{NATIVE_HOST_NAME}.json"
    )


def _plugin_root() -> Path:
    return Path(__file__).resolve().parent


def _repo_root() -> Path:
    """Return the source checkout root when this module runs from a repo."""
    return _plugin_root().parents[2]


def _packaged_build_fingerprint() -> dict[str, str | None]:
    """Read build data materialized into packaged Native Messaging assets."""
    try:
        from .assets.scripts.build_fingerprint import BUILD_FINGERPRINT
    except ImportError:
        return {"commit": "unknown", "builtAt": None}
    commit = str(BUILD_FINGERPRINT.get("commit") or "unknown")
    built_at = BUILD_FINGERPRINT.get("builtAt")
    return {
        "commit": commit,
        "builtAt": str(built_at) if built_at is not None else None,
    }


def _build_fingerprint() -> dict[str, str | None]:
    """Return the checkout build identity, degrading outside a git worktree."""
    try:
        commit = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=_repo_root(),
            capture_output=True,
            check=True,
            text=True,
        ).stdout.strip()
        built_at = subprocess.run(
            ["git", "show", "-s", "--format=%cI", "HEAD"],
            cwd=_repo_root(),
            capture_output=True,
            check=True,
            text=True,
        ).stdout.strip()
        if commit and built_at:
            return {"commit": commit, "builtAt": built_at}
    except (OSError, subprocess.CalledProcessError):
        pass
    return _packaged_build_fingerprint()


def _first_existing_path(candidates: list[Path], label: str) -> Path:
    for candidate in candidates:
        if candidate.exists():
            return candidate
    joined = ", ".join(str(path) for path in candidates)
    raise FileNotFoundError(f"{label} not found. Checked: {joined}")


def _extension_source_dir() -> Path:
    plugin_root = _plugin_root()
    return _first_existing_path(
        [
            plugin_root / "assets" / "extensions" / "chrome",
        ],
        "Chrome extension assets",
    )


def _native_host_source_path() -> Path:
    plugin_root = _plugin_root()
    return _first_existing_path(
        [
            plugin_root / "assets" / "scripts" / "nm_host.py",
        ],
        "Native Messaging host script",
    )


def _native_host_support_paths() -> list[Path]:
    source_dir = _native_host_source_path().parent
    return [
        source_dir / name
        for name in (
            "build_fingerprint.py",
            "handshake.py",
            "protocol_mirror.py",
        )
        if (source_dir / name).exists()
    ]


def _qwenpaw_home(home: Path) -> Path:
    return home / ".qwenpaw"


def _resolve_host_interpreter() -> str:
    """Return the Python runtime that can execute the Native Messaging host."""
    bundled_runtime = os.environ.get("QWENPAW_DESKTOP_PY_RUNTIME", "")
    if bundled_runtime and Path(bundled_runtime).is_file():
        return bundled_runtime
    if not getattr(sys, "frozen", False) and not os.environ.get(
        "QWENPAW_DESKTOP_APP",
    ):
        return sys.executable
    raise RuntimeError(
        "QWENPAW_DESKTOP_PY_RUNTIME is missing or invalid; reinstall the "
        "QwenPaw desktop app.",
    )


def _windows_batch_path_literal(value: str) -> str:
    """Return a cmd.exe-safe literal path for a generated batch file."""
    normalized = value
    if value.upper().startswith("\\\\?\\UNC\\"):
        normalized = "\\\\" + value[len("\\\\?\\UNC\\") :]
    elif value.startswith("\\\\?\\"):
        normalized = value[len("\\\\?\\") :]
    return normalized.replace("%", "%%")


def native_host_launcher_path(
    qwenpaw_home: Path,
    *,
    platform: str | None = None,
) -> Path:
    """Return the Native Messaging launcher path for a platform."""
    name = NM_HOST_BASENAME
    if (platform or sys.platform) == "win32":
        name += NM_HOST_WIN_SUFFIX
    return qwenpaw_home / "bin" / name


def recover_windows_native_host_launcher(
    *,
    home: Path | None = None,
    platform: str | None = None,
) -> bool:
    """Recover a launcher left gated by an interrupted Windows installer."""
    platform = platform or sys.platform
    if platform != "win32":
        return False

    qwenpaw_home = _qwenpaw_home(home or Path.home())
    launcher = native_host_launcher_path(qwenpaw_home, platform=platform)
    backup = launcher.with_name(
        launcher.name + WINDOWS_MAINTENANCE_BACKUP_SUFFIX,
    )
    if not backup.is_file():
        return False

    is_gate = False
    if launcher.is_file():
        try:
            is_gate = (
                WINDOWS_MAINTENANCE_STUB_MARKER.encode("ascii")
                in launcher.read_bytes()
            )
        except OSError:
            return False
    if launcher.exists() and not is_gate:
        backup.unlink()
        return False

    launcher.unlink(missing_ok=True)
    backup.replace(launcher)
    return True


class _NoopNativeHostRegistry:
    def set_value(self, key_path: str, value: str) -> None:
        del key_path, value

    def get_value(self, key_path: str) -> str | None:
        del key_path

    def delete_value(self, key_path: str) -> None:
        del key_path


class _WindowsNativeHostRegistry:
    def set_value(self, key_path: str, value: str) -> None:
        import winreg

        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, key_path) as key:
            winreg.SetValueEx(key, None, 0, winreg.REG_SZ, value)

    def get_value(self, key_path: str) -> str | None:
        import winreg

        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path) as key:
                value, _ = winreg.QueryValueEx(key, None)
        except FileNotFoundError:
            return None
        return str(value)

    def delete_value(self, key_path: str) -> None:
        import winreg

        try:
            winreg.DeleteKey(winreg.HKEY_CURRENT_USER, key_path)
        except FileNotFoundError:
            pass


def _native_host_registry(platform: str, registry: object | None) -> object:
    if platform != "win32":
        return _NoopNativeHostRegistry()
    return registry if registry is not None else _WindowsNativeHostRegistry()


def resolve_default_ws_url() -> str:
    """Resolve the bridge WebSocket URL for the currently running API."""
    return require_bridge_endpoint()


class BridgeEndpointUnavailable(RuntimeError):
    """Raised when the local API bind cannot safely host the bridge token."""


class InstallModeError(ValueError):
    """Raised when the requested extension install mode cannot be used."""


def require_bridge_endpoint() -> str:
    """Derive a loopback-only bridge endpoint from the running server bind."""
    try:
        api_info = read_last_api()
    except Exception:
        api_info = None

    if not api_info:
        return DEFAULT_WS_URL

    host, port = api_info
    host = "127.0.0.1" if host in {"", "0.0.0.0"} else str(host)
    raw_host = (
        host[1:-1] if host.startswith("[") and host.endswith("]") else host
    )
    if raw_host != "localhost":
        try:
            is_loopback = ip_address(raw_host).is_loopback
        except ValueError:
            is_loopback = False
        if not is_loopback:
            raise BridgeEndpointUnavailable(
                "Chrome Native Messaging requires QwenPaw to bind to a "
                "loopback address (127.0.0.1, ::1, or localhost).",
            )
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    return f"ws://{host}:{port}/api/ws/chrome"


def _copy_extension(qwenpaw_home: Path) -> Path:
    source = _extension_source_dir()
    target = qwenpaw_home / "chrome-extension" / "qwenpaw-chrome"
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source, target, dirs_exist_ok=True)
    return target


def _write_local_extension_config(
    extension_dir: Path,
    build: dict[str, str | None] | None = None,
) -> Path:
    config_path = extension_dir / LOCAL_BRIDGE_CONFIG_JS
    config = {
        "initialReconnectBackoffSeconds": (
            LOCAL_INITIAL_RECONNECT_BACKOFF_SECONDS
        ),
        "maxReconnectBackoffSeconds": LOCAL_MAX_RECONNECT_BACKOFF_SECONDS,
        "localPort": int(
            resolve_default_ws_url().rsplit(":", 1)[1].split("/")[0],
        ),
        "build": build or _build_fingerprint(),
    }
    config_path.write_text(
        "globalThis.QWENPAW_BRIDGE_CONFIG = "
        f"{json.dumps(config, separators=(',', ':'))};\n",
        encoding="utf-8",
    )
    return config_path


def atomic_write_json_0600(path: Path, data: dict[str, object]) -> Path:
    """Atomically persist bridge secrets with owner-only permissions."""
    write_json_atomic(path, data, new_file_mode=0o600)
    return path


def _write_nm_config(qwenpaw_home: Path, token: str, ws_url: str) -> Path:
    config_path = qwenpaw_home / "nm-bridge.json"
    return atomic_write_json_0600(
        config_path,
        {"ws_url": ws_url, "token": token},
    )


def _install_mode_state_path(qwenpaw_home: Path) -> Path:
    return qwenpaw_home / INSTALL_MODE_STATE_FILENAME


def _write_install_mode_state(
    qwenpaw_home: Path,
    install_mode: str,
    native_host_probe: dict[str, object] | None = None,
) -> Path:
    state_path = _install_mode_state_path(qwenpaw_home)
    state: dict[str, object] = {"install_mode": install_mode}
    if native_host_probe is not None:
        state["native_host_probe"] = native_host_probe
    return atomic_write_json_0600(state_path, state)


def _read_install_mode_state_data(
    qwenpaw_home: Path,
) -> dict[str, object] | None:
    try:
        state = json.loads(
            _install_mode_state_path(qwenpaw_home).read_text(
                encoding="utf-8",
            ),
        )
    except (OSError, json.JSONDecodeError):
        return None
    return state if isinstance(state, dict) else None


def _read_install_mode_state(qwenpaw_home: Path) -> str | None:
    state = _read_install_mode_state_data(qwenpaw_home)
    install_mode = state.get("install_mode") if state is not None else None
    return install_mode if install_mode in {"unpacked", "cws"} else None


def _check_native_host_runtime(
    launcher: Path,
    *,
    timeout: float = 5.0,
) -> dict[str, str | bool] | None:
    """Return a probe failure when the host runtime is unusable."""
    try:
        runtime_check = subprocess.run(
            [str(launcher), "--check-runtime"],
            capture_output=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        return {"ok": False, "stage": "timeout", "detail": str(exc)}
    except OSError as exc:
        return {"ok": False, "stage": "launch", "detail": str(exc)}
    if runtime_check.returncode != 0:
        detail = runtime_check.stderr.decode("utf-8", "replace").strip()
        return {
            "ok": False,
            "stage": "runtime",
            "detail": detail or f"exit code {runtime_check.returncode}",
        }
    return None


def _probe_native_host(
    launcher: Path,
    *,
    timeout: float = 5.0,
) -> dict[str, str | bool]:
    """Validate the host runtime, then verify an unmodified NM frame."""
    runtime_failure = _check_native_host_runtime(launcher, timeout=timeout)
    if runtime_failure is not None:
        return runtime_failure

    payload = {"probe": "qwenpaw"}
    raw_payload = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    frame = struct.pack("<I", len(raw_payload)) + raw_payload
    try:
        completed = subprocess.run(
            [str(launcher), "--probe"],
            input=frame,
            capture_output=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        return {"ok": False, "stage": "timeout", "detail": str(exc)}
    except OSError as exc:
        return {"ok": False, "stage": "launch", "detail": str(exc)}
    if completed.returncode != 0:
        detail = completed.stderr.decode("utf-8", "replace").strip()
        return {
            "ok": False,
            "stage": "launch",
            "detail": detail or f"exit code {completed.returncode}",
        }
    if completed.stdout != frame:
        return {
            "ok": False,
            "stage": "framing",
            "detail": "Native Messaging probe frame did not round-trip",
        }
    return {"ok": True, "stage": "", "detail": ""}


def _native_host_repair_instruction(probe: dict[str, object]) -> str:
    """Return a bounded, actionable repair message for a failed probe."""
    stage = str(probe.get("stage") or "unknown")
    prefix = f"Native host self-check failed during {stage}."
    if stage == "runtime":
        detail = " ".join(str(probe.get("detail") or "").split())[:500]
        if detail:
            prefix = f"{prefix} {detail}"
    return f"{prefix} {NATIVE_HOST_REPAIR_INSTRUCTION}"


def _read_existing_nm_token(qwenpaw_home: Path) -> str | None:
    config_path = qwenpaw_home / "nm-bridge.json"
    if not config_path.exists():
        return None
    try:
        raw = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    token = str(raw.get("token") or "").strip()
    return token or None


def _write_host(
    qwenpaw_home: Path,
    *,
    platform: str | None = None,
    build: dict[str, str | None] | None = None,
) -> Path:
    platform = platform or sys.platform
    bin_dir = qwenpaw_home / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    host_impl = bin_dir / "qwenpaw-nm-host.py"
    shutil.copy2(_native_host_source_path(), host_impl)
    if platform != "win32":
        host_impl.chmod(0o755)
    for support_path in _native_host_support_paths():
        shutil.copy2(support_path, bin_dir / support_path.name)
    (bin_dir / "build_fingerprint.py").write_text(
        "# -*- coding: utf-8 -*-\n"
        '"""Build fingerprint materialized at installation time."""\n\n'
        f"BUILD_FINGERPRINT = {repr(build or _build_fingerprint())}\n",
        encoding="utf-8",
    )

    host = native_host_launcher_path(qwenpaw_home, platform=platform)
    interpreter = _resolve_host_interpreter()
    if platform == "win32":
        interpreter = _windows_batch_path_literal(interpreter)
        host_impl_literal = _windows_batch_path_literal(str(host_impl))
        # cmd.exe reads batch files through the current OEM code page. This
        # ASCII-only line switches decoding to UTF-8 before paths are read.
        host.write_text(
            "@echo off\n"
            "chcp 65001 >nul\n"
            f'"{interpreter}" "{host_impl_literal}" %*\n',
            encoding="utf-8",
        )
    else:
        host.write_text(
            "#!/usr/bin/env sh\n" f'exec "{interpreter}" "{host_impl}" "$@"\n',
            encoding="utf-8",
        )
        host.chmod(
            host.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH,
        )
    return host


def _write_native_manifest(
    host_path: Path,
    extension_id: str = EXTENSION_ID,
    *,
    home: Path,
    platform: str | None = None,
) -> Path:
    manifest_path = native_manifest_path(home, platform=platform)
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest = {
        "name": NATIVE_HOST_NAME,
        "description": "QwenPaw Native Messaging host",
        "path": str(host_path),
        "type": "stdio",
        "allowed_origins": [f"chrome-extension://{extension_id}/"],
    }
    return atomic_write_json_0600(manifest_path, manifest)


def _uninstall(
    qwenpaw_home: Path,
    *,
    home: Path,
    platform: str | None = None,
    registry: object | None = None,
) -> None:
    platform = platform or sys.platform
    native_host_registry = _native_host_registry(platform, registry)
    manifest_path = native_manifest_path(home, platform=platform)
    if manifest_path.exists():
        manifest_path.unlink()
    native_host_registry.delete_value(NATIVE_HOST_REGISTRY_KEY)
    config_path = qwenpaw_home / "nm-bridge.json"
    if config_path.exists():
        config_path.unlink()
    install_mode_state_path = _install_mode_state_path(qwenpaw_home)
    if install_mode_state_path.exists():
        install_mode_state_path.unlink()
    host = native_host_launcher_path(qwenpaw_home, platform=platform)
    host_impl = qwenpaw_home / "bin" / "qwenpaw-nm-host.py"
    host_paths = [host, host_impl]
    if platform == "win32":
        host_paths.append(
            host.with_name(
                host.name + WINDOWS_MAINTENANCE_BACKUP_SUFFIX,
            ),
        )
    for path in host_paths:
        if path.exists():
            path.unlink()
    shutil.rmtree(qwenpaw_home / "chrome-extension", ignore_errors=True)


def setup_extension_files(
    *,
    install_mode: str = "unpacked",
    reset: bool = False,
    home: Path | None = None,
    platform: str | None = None,
    registry: object | None = None,
) -> dict[str, str | bool]:
    """Install extension files and Native Messaging registration."""
    if install_mode == "cws":
        raise InstallModeError(CWS_COMING_SOON_MESSAGE)
    if install_mode != "unpacked":
        raise InstallModeError("install_mode must be 'unpacked'")

    home = home or Path.home()
    platform = platform or sys.platform
    native_host_registry = _native_host_registry(platform, registry)
    ws_url = require_bridge_endpoint()
    qwenpaw_home = _qwenpaw_home(home)
    if reset:
        _uninstall(
            qwenpaw_home,
            home=home,
            platform=platform,
            registry=native_host_registry,
        )

    token = None if reset else _read_existing_nm_token(qwenpaw_home)
    token = token or secrets.token_urlsafe(32)
    build = _build_fingerprint()
    extension_dir = None
    if install_mode == "unpacked":
        extension_dir = _copy_extension(qwenpaw_home)
        _write_local_extension_config(extension_dir, build)
    config_path = _write_nm_config(qwenpaw_home, token, ws_url)
    host_path = _write_host(qwenpaw_home, platform=platform, build=build)
    manifest_path = _write_native_manifest(
        host_path,
        home=home,
        platform=platform,
    )
    native_host_registry.set_value(
        NATIVE_HOST_REGISTRY_KEY,
        str(manifest_path),
    )
    native_host_probe = _probe_native_host(host_path)
    _write_install_mode_state(qwenpaw_home, install_mode, native_host_probe)
    result: dict[str, str | bool] = {
        "installed": bool(native_host_probe["ok"]),
        "install_mode": install_mode,
        "extension_id": EXTENSION_ID,
        "extension_dir": (
            str(extension_dir) if extension_dir is not None else ""
        ),
        "native_manifest_path": str(manifest_path),
        "native_host_path": str(host_path),
        "config_path": str(config_path),
        "manifest_configured": True,
        "native_host_repair_required": not native_host_probe["ok"],
        "native_host_repair_instruction": (
            _native_host_repair_instruction(native_host_probe)
            if not native_host_probe["ok"]
            else ""
        ),
        "ws_url": ws_url,
        "chrome_extensions_url": CHROME_EXTENSIONS_URL,
    }
    return result


def extension_install_status(
    *,
    home: Path | None = None,
    platform: str | None = None,
    registry: object | None = None,
) -> dict[str, str | bool | None]:
    """Return install paths and whether the local registration exists."""
    home = home or Path.home()
    platform = platform or sys.platform
    native_host_registry = _native_host_registry(platform, registry)
    qwenpaw_home = _qwenpaw_home(home)
    extension_dir = qwenpaw_home / "chrome-extension" / "qwenpaw-chrome"
    manifest_path = native_manifest_path(home, platform=platform)
    host_path = native_host_launcher_path(qwenpaw_home, platform=platform)
    config_path = qwenpaw_home / "nm-bridge.json"
    manifest_configured = False
    repair_required = False
    ws_url = None
    if config_path.exists():
        try:
            config = json.loads(config_path.read_text(encoding="utf-8"))
            ws_url = config.get("ws_url")
            manifest_configured = bool(ws_url and config.get("token"))
        except (OSError, json.JSONDecodeError):
            ws_url = None
    if platform == "win32":
        registered_manifest = native_host_registry.get_value(
            NATIVE_HOST_REGISTRY_KEY,
        )
        try:
            registry_manifest_readable = (
                bool(registered_manifest)
                and Path(
                    str(registered_manifest),
                ).is_file()
            )
            if registry_manifest_readable:
                Path(str(registered_manifest)).read_bytes()
        except OSError:
            registry_manifest_readable = False
        native_host_configured = (
            registry_manifest_readable and host_path.exists()
        )
    else:
        native_host_configured = (
            manifest_path.exists()
            and host_path.exists()
            and config_path.exists()
            and manifest_configured
        )
    unpacked_installed = (extension_dir / "manifest.json").exists() and (
        native_host_configured
    )
    install_state = _read_install_mode_state_data(qwenpaw_home)
    install_mode = _read_install_mode_state(qwenpaw_home)
    cws_installed = native_host_configured and (
        install_mode == "cws"
        or (install_mode is None and not unpacked_installed)
    )
    if install_mode == "unpacked":
        cws_installed = False
    installed = unpacked_installed or cws_installed
    probe = (
        install_state.get("native_host_probe")
        if install_state is not None
        else None
    )
    if isinstance(probe, dict) and probe.get("ok") is False:
        repair_required = True
        repair_instruction = _native_host_repair_instruction(probe)
    else:
        repair_instruction = ""
    return {
        "installed": installed,
        "install_mode": (
            "cws"
            if cws_installed
            else "unpacked"
            if unpacked_installed
            else None
        ),
        "extension_id": EXTENSION_ID,
        "extension_dir": str(extension_dir),
        "native_manifest_path": str(manifest_path),
        "native_host_path": str(host_path),
        "config_path": str(config_path),
        "manifest_configured": manifest_configured,
        "native_host_repair_required": repair_required,
        "native_host_repair_instruction": repair_instruction,
        "legacy_config_path": "",
        # This is the endpoint actually persisted for the Native Messaging
        # host.  Do not replace a missing value with the current server bind:
        # callers use the distinction to detect an incomplete or stale setup.
        "ws_url": ws_url,
        "chrome_extensions_url": CHROME_EXTENSIONS_URL,
    }


def open_extension_folder(
    extension_dir: Path | None = None,
    *,
    platform: str | None = None,
    home: Path | None = None,
) -> dict[str, str | bool | None]:
    """Open the local unpacked extension folder with a native file manager."""
    home = home or Path.home()
    platform = platform or sys.platform
    target = extension_dir or (
        _qwenpaw_home(home) / "chrome-extension" / "qwenpaw-chrome"
    )
    target = target.expanduser()

    if not target.exists():
        return {
            "opened": False,
            "path": str(target),
            "error": "Extension folder does not exist yet.",
        }

    if platform == "darwin":
        commands = [["open", str(target)]]
    elif platform == "win32":
        commands = [["explorer", str(target)]]
    else:
        commands = [["xdg-open", str(target)]]

    for command in commands:
        try:
            subprocess.Popen(  # pylint: disable=consider-using-with
                command,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            return {"opened": True, "path": str(target), "error": None}
        except OSError as exc:
            last_error = str(exc)

    return {"opened": False, "path": str(target), "error": last_error}


def _find_windows_chrome_executable() -> Path | None:
    """Return a registered or standard-install Google Chrome executable."""
    candidates: list[Path] = []
    try:
        import winreg
    except ImportError:
        winreg = None

    if winreg is not None:
        app_paths_key = (
            r"Software\Microsoft\Windows\CurrentVersion\App Paths\chrome.exe"
        )
        for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
            try:
                with winreg.OpenKey(hive, app_paths_key) as key:
                    value, _ = winreg.QueryValueEx(key, "")
            except OSError:
                continue
            candidate = str(value).strip().strip('"')
            if candidate:
                candidates.append(Path(candidate))

    for env_name in ("LOCALAPPDATA", "ProgramFiles", "ProgramFiles(x86)"):
        root = os.environ.get(env_name)
        if root:
            candidates.append(
                Path(root)
                / "Google"
                / "Chrome"
                / "Application"
                / "chrome.exe",
            )

    seen: set[str] = set()
    for candidate in candidates:
        key = os.path.normcase(str(candidate))
        if key in seen:
            continue
        seen.add(key)
        if candidate.is_file():
            return candidate
    return None


def open_chrome_extensions_page(
    *,
    platform: str | None = None,
) -> dict[str, str | bool]:
    """Open Chrome's extension manager through a fixed local action."""
    platform = platform or sys.platform
    commands: list[list[str]] = []

    if platform == "darwin":
        commands.append(["open", "-a", "Google Chrome", CHROME_EXTENSIONS_URL])
    elif platform == "win32":
        chrome_executable = _find_windows_chrome_executable()
        if chrome_executable is None:
            return {
                "opened": False,
                "url": CHROME_EXTENSIONS_URL,
                "error": "Google Chrome executable was not found.",
            }
        try:
            subprocess.Popen(  # pylint: disable=consider-using-with
                [str(chrome_executable), CHROME_EXTENSIONS_URL],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except OSError as exc:
            return {
                "opened": False,
                "url": CHROME_EXTENSIONS_URL,
                "error": f"Could not start Google Chrome: {exc}",
            }
        return {"opened": True, "url": CHROME_EXTENSIONS_URL}
    else:
        commands.extend(
            [
                [browser, CHROME_EXTENSIONS_URL]
                for browser in (
                    "google-chrome",
                    "google-chrome-stable",
                    "chromium",
                    "chromium-browser",
                )
            ],
        )

    for command in commands:
        try:
            subprocess.Popen(  # pylint: disable=consider-using-with
                command,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            return {"opened": True, "url": CHROME_EXTENSIONS_URL}
        except OSError:
            continue

    try:
        opened = webbrowser.open(CHROME_EXTENSIONS_URL)
    except Exception as exc:  # pragma: no cover - defensive OS fallback
        return {
            "opened": False,
            "url": CHROME_EXTENSIONS_URL,
            "error": str(exc),
        }
    return {"opened": bool(opened), "url": CHROME_EXTENSIONS_URL}
