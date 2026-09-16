# -*- coding: utf-8 -*-
"""Telemetry collection for installation analytics."""

from __future__ import annotations

import json
import logging
import platform
import subprocess
import sys
import time
import uuid
from contextlib import contextmanager
from collections.abc import Iterator
from pathlib import Path
from typing import Any, Callable

from ..__version__ import __version__ as QWENPAW_VERSION
from ..constant import EnvVarLoader
from .io_utils import get_sync_path_lock, write_json_atomic

logger = logging.getLogger(__name__)

TELEMETRY_ENDPOINT = (
    "https://qwenpawelemetry-sukzkbfzhc.ap-southeast-1.fcapp.run"
)
TELEMETRY_MARKER_FILE = ".telemetry_collected"


def _safe_get(func: Callable[[], str], default: str = "unknown") -> str:
    """Safely get value from function, return default on error."""
    try:
        return func()
    except Exception:
        return default


def _detect_install_method() -> str:
    """Detect how QwenPaw was installed based on environment signals."""
    if EnvVarLoader.get_bool("QWENPAW_RUNNING_IN_CONTAINER"):
        return "docker"
    if EnvVarLoader.get_bool("QWENPAW_DESKTOP_APP"):
        return "desktop"
    return "pip"


def get_system_info() -> dict[str, Any]:
    """Collect system environment information.

    Returns anonymized system information including:
    - install_id: Random UUID (not tied to user)
    - qwenpaw_version: QwenPaw version string
    - install_method: How QwenPaw was installed (docker/desktop/pip)
    - os: Operating system (Windows/Darwin/Linux)
    - os_version: OS version string
    - python_version: Python version running qwenpaw (major.minor)
    - architecture: CPU architecture (x86_64/arm64/etc)
    - has_gpu: GPU availability detection
    """
    return {"install_id": str(uuid.uuid4()), **get_environment_info()}


def get_environment_info() -> dict[str, Any]:
    """Collect the Runtime environment without generating an identity."""
    info = {
        "qwenpaw_version": _safe_get(lambda: QWENPAW_VERSION, "unknown"),
        "install_method": _safe_get(_detect_install_method, "unknown"),
        "os": _safe_get(platform.system, "unknown"),
        "os_version": _safe_get(platform.release, "unknown"),
        "python_version": (
            f"{sys.version_info.major}." f"{sys.version_info.minor}"
        ),
        "architecture": _safe_get(platform.machine, "unknown"),
        "has_gpu": _detect_gpu(),
    }
    return info


def _detect_gpu() -> bool | str:
    """Detect GPU availability without additional dependencies.

    Returns:
        True if any GPU is detected, False otherwise, or "unknown" on error.
    """
    try:
        os_type = _safe_get(platform.system, "")
        arch = _safe_get(platform.machine, "")

        # Check NVIDIA GPU via nvidia-smi (works on Linux/macOS/Windows)
        try:
            result = subprocess.run(
                ["nvidia-smi"],
                capture_output=True,
                timeout=3,
                check=False,
            )
            if result.returncode == 0:
                return True
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pass

        # Check Apple Silicon (has integrated GPU)
        if os_type == "Darwin" and arch == "arm64":
            return True

        # Check AMD/NVIDIA GPU on Linux via lspci
        if os_type == "Linux":
            try:
                result = subprocess.run(
                    ["lspci"],
                    capture_output=True,
                    text=True,
                    timeout=3,
                    check=False,
                )
                if result.returncode == 0:
                    output = str(result.stdout).upper()
                    gpu_vendors = ("AMD", "NVIDIA", "INTEL")
                    gpu_types = ("VGA", "GPU", "3D")
                    has_vendor = any(
                        vendor in output for vendor in gpu_vendors
                    )
                    has_type = any(
                        gpu_type in output for gpu_type in gpu_types
                    )
                    if has_vendor and has_type:
                        return True
            except (FileNotFoundError, subprocess.TimeoutExpired):
                pass

        # Check GPU on Windows via wmic (works for AMD/NVIDIA/Intel)
        if os_type == "Windows":
            try:
                result = subprocess.run(
                    ["wmic", "path", "win32_VideoController", "get", "name"],
                    capture_output=True,
                    text=True,
                    timeout=3,
                    check=False,
                )
                if result.returncode == 0:
                    output = str(result.stdout).upper()
                    # Check for dedicated GPU indicators
                    if any(
                        keyword in output
                        for keyword in [
                            "NVIDIA",
                            "AMD",
                            "RADEON",
                            "GEFORCE",
                            "RTX",
                            "GTX",
                        ]
                    ):
                        return True
            except (FileNotFoundError, subprocess.TimeoutExpired):
                pass

        return False
    except Exception:
        return "unknown"


