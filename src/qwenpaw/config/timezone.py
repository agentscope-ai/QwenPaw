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
    "America/Buenos_Aires": "America/Argentina/Buenos_Aires",
    "America/Godthab": "America/Nuuk",
    "America/Indianapolis": "America/Indiana/Indianapolis",
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


def _is_timezone_name(name: Optional[str]) -> bool:
    """Return True if *name* is a resolvable IANA/alias timezone name.

    Unlike :func:`_is_iana` this also accepts slashless names such as
    ``"UTC"``, which the environment probe must not skip: a process started
    with ``TZ=UTC`` runs on UTC, while the other probes would still report
    the *host* zone and silently disagree with ``datetime.now()``.
    """
    if not name:
        return False
    return normalize_tz(name) is not None


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
    """Return the IANA timezone name the process runs in.

    ``$TZ`` is consulted before the OS-specific probes and, unlike
    :func:`_is_iana`, a slashless name such as ``"UTC"`` is accepted — so a
    container started with ``TZ=UTC`` reports ``"UTC"`` instead of the host
    zone that ``datetime.now()`` no longer follows.  This value is also
    ``Config.user_timezone``'s default, so that default tracks ``$TZ`` too.

    Falls back to ``"UTC"`` when detection fails.  This function
    must *never* raise — any unexpected error is swallowed.  Note that
    ``"UTC"`` is also a legitimate result, so callers that need to tell a
    genuinely-UTC host from a failed lookup should compare the returned
    zone against the process's actual offset (see
    ``qwenpaw.app.chats.utils._process_local_tz``).
    """
    try:
        return _detect_system_timezone_inner()
    except Exception:
        return "UTC"


def _detect_system_timezone_inner() -> str:
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
    return tz if _is_timezone_name(tz) else None


