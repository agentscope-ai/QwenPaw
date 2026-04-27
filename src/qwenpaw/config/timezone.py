# -*- coding: utf-8 -*-
"""Detect the system IANA timezone.

Kept in its own module to avoid circular imports between config.py and
utils.py.  Uses only the standard library; always returns a valid string
(falls back to ``"UTC"``).
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Optional
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

logger = logging.getLogger(__name__)

_NON_STANDARD_ALIASES: dict[str, str] = {
    "Asia/Beijing": "Asia/Shanghai",
    "Asia/Calcutta": "Asia/Kolkata",
    "Asia/Saigon": "Asia/Ho_Chi_Minh",
    "Asia/Katmandu": "Asia/Kathmandu",
    "Asia/Rangoon": "Asia/Yangon",
    "Asia/Thimbu": "Asia/Thimphu",
    "Asia/Ujung_Pandang": "Asia/Makassar",
    "Asia/Ulan_Bator": "Asia/Ulaanbaatar",
    "Pacific/Samoa": "Pacific/Pago_Pago",
    "Pacific/Ponape": "Pacific/Pohnpei",
    "Pacific/Truk": "Pacific/Chuuk",
    "Atlantic/Faeroe": "Atlantic/Faroe",
    "Europe/Kiev": "Europe/Kyiv",
    "PRC": "Asia/Shanghai",
}


def _is_iana(name: Optional[str]) -> bool:
    """Return True if *name* looks like an IANA tz id."""
    return bool(name and "/" in name)


def normalize_tz(name: str) -> Optional[str]:
    """Validate and normalize a timezone name.

    Returns a valid IANA name, or ``None`` if *name* cannot be resolved.
    Handles IANA backward-compatible links (via ``ZoneInfo``) as well as
    non-standard names used by certain Linux distributions.
    """
    if not name:
        return None
    # Prefer our alias table first so that deprecated / non-standard
    # names (even those accepted by ZoneInfo backward links) are
    # mapped to canonical modern identifiers.
    alias = _NON_STANDARD_ALIASES.get(name)
    if alias:
        try:
            ZoneInfo(alias)
            return alias
        except (ZoneInfoNotFoundError, KeyError, ValueError):
            pass
    try:
        ZoneInfo(name)
        return name
    except (ZoneInfoNotFoundError, KeyError, ValueError):
        pass
    return None


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
    probes = [_probe_python, _probe_env]
    if os.name == "nt":
        probes.append(_probe_windows_registry)
    else:
        probes += [
            _probe_etc_timezone,
            _probe_localtime_link,
            _probe_sysconfig_clock,
            _probe_timedatectl,
        ]
    for probe in probes:
        raw = probe()
        if raw is not None:
            normalized = normalize_tz(raw)
            if normalized is not None:
                if normalized != raw:
                    logger.info(
                        "Mapped non-standard timezone %r → %r",
                        raw,
                        normalized,
                    )
                return normalized
            logger.debug(
                "Probe returned invalid timezone %r, skipping",
                raw,
            )
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


_WIN_TO_IANA = {
    "China Standard Time": "Asia/Shanghai",
    "Taipei Standard Time": "Asia/Taipei",
    "Tokyo Standard Time": "Asia/Tokyo",
    "Korea Standard Time": "Asia/Seoul",
    "Singapore Standard Time": "Asia/Singapore",
    "India Standard Time": "Asia/Kolkata",
    "Arabian Standard Time": "Asia/Dubai",
    "Russian Standard Time": "Europe/Moscow",
    "W. Europe Standard Time": "Europe/Berlin",
    "Romance Standard Time": "Europe/Paris",
    "GMT Standard Time": "Europe/London",
    "Eastern Standard Time": "America/New_York",
    "Central Standard Time": "America/Chicago",
    "Mountain Standard Time": "America/Denver",
    "Pacific Standard Time": "America/Los_Angeles",
    "US Mountain Standard Time": "America/Phoenix",
    "Atlantic Standard Time": "America/Halifax",
    "Hawaiian Standard Time": "Pacific/Honolulu",
    "AUS Eastern Standard Time": "Australia/Sydney",
    "New Zealand Standard Time": "Pacific/Auckland",
    "Cen. Australia Standard Time": "Australia/Adelaide",
    "E. Africa Standard Time": "Africa/Nairobi",
    "SE Asia Standard Time": "Asia/Bangkok",
    "West Pacific Standard Time": "Pacific/Port_Moresby",
    "SA Eastern Standard Time": "America/Sao_Paulo",
    "UTC": "UTC",
}


def _probe_windows_registry() -> Optional[str]:
    """Read the current timezone from the Windows registry."""
    try:
        import winreg

        reg_path = r"SYSTEM\CurrentControlSet\Control\TimeZoneInformation"
        key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, reg_path)
        try:
            win_tz = winreg.QueryValueEx(key, "TimeZoneKeyName")[0]
        finally:
            winreg.CloseKey(key)
        return _WIN_TO_IANA.get(win_tz)
    except Exception:
        pass
    return None


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
        with open("/etc/sysconfig/clock", encoding="utf-8") as fh:
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
            timeout=1,
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
            timeout=1,
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