def _upload_telemetry_sync(data: dict[str, Any]) -> bool:
    """Upload telemetry data (synchronous).

    Args:
        data: Telemetry data to upload

    Returns:
        True if upload succeeded, False otherwise
    """
    try:
        import httpx

        with httpx.Client(timeout=2.0) as client:
            response = client.post(TELEMETRY_ENDPOINT, json=data)
            return response.status_code in (200, 201, 204)
    except Exception as e:
        # Silent failure - don't break installation
        logger.debug("Telemetry upload failed: %s", e)
        return False


def _get_current_version() -> str:
    """Get the current QwenPaw version string."""
    try:
        from ..__version__ import __version__ as qwenpaw_ver

        return qwenpaw_ver
    except Exception:
        return "unknown"


def has_telemetry_been_collected(working_dir: Path) -> bool:
    """Check if telemetry has already been collected for the current version.

    Re-triggers collection when QwenPaw is upgraded (or downgraded) to a
    version that hasn't been collected before.

    Args:
        working_dir: Path to QwenPaw working directory

    Returns:
        True if already collected for this version, False otherwise
    """
    marker_file = working_dir / TELEMETRY_MARKER_FILE
    if not marker_file.exists():
        return False
    try:
        marker_data = json.loads(marker_file.read_text(encoding="utf-8"))
        current = _get_current_version()
        # v1.2+: list of all collected versions
        collected_versions = marker_data.get("collected_versions", [])
        if collected_versions:
            return current in collected_versions
        # v1.1 compat: single qwenpaw_version field
        return marker_data.get("qwenpaw_version", "") == current
    except Exception:
        return False


def is_telemetry_opted_out(working_dir: Path) -> bool:
    """Check the process setting and saved telemetry opt-out.

    QWENPAW_TELEMETRY_DISABLED disables telemetry for this process without
    persisting the choice. A saved opt-out applies regardless of version.

    Args:
        working_dir: Path to QwenPaw working directory

    Returns:
        True if telemetry is disabled or the user has opted out.
    """
    if EnvVarLoader.get_bool("QWENPAW_TELEMETRY_DISABLED"):
        return True

    marker_file = working_dir / TELEMETRY_MARKER_FILE
    if not marker_file.exists():
        return False
    try:
        marker_data = json.loads(marker_file.read_text(encoding="utf-8"))
        return marker_data.get("opted_out", False) is True
    except Exception:
        return False


@contextmanager
def telemetry_marker(working_dir: Path) -> Iterator[dict[str, Any]]:
    """Update shared telemetry state using the existing lock and writer."""
    path = working_dir / TELEMETRY_MARKER_FILE
    with get_sync_path_lock(path):
        data = (
            json.loads(path.read_text(encoding="utf-8"))
            if path.exists()
            else {}
        )
        before = json.dumps(data)
        yield data
        if json.dumps(data) != before:
            working_dir.mkdir(parents=True, exist_ok=True)
            write_json_atomic(path, data)


def mark_telemetry_collected(
    working_dir: Path,
    *,
    opted_out: bool = False,
) -> None:
    """Save installation consent/version without replacing daily state."""
    current = _get_current_version()
    try:
        with telemetry_marker(working_dir) as data:
            versions = data.get("collected_versions", [])
            if not versions:
                old_version = data.get("qwenpaw_version", "")
                if old_version:
                    versions = [old_version]
            if current not in versions:
                versions.append(current)
            data.update(
                {
                    "collected_at": time.time(),
                    "qwenpaw_version": current,
                    "collected_versions": versions,
                    "opted_out": opted_out or data.get("opted_out", False),
                    "version": current,
                },
            )
    except Exception as e:
        logger.debug("Failed to write telemetry marker: %s", e)


def collect_and_upload_telemetry(working_dir: Path) -> bool:
    """Collect system info and upload telemetry.

    Args:
        working_dir: Path to QwenPaw working directory

    Returns:
        True if upload succeeded, False if disabled or upload failed.
    """
    if is_telemetry_opted_out(working_dir):
        return False

    # Collect system info
    info = get_system_info()

    # Upload (failures are logged internally)
    success = _upload_telemetry_sync(info)

    # Mark as collected regardless of upload success to avoid retry
    mark_telemetry_collected(working_dir)

    return success
