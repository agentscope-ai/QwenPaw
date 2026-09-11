# -*- coding: utf-8 -*-
"""Registry for Marketplace sources restored by PawPort."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlsplit, urlunsplit

from ..config.utils import get_plugins_dir
from ..utils.io_utils import (
    get_path_lock,
    read_json_async,
    write_json_atomic_async,
)


def _clean_source(source: str) -> tuple[str, bool]:
    """Remove URL credentials/query/fragment before persisting a source."""
    value = str(source or "").strip()
    if not value.startswith(("http://", "https://")):
        return value, False
    parsed = urlsplit(value)
    host = parsed.hostname or ""
    if parsed.port is not None:
        host = f"{host}:{parsed.port}"
    cleaned = urlunsplit((parsed.scheme, host, parsed.path, "", ""))
    return cleaned, cleaned != value


class ExternalMarketplaceRegistry:
    """Small JSON registry of provider-owned Marketplace declarations."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or (get_plugins_dir() / "marketplaces.json")

    async def read(self) -> dict[str, Any]:
        """Return a normalized registry, tolerating an absent old file."""
        try:
            value = (
                await read_json_async(self.path) if self.path.is_file() else {}
            )
        except (OSError, ValueError, TypeError):
            value = {}
        sources = value.get("sources", {}) if isinstance(value, dict) else {}
        if not isinstance(sources, dict):
            sources = {}
        return {"schema_version": "1", "sources": sources}

    # pylint: disable-next=too-many-arguments
    async def register_if_absent(
        self,
        *,
        provider: str,
        source_id: str,
        name: str,
        source: str,
        source_type: str,
        ref_name: str = "",
    ) -> tuple[Literal["created", "same", "conflict"], bool]:
        """Return ``(created|same|conflict, credentials_removed)``."""
        async with get_path_lock(self.path):
            payload = await self.read()
            cleaned_source, credentials_removed = _clean_source(source)
            key = f"{provider}:{source_id}"
            record = {
                "provider": provider,
                "source_id": source_id,
                "name": name,
                "source": cleaned_source,
                "source_type": source_type,
                "ref_name": ref_name,
                "status": (
                    "available" if cleaned_source else "source_unavailable"
                ),
            }
            existing = payload["sources"].get(key)
            if existing is not None:
                return (
                    "same" if existing == record else "conflict",
                    credentials_removed,
                )
            payload["sources"][key] = record
            self.path.parent.mkdir(parents=True, exist_ok=True)
            await write_json_atomic_async(
                self.path,
                payload,
                sort_keys=True,
                new_file_mode=0o600,
            )
            return "created", credentials_removed


__all__ = ["ExternalMarketplaceRegistry"]
