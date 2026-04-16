# -*- coding: utf-8 -*-
"""Plugin architecture definitions."""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
from pathlib import Path


@dataclass
class PluginManifest:
    """Plugin manifest definition."""

    id: str
    name: str
    version: str
    description: str = ""
    author: str = ""
    entry_point: str = "plugin.py"
    dependencies: List[str] = field(default_factory=list)
    min_version: str = "0.1.0"
    meta: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "PluginManifest":
        """Create manifest from dictionary.

        Args:
            data: Manifest data dictionary

        Returns:
            PluginManifest instance
        """
        return cls(
            id=data["id"],
            name=data["name"],
            version=data["version"],
            description=data.get("description", ""),
            author=data.get("author", ""),
            entry_point=data.get("entry_point", "plugin.py"),
            dependencies=data.get("dependencies", []),
            min_version=data.get("min_version", "0.1.0"),
            meta=data.get("meta", {}),
        )


@dataclass
class PluginRecord:
    """Plugin record for loaded plugins."""

    manifest: PluginManifest
    source_path: Path
    enabled: bool
    instance: Optional[Any] = None
    diagnostics: List[str] = field(default_factory=list)