# Windows registry zone names -> IANA ids.
# Generated from CLDR ``windowsZones.xml`` (territory ``001``), covering
# every name under ``SOFTWARE\Microsoft\Windows NT\CurrentVersion\Time Zones``
# on Windows 10/11 (141 names).  The two names CLDR has dropped
# (``Kamchatka`` / ``Mid-Atlantic Standard Time``) are mapped by hand.
# Values keep CLDR's spelling, including backward-compatible links
# (``America/Buenos_Aires``, ``America/Godthab``); ``normalize_tz``
# canonicalises those on the way out.
# A name outside this map makes ``_probe_windows_registry`` return ``None``;
# the caller then keeps the process offset rather than stamping ``+00:00``.
_WIN_TO_IANA = {
    "AUS Central Standard Time": "Australia/Darwin",
    "AUS Eastern Standard Time": "Australia/Sydney",
    "Afghanistan Standard Time": "Asia/Kabul",
    "Alaskan Standard Time": "America/Anchorage",
    "Aleutian Standard Time": "America/Adak",
    "Altai Standard Time": "Asia/Barnaul",
    "Arab Standard Time": "Asia/Riyadh",
    "Arabian Standard Time": "Asia/Dubai",
    "Arabic Standard Time": "Asia/Baghdad",
    "Argentina Standard Time": "America/Buenos_Aires",
    "Astrakhan Standard Time": "Europe/Astrakhan",
    "Atlantic Standard Time": "America/Halifax",
    "Aus Central W. Standard Time": "Australia/Eucla",
    "Azerbaijan Standard Time": "Asia/Baku",
    "Azores Standard Time": "Atlantic/Azores",
    "Bahia Standard Time": "America/Bahia",
    "Bangladesh Standard Time": "Asia/Dhaka",
    "Belarus Standard Time": "Europe/Minsk",
    "Bougainville Standard Time": "Pacific/Bougainville",
    "Canada Central Standard Time": "America/Regina",
    "Cape Verde Standard Time": "Atlantic/Cape_Verde",
    "Caucasus Standard Time": "Asia/Yerevan",
    "Cen. Australia Standard Time": "Australia/Adelaide",
    "Central America Standard Time": "America/Guatemala",
    "Central Asia Standard Time": "Asia/Bishkek",
    "Central Brazilian Standard Time": "America/Cuiaba",
    "Central Europe Standard Time": "Europe/Budapest",
    "Central European Standard Time": "Europe/Warsaw",
    "Central Pacific Standard Time": "Pacific/Guadalcanal",
    "Central Standard Time": "America/Chicago",
    "Central Standard Time (Mexico)": "America/Mexico_City",
    "Chatham Islands Standard Time": "Pacific/Chatham",
    "China Standard Time": "Asia/Shanghai",
    "Cuba Standard Time": "America/Havana",
    "Dateline Standard Time": "Etc/GMT+12",
    "E. Africa Standard Time": "Africa/Nairobi",
    "E. Australia Standard Time": "Australia/Brisbane",
    "E. Europe Standard Time": "Europe/Chisinau",
    "E. South America Standard Time": "America/Sao_Paulo",
    "Easter Island Standard Time": "Pacific/Easter",
    "Eastern Standard Time": "America/New_York",
    "Eastern Standard Time (Mexico)": "America/Cancun",
    "Egypt Standard Time": "Africa/Cairo",
    "Ekaterinburg Standard Time": "Asia/Yekaterinburg",
    "FLE Standard Time": "Europe/Kiev",
    "Fiji Standard Time": "Pacific/Fiji",
    "GMT Standard Time": "Europe/London",
    "GTB Standard Time": "Europe/Bucharest",
    "Georgian Standard Time": "Asia/Tbilisi",
    "Greenland Standard Time": "America/Godthab",
    "Greenwich Standard Time": "Atlantic/Reykjavik",
    "Haiti Standard Time": "America/Port-au-Prince",
    "Hawaiian Standard Time": "Pacific/Honolulu",
    "India Standard Time": "Asia/Kolkata",
    "Iran Standard Time": "Asia/Tehran",
    "Israel Standard Time": "Asia/Jerusalem",
    "Jordan Standard Time": "Asia/Amman",
    "Kaliningrad Standard Time": "Europe/Kaliningrad",
    "Kamchatka Standard Time": "Asia/Kamchatka",
    "Korea Standard Time": "Asia/Seoul",
    "Libya Standard Time": "Africa/Tripoli",
    "Line Islands Standard Time": "Pacific/Kiritimati",
    "Lord Howe Standard Time": "Australia/Lord_Howe",
    "Magadan Standard Time": "Asia/Magadan",
    "Magallanes Standard Time": "America/Punta_Arenas",
    "Marquesas Standard Time": "Pacific/Marquesas",
    "Mauritius Standard Time": "Indian/Mauritius",
    "Mid-Atlantic Standard Time": "Atlantic/South_Georgia",
    "Middle East Standard Time": "Asia/Beirut",
    "Montevideo Standard Time": "America/Montevideo",
    "Morocco Standard Time": "Africa/Casablanca",
    "Mountain Standard Time": "America/Denver",
    "Mountain Standard Time (Mexico)": "America/Mazatlan",
    "Myanmar Standard Time": "Asia/Rangoon",
    "N. Central Asia Standard Time": "Asia/Novosibirsk",
    "Namibia Standard Time": "Africa/Windhoek",
    "Nepal Standard Time": "Asia/Katmandu",
    "New Zealand Standard Time": "Pacific/Auckland",
    "Newfoundland Standard Time": "America/St_Johns",
    "Norfolk Standard Time": "Pacific/Norfolk",
    "North Asia East Standard Time": "Asia/Irkutsk",
    "North Asia Standard Time": "Asia/Krasnoyarsk",
    "North Korea Standard Time": "Asia/Pyongyang",
    "Omsk Standard Time": "Asia/Omsk",
    "Pacific SA Standard Time": "America/Santiago",
    "Pacific Standard Time": "America/Los_Angeles",
    "Pacific Standard Time (Mexico)": "America/Tijuana",
    "Pakistan Standard Time": "Asia/Karachi",
    "Paraguay Standard Time": "America/Asuncion",
    "Qyzylorda Standard Time": "Asia/Qyzylorda",
    "Romance Standard Time": "Europe/Paris",
    "Russia Time Zone 10": "Asia/Srednekolymsk",
    "Russia Time Zone 11": "Asia/Kamchatka",
    "Russia Time Zone 3": "Europe/Samara",
    "Russian Standard Time": "Europe/Moscow",
    "SA Eastern Standard Time": "America/Cayenne",
    "SA Pacific Standard Time": "America/Bogota",
    "SA Western Standard Time": "America/La_Paz",
    "SE Asia Standard Time": "Asia/Bangkok",
    "Saint Pierre Standard Time": "America/Miquelon",
    "Sakhalin Standard Time": "Asia/Sakhalin",
    "Samoa Standard Time": "Pacific/Apia",
    "Sao Tome Standard Time": "Africa/Sao_Tome",
    "Saratov Standard Time": "Europe/Saratov",
    "Singapore Standard Time": "Asia/Singapore",
    "South Africa Standard Time": "Africa/Johannesburg",
    "South Sudan Standard Time": "Africa/Juba",
    "Sri Lanka Standard Time": "Asia/Colombo",
    "Sudan Standard Time": "Africa/Khartoum",
    "Syria Standard Time": "Asia/Damascus",
    "Taipei Standard Time": "Asia/Taipei",
    "Tasmania Standard Time": "Australia/Hobart",
    "Tocantins Standard Time": "America/Araguaina",
    "Tokyo Standard Time": "Asia/Tokyo",
    "Tomsk Standard Time": "Asia/Tomsk",
    "Tonga Standard Time": "Pacific/Tongatapu",
    "Transbaikal Standard Time": "Asia/Chita",
    "Turkey Standard Time": "Europe/Istanbul",
    "Turks And Caicos Standard Time": "America/Grand_Turk",
    "US Eastern Standard Time": "America/Indianapolis",
    "US Mountain Standard Time": "America/Phoenix",
    "UTC": "UTC",
    "UTC+12": "Etc/GMT-12",
    "UTC+13": "Etc/GMT-13",
    "UTC-02": "Etc/GMT+2",
    "UTC-08": "Etc/GMT+8",
    "UTC-09": "Etc/GMT+9",
    "UTC-11": "Etc/GMT+11",
    "Ulaanbaatar Standard Time": "Asia/Ulaanbaatar",
    "Venezuela Standard Time": "America/Caracas",
    "Vladivostok Standard Time": "Asia/Vladivostok",
    "Volgograd Standard Time": "Europe/Volgograd",
    "W. Australia Standard Time": "Australia/Perth",
    "W. Central Africa Standard Time": "Africa/Lagos",
    "W. Europe Standard Time": "Europe/Berlin",
    "W. Mongolia Standard Time": "Asia/Hovd",
    "West Asia Standard Time": "Asia/Tashkent",
    "West Bank Standard Time": "Asia/Hebron",
    "West Pacific Standard Time": "Pacific/Port_Moresby",
    "Yakutsk Standard Time": "Asia/Yakutsk",
    "Yukon Standard Time": "America/Whitehorse",
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
