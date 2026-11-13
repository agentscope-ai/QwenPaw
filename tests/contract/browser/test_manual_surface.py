# -*- coding: utf-8 -*-
"""Every locator call named in the manual must exist on LocatorView."""
import re

from qwenpaw.browser.sdk import facade
from qwenpaw.browser.sdk.contracts import LocatorView

_MANUAL = "".join(
    value
    for name in dir(facade)
    if name.startswith("_BLOCK")
    for value in [getattr(facade, name)]
    if isinstance(value, str)
)

_CALL_RE = re.compile(r"\b([a-z_][a-z0-9_]*)\(")

_NON_LOCATOR_NAMES = {
    "browser",
    "connect",
    "open",
    "close",
    "close_page",
    "close_session",
    "snapshot",
    "current_surface",
    "goto",
    "screenshot",
    "print",
    "getting_started",
    "get_by_role",
    "get_by_label",
    "get_by_text",
    "get_by_placeholder",
    "locator",
    "frame_locator",
    "handoff",
    "activate_page",
    "wait_for",
    "session_status",
    "len",
    "splitlines",
    "join",
}


def test_manual_locator_calls_exist_on_contract():
    """The manual cannot advertise locator methods absent from the SDK."""
    advertised = set(_CALL_RE.findall(_MANUAL)) - _NON_LOCATOR_NAMES
    missing = sorted(
        name for name in advertised if not hasattr(LocatorView, name)
    )
    assert missing == []


def test_removed_surface_not_advertised():
    """Removed and property-only calls cannot return to the manual."""
    for banned in ("evaluate(", "drag(", "first()", "last()"):
        assert banned not in _MANUAL
