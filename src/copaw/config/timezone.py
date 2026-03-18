# -*- coding: utf-8 -*-
"""Detect the system IANA timezone.

Kept in its own module to avoid circular imports between config.py and
utils.py.  Uses only the standard library; always returns a valid string
(falls back to ``"UTC"``).
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Optional


def _is_iana(name: Optional[str]) -> bool:
    """Return True if *name* looks like an IANA tz id."""
    return bool(name and "/" in name)


def detect_system_timezone() -> str:
    """Return the IANA timezone name of the host.

    Falls back to ``"UTC"`` when detection fails.  This function
    must *never* raise — any unexpected error is swallowed.
    """
    try:
        return _detect_system_timezone_inner()
    except Exception:
        return "UTC"


def _detect_system_timezone_inner() -> str:  # noqa: R0911
    for probe in (
        _probe_python,
        _probe_env,
        _probe_etc_timezone,
        _probe_localtime_link,
        _probe_sysconfig_clock,
        _probe_timedatectl,
    ):
        result = probe()
        if result is not None:
            return result
    return "UTC"


def _probe_python() -> Optional[str]:
    """Ask the Python runtime for the local IANA name."""
    try:
        name = (
            datetime.now(timezone.utc)
            .astimezone()
            .tzinfo.tzname(None)  # type: ignore[union-attr]
        )
        if _is_iana(name):
            return name
    except Exception:
        pass
    return None


def _probe_env() -> Optional[str]:
    """Check the ``$TZ`` environment variable."""
    tz = os.environ.get("TZ", "")
    return tz if _is_iana(tz) else None


def _probe_etc_timezone() -> Optional[str]:
    """Read ``/etc/timezone`` (Debian / Ubuntu)."""
    try:
        with open("/etc/timezone", encoding="utf-8") as fh:
            name = fh.read().strip()
            if _is_iana(name):
                return name
    except (OSError, ValueError):
        pass
    return None


def _probe_localtime_link() -> Optional[str]:
    """Resolve the ``/etc/localtime`` symlink."""
    try:
        link = os.readlink("/etc/localtime")
        if "zoneinfo/" in link:
            return link.split("zoneinfo/", 1)[1]
    except OSError:
        pass
    return None


def _probe_sysconfig_clock() -> Optional[str]:
    """Parse ``/etc/sysconfig/clock`` (CentOS / RHEL ≤ 6)."""
    try:
        with open(
            "/etc/sysconfig/clock",
            encoding="utf-8",
        ) as fh:
            for raw in fh:
                if raw.strip().startswith("ZONE="):
                    zone = raw.split("=", 1)[1].strip().strip('"').strip("'")
                    if _is_iana(zone):
                        return zone
    except (OSError, ValueError):
        pass
    return None


def _probe_timedatectl() -> Optional[str]:
    """Query ``timedatectl`` (systemd)."""
    import subprocess  # delayed: avoid cost on happy path

    # systemd ≥ 239 — machine-readable output
    try:
        out = subprocess.check_output(
            [
                "timedatectl",
                "show",
                "-p",
                "Timezone",
                "--value",
            ],
            text=True,
            timeout=3,
            stderr=subprocess.DEVNULL,
        ).strip()
        if _is_iana(out):
            return out
    except Exception:
        pass

    # systemd < 239 (e.g. CentOS 7) — parse human output
    try:
        out = subprocess.check_output(
            ["timedatectl", "status"],
            text=True,
            timeout=3,
            stderr=subprocess.DEVNULL,
        )
        for line in out.splitlines():
            if "time zone" in line.lower():
                # "Time zone: Asia/Shanghai (CST, +0800)"
                part = line.split(":", 1)[1]
                part = part.strip().split()[0]
                if _is_iana(part):
                    return part
    except Exception:
        pass
    return None
