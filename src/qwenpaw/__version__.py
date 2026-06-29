# -*- coding: utf-8 -*-

__version__ = "2.0.0b2"


def get_qwenpaw_compat_label(version: str | None = None) -> str:
    """Return the major-version compatibility label used by the plugin market.

    Examples:
        >>> get_qwenpaw_compat_label("1.1.12")
        '1.x'
        >>> get_qwenpaw_compat_label("2.0.0b1")
        '2.x'
    """
    version = (version or __version__).strip()
    major = version.split(".", 1)[0] if version else "0"
    return f"{major}.x"
