# -*- coding: utf-8 -*-
from __future__ import annotations

import os
from datetime import datetime

DEFAULT_TIMEZONE = "UTC"


def get_default_timezone() -> str:
    """Return the configured or detected local timezone name."""
    configured = os.environ.get("COPAW_TIMEZONE", "").strip()
    if configured:
        return configured

    try:
        import tzlocal  # type: ignore

        get_name = getattr(tzlocal, "get_localzone_name", None)
        if callable(get_name):
            detected = get_name()
            if isinstance(detected, str) and detected.strip():
                return detected.strip()

        get_zone = getattr(tzlocal, "get_localzone", None)
        if callable(get_zone):
            zone = get_zone()
            for attr in ("key", "zone"):
                detected = getattr(zone, attr, None)
                if isinstance(detected, str) and detected.strip():
                    return detected.strip()
            detected = str(zone).strip()
            if detected and detected.lower() != "local":
                return detected
    except Exception:
        pass

    try:
        local_tz = datetime.now().astimezone().tzinfo
        if local_tz is not None:
            for attr in ("key", "zone"):
                detected = getattr(local_tz, attr, None)
                if isinstance(detected, str) and detected.strip():
                    return detected.strip()
    except Exception:
        pass

    return DEFAULT_TIMEZONE
