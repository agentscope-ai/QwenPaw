# -*- coding: utf-8 -*-
"""Detect the system IANA timezone.

Kept in its own module to avoid circular imports between config.py and
utils.py.  Uses only the standard library; always returns a valid string
(falls back to ``"UTC"``).
"""

from __future__ import annotations

import os
from datetime import datetime, timezone


def detect_system_timezone() -> str:
    """Return the IANA timezone name of the host, falling back to ``UTC``."""
    try:
        local_name = (
            datetime.now(timezone.utc)
            .astimezone()
            .tzinfo.tzname(None)  # type: ignore[union-attr]
        )
        if local_name and "/" in local_name:
            return local_name
    except Exception:
        pass

    tz_env = os.environ.get("TZ", "")
    if tz_env and "/" in tz_env:
        return tz_env

    try:
        with open("/etc/timezone", encoding="utf-8") as f:
            name = f.read().strip()
            if name and "/" in name:
                return name
    except OSError:
        pass

    try:
        link = os.readlink("/etc/localtime")
        if "zoneinfo/" in link:
            return link.split("zoneinfo/", 1)[1]
    except OSError:
        pass

    return "UTC"
