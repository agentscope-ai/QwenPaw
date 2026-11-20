# -*- coding: utf-8 -*-
"""Trusted shared Runner hello construction."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, TYPE_CHECKING

from .errors import DescriptorValidationError, ProtocolValidationError
from .identifiers import validate_digest

if TYPE_CHECKING:
    from .shared import SharedHelloParams


@dataclass(frozen=True, slots=True, init=False)
class RunnerProtocolHost:
    """Construct hello from trusted source and non-source launch identity."""

    _source_revision: str

    def __init__(self, source_revision: str) -> None:
        try:
            object.__setattr__(
                self,
                "_source_revision",
                validate_digest(
                    source_revision,
                    name="Source revision",
                ),
            )
        except DescriptorValidationError as exc:
            raise ProtocolValidationError(
                str(exc),
                path=("source_revision",),
            ) from exc

    @property
    def source_revision(self) -> str:
        """Return the immutable revision supplied by trusted bootstrap."""
        return self._source_revision

    def create_shared_hello(
        self,
        *,
        channel_key: str,
        instance_id: str,
        generation: int,
        qwenpaw_version: str,
        requirements_path: str | Path,
        capabilities: tuple[str, ...] = (),
        versions: Mapping[str, str] | None = None,
    ) -> SharedHelloParams:
        """Observe actual child metadata before importing any Driver."""
        from packaging.markers import default_environment
        from packaging.tags import sys_tags

        from .identifiers import current_python_abi
        from .shared import (
            SHARED_PROTOCOL_VERSION,
            SharedHelloParams,
            audit_shared_dependencies,
        )

        audit = audit_shared_dependencies(requirements_path, versions=versions)
        audit.require_satisfied()
        return SharedHelloParams.from_mapping(
            {
                "protocol_version": SHARED_PROTOCOL_VERSION,
                "dependency_mode": "shared",
                "channel_key": channel_key,
                "instance_id": instance_id,
                "generation": generation,
                "qwenpaw_version": qwenpaw_version,
                "source_revision": self._source_revision,
                "python_abi": current_python_abi(),
                "platform_tag": next(sys_tags()).platform,
                "dependencies": audit.to_mapping(),
                "marker_environment": default_environment(),
                "capabilities": list(capabilities),
            },
        )
