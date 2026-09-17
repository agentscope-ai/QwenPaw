# -*- coding: utf-8 -*-
"""Stable browser error codes (core source of truth)."""

from enum import StrEnum


class BrowserErrorCode(StrEnum):
    """Error codes shared by browser transport implementations."""

    UNKNOWN = "unknown"
    BRIDGE_DISCONNECTED = "bridge_disconnected"
    BRIDGE_REQUEST_TIMEOUT = "bridge_request_timeout"
    BROWSER_TAB_OCCUPIED = "browser_tab_occupied"
    BROWSER_PROTOCOL_VERSION_MISMATCH = "browser_protocol_version_mismatch"
    BROWSER_COMMAND_TOO_LARGE = "browser_command_too_large"


__all__ = ["BrowserErrorCode"]
