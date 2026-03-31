# -*- coding: utf-8 -*-
"""Helpers for collecting normalized system hardware information."""

from __future__ import annotations

import ctypes
import os
import platform
import re
import subprocess
from typing import Any

_BYTES_PER_GB = float(1024**3)
_CUDA_VERSION_PATTERNS = (
    re.compile(r"CUDA Version:\s*([0-9]+(?:\.[0-9]+)?)", re.IGNORECASE),
    re.compile(r"release\s+([0-9]+(?:\.[0-9]+)?)", re.IGNORECASE),
)


def get_os_name() -> str:
    """Return the current operating system as windows/macos/linux."""
    system = platform.system().lower()
    mapping = {
        "windows": "windows",
        "darwin": "macos",
        "linux": "linux",
    }
    return mapping.get(system, system)


def get_architecture() -> str:
    """Return the CPU architecture as x64/arm64 when recognized."""
    machine = platform.machine().lower()
    mapping = {
        "x86_64": "x64",
        "amd64": "x64",
        "arm64": "arm64",
        "aarch64": "arm64",
    }
    return mapping.get(machine, machine)


def get_macos_version() -> tuple[int, ...] | None:
    """Return the full macOS version as a tuple, or None when unavailable."""
    if get_os_name() != "macos":
        return None

    version = platform.mac_ver()[0].strip()
    if not version:
        version = (_run_command(["sw_vers", "-productVersion"]) or "").strip()
    if not version:
        return None

    parts = tuple(int(part) for part in version.split(".") if part.isdigit())
    if not parts:
        return None
    return parts


def get_cuda_version() -> str | None:
    """Return the detected CUDA version, or None if CUDA is unavailable."""
    for command in (["nvidia-smi"], ["nvcc", "--version"]):
        output = _run_command(command)
        if not output:
            continue
        for pattern in _CUDA_VERSION_PATTERNS:
            match = pattern.search(output)
            if match:
                return match.group(1)
    return None


def get_memory_size_gb() -> float:
    """Return total system memory in GB."""
    memory_bytes = _get_total_memory_bytes()
    if memory_bytes <= 0:
        return 0.0
    return round(memory_bytes / _BYTES_PER_GB, 2)


def get_vram_size_gb() -> float:
    """Return the largest CUDA GPU memory size in GB, or 0 when absent."""
    if get_cuda_version() is None:
        return 0.0

    output = _run_command(
        [
            "nvidia-smi",
            "--query-gpu=memory.total",
            "--format=csv,noheader,nounits",
        ],
    )
    if not output:
        return 0.0

    best_memory_mb = 0.0
    for line in output.splitlines():
        value = line.strip()
        if not value:
            continue
        try:
            best_memory_mb = max(best_memory_mb, float(value))
        except ValueError:
            continue

    if best_memory_mb <= 0:
        return 0.0
    return round(best_memory_mb / 1024.0, 2)


def get_system_info() -> dict[str, Any]:
    """Return normalized system information used by local model features."""
    cuda_version = get_cuda_version()
    return {
        "os": get_os_name(),
        "arch": get_architecture(),
        "cuda_version": cuda_version,
        "memory_gb": get_memory_size_gb(),
        "vram_gb": get_vram_size_gb() if cuda_version else 0.0,
    }


def _run_command(args: list[str], timeout: int = 5) -> str | None:
    try:
        result = subprocess.run(
            args,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None

    output = ((result.stdout or "") + "\n" + (result.stderr or "")).strip()
    if not output and result.returncode != 0:
        return None
    return output or None


def _get_total_memory_bytes() -> int:
    memory_bytes = _get_total_memory_bytes_from_sysconf()
    if memory_bytes:
        return memory_bytes

    if get_os_name() == "macos":
        memory_bytes = _get_total_memory_bytes_from_sysctl()
        if memory_bytes:
            return memory_bytes

    if get_os_name() == "linux":
        memory_bytes = _get_total_memory_bytes_from_proc_meminfo()
        if memory_bytes:
            return memory_bytes

    if get_os_name() == "windows":
        memory_bytes = _get_total_memory_bytes_from_windows_api()
        if memory_bytes:
            return memory_bytes

    return 0


def _get_total_memory_bytes_from_sysconf() -> int:
    if not hasattr(os, "sysconf"):
        return 0

    try:
        page_size = os.sysconf("SC_PAGE_SIZE")
        phys_pages = os.sysconf("SC_PHYS_PAGES")
    except (OSError, ValueError):
        return 0

    if not isinstance(page_size, int) or not isinstance(phys_pages, int):
        return 0
    if page_size <= 0 or phys_pages <= 0:
        return 0
    return page_size * phys_pages


def _get_total_memory_bytes_from_sysctl() -> int:
    output = _run_command(["sysctl", "-n", "hw.memsize"])
    if not output:
        return 0
    try:
        return int(output.strip())
    except ValueError:
        return 0


def _get_total_memory_bytes_from_proc_meminfo() -> int:
    try:
        with open("/proc/meminfo", encoding="utf-8") as handle:
            for line in handle:
                if not line.startswith("MemTotal:"):
                    continue
                parts = line.split()
                if len(parts) < 2:
                    return 0
                return int(parts[1]) * 1024
    except (OSError, ValueError):
        return 0
    return 0


def _get_total_memory_bytes_from_windows_api() -> int:
    class _MemoryStatus(ctypes.Structure):
        _fields_ = [
            ("dwLength", ctypes.c_ulong),
            ("dwMemoryLoad", ctypes.c_ulong),
            ("ullTotalPhys", ctypes.c_ulonglong),
            ("ullAvailPhys", ctypes.c_ulonglong),
            ("ullTotalPageFile", ctypes.c_ulonglong),
            ("ullAvailPageFile", ctypes.c_ulonglong),
            ("ullTotalVirtual", ctypes.c_ulonglong),
            ("ullAvailVirtual", ctypes.c_ulonglong),
            ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
        ]

    kernel32 = getattr(getattr(ctypes, "windll", None), "kernel32", None)
    if kernel32 is None:
        return 0

    status = _MemoryStatus(ctypes.sizeof(_MemoryStatus))
    if not kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
        return 0
    return int(status.ullTotalPhys)
