# -*- coding: utf-8 -*-
"""Per-turn artifact collector access for file-producing tools."""

from contextvars import ContextVar, Token
from pathlib import Path

from .collector import ArtifactCollector, ArtifactCollectorGroup

ArtifactCollectorContext = ArtifactCollector | ArtifactCollectorGroup

_CURRENT_COLLECTOR: ContextVar[ArtifactCollectorContext | None] = ContextVar(
    "workspace_artifact_collector",
    default=None,
)


def set_current_artifact_collector(
    collector: ArtifactCollectorContext | None,
) -> Token:
    """Set the collector visible to tools in the current async context."""
    return _CURRENT_COLLECTOR.set(collector)


def reset_current_artifact_collector(token: Token) -> None:
    """Restore the collector value that preceded one runtime turn."""
    _CURRENT_COLLECTOR.reset(token)


def register_current_artifact(file_path: str | Path) -> bool:
    """Register a file with the active turn collector when available."""
    collector = _CURRENT_COLLECTOR.get()
    if collector is None:
        return False
    return collector.register(file_path)
