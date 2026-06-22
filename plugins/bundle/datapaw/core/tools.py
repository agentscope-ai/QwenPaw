# -*- coding: utf-8 -*-
"""Built-in tool functions for DataPaw agents."""
from __future__ import annotations

from typing import Any, Callable

DEFAULT_TOOL_NAMES: list[str] = []
TOOL_REGISTRY: dict[str, Callable[..., Any]] = {}
