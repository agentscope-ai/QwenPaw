"""Per-turn artifact collector access for file-producing tools."""

from contextvars import ContextVar
from pathlib import Path

from .collector import ArtifactCollector

_CURRENT_COLLECTOR: ContextVar[ArtifactCollector | None] = ContextVar(
    "workspace_artifact_collector",
    default=None,
)


def set_current_artifact_collector(
    collector: ArtifactCollector | None,
) -> None:
    """Set the collector visible to tools in the current async context."""
    _CURRENT_COLLECTOR.set(collector)


def register_current_artifact(file_path: str | Path) -> bool:
    """Register a file with the active turn collector when available."""
    collector = _CURRENT_COLLECTOR.get()
    if collector is None:
        return False
    return collector.register(file_path)
