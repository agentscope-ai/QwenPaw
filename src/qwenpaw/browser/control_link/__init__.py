# -*- coding: utf-8 -*-
"""Browser variant control-link packages."""

_registered = False


def register_builtin_control_links() -> None:
    """Idempotently self-register first-party control links."""
    global _registered
    if _registered:
        return
    from .chrome.adapter import register as register_chrome
    from .cdp.adapter import register as register_cdp
    from .playwright.adapter import register as register_playwright

    register_chrome()
    register_cdp()
    register_playwright()
    _registered = True
