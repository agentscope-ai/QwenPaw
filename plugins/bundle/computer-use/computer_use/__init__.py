# -*- coding: utf-8 -*-
"""computer_use tool package (plugin-provided)."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .dispatch import computer_use

__all__ = ["computer_use"]


def __getattr__(name: str):
    """Load the host-bound tool entry point only when it is requested."""
    if name != "computer_use":
        raise AttributeError(name)
    from .dispatch import computer_use

    return computer_use
