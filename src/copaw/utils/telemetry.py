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
from pathlib import Path
from typing import Any, Callable

logger = logging.getLogger(__name__)

TELEMETRY_ENDPOINT = "https://telemetry.agentscope.io/copaw/install"
TELEMETRY_MARKER_FILE = ".telemetry_collected"


def _safe_get(func: Callable[[], str], default: str = "unknown") -> str:
    """Safely get value from function, return default on error."""
    try:
        return func()
    except Exception:
        return default


def get_system_info() -> dict[str, Any]:
    """Collect system environment information.

    Returns anonymized system information including:
    - install_id: Random UUID (not tied to user)
    - os: Operating system (Windows/Darwin/Linux)
    - os_version: OS version string
    - python_version: Python version running copaw (major.minor)
    - architecture: CPU architecture (x86_64/arm64/etc)
    - has_gpu: GPU availability detection
    """
    info = {
        "install_id": str(uuid.uuid4()),
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

        with httpx.Client(timeout=5.0) as client:
            response = client.post(TELEMETRY_ENDPOINT, json=data)
            return response.status_code in (200, 201, 204)
    except Exception as e:
        # Silent failure - don't break installation
        logger.debug("Telemetry upload failed: %s", e)
        return False


def has_telemetry_been_collected(working_dir: Path) -> bool:
    """Check if telemetry has already been collected for this installation.

    Args:
        working_dir: Path to CoPaw working directory

    Returns:
        True if telemetry was already collected, False otherwise
    """
    marker_file = working_dir / TELEMETRY_MARKER_FILE
    return marker_file.exists()


def mark_telemetry_collected(working_dir: Path) -> None:
    """Mark that telemetry has been collected.

    Creates a marker file with timestamp to prevent duplicate collection.

    Args:
        working_dir: Path to CoPaw working directory
    """
    marker_file = working_dir / TELEMETRY_MARKER_FILE
    try:
        marker_data = {
            "collected_at": time.time(),
            "version": "1.0",
        }
        marker_file.write_text(json.dumps(marker_data), encoding="utf-8")
    except Exception as e:
        logger.debug("Failed to write telemetry marker: %s", e)


def collect_and_upload_telemetry(working_dir: Path) -> bool:
    """Collect system info and upload telemetry.

    Args:
        working_dir: Path to CoPaw working directory

    Returns:
        True if upload succeeded, False otherwise
    """
    # Collect system info
    info = get_system_info()

    # Upload (failures are logged internally)
    success = _upload_telemetry_sync(info)

    # Mark as collected regardless of upload success to avoid retry
    mark_telemetry_collected(working_dir)

    return success
