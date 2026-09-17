# -*- coding: utf-8 -*-
"""Core browser-control abstractions."""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .sdk.facade import Browser
    from .sdk.page import Page

__all__ = ["Browser", "Page"]


def __getattr__(name: str) -> object:
    """Lazily expose the SDK entrypoints from the package path (PEP 562).

    The model reflexively writes ``from qwenpaw.browser import Browser``;
    resolve that without eager import cost or a circular facade import.
    """
    if name == "Browser":
        from .sdk.facade import Browser

        return Browser
    if name == "Page":
        from .sdk.page import Page

        return Page
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
