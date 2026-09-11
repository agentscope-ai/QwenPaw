# -*- coding: utf-8 -*-
"""Cross-user and cross-platform source data location resolution."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Mapping

from ..models import SourceLocation
from .qoder_sessions import default_qoder_user_data

_ALIASES = {
    "codex": "codex",
    "openai-codex": "codex",
    "qoder": "qoder",
}


def canonical_provider_id(source: str) -> str:
    """Return the canonical provider id or raise a useful error."""
    provider_id = _ALIASES.get(source.strip().lower())
    if provider_id is None:
        raise ValueError(
            f"Unsupported import source {source!r}. Supported providers: "
            "codex, qoder.",
        )
    return provider_id


def _configured_root(
    *,
    explicit: Path | None,
    environment: Mapping[str, str],
    variable: str,
    fallback: Path,
) -> tuple[Path, str]:
    if explicit is not None:
        root = explicit.expanduser()
        source = "explicit"
    else:
        configured = str(environment.get(variable) or "").strip()
        if configured:
            root = Path(configured).expanduser()
            source = f"environment:{variable}"
        else:
            root = fallback
            source = "platform_default"
    if not root.is_absolute():
        raise ValueError(f"Source data directory must be absolute: {root}")
    return root.resolve(strict=False), source


def resolve_source_location(
    source: str,
    *,
    source_home: Path | None = None,
    user_home: Path | None = None,
    platform_name: str | None = None,
    environ: Mapping[str, str] | None = None,
) -> SourceLocation:
    """Resolve provider roots without recursively scanning the whole device."""
    provider_id = canonical_provider_id(source)
    home = (user_home or Path.home()).expanduser().resolve(strict=False)
    environment = environ if environ is not None else os.environ
    platform_value = platform_name or sys.platform

    if provider_id == "codex":
        data_home, data_source = _configured_root(
            explicit=source_home,
            environment=environment,
            variable="CODEX_HOME",
            fallback=home / ".codex",
        )
        return SourceLocation(
            provider_id=provider_id,
            data_home=str(data_home),
            data_home_source=data_source,
            data_home_exists=data_home.is_dir(),
        )

    data_home, data_source = _configured_root(
        explicit=source_home,
        environment=environment,
        variable="QODER_HOME",
        fallback=home / ".qoder",
    )
    user_data = default_qoder_user_data(
        home,
        platform_name=platform_value,
        environ=environment,
    ).expanduser()
    if not user_data.is_absolute():
        raise ValueError(
            f"Qoder User data directory must be absolute: {user_data}",
        )
    user_data = user_data.resolve(strict=False)
    return SourceLocation(
        provider_id=provider_id,
        data_home=str(data_home),
        data_home_source=data_source,
        user_data_home=str(user_data),
        data_home_exists=data_home.is_dir(),
        user_data_home_exists=user_data.is_dir(),
    )


__all__ = [
    "canonical_provider_id",
    "resolve_source_location",
]
