# -*- coding: utf-8 -*-
"""Declarative system-prompt contributions with explicit workspace scope."""

from dataclasses import dataclass
from typing import Callable

from .context import RequestContext


@dataclass(frozen=True)
class PromptSpec:
    name: str
    text: str = ""
    priority: int = 100
    workspace_id: str | None = None
    render: Callable[[RequestContext], str] | None = None
