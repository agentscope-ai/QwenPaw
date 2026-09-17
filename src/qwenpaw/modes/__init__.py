# -*- coding: utf-8 -*-
"""Mode abstractions.

Each ``AgentMode`` packages the commands / tools / hooks / prompt
contributors that belong to one runtime mode (``coding`` / ``mission``
/ ``plan``).  The base class and the ``ModeGatedHook`` mix-in provide
a single registration surface for mode authors.
"""

from __future__ import annotations

from .base import AgentMode, ModeGatedHook

__all__ = ["AgentMode", "ModeGatedHook"]
