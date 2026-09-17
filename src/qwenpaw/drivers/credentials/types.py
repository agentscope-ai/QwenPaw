# -*- coding: utf-8 -*-
"""Runtime credential value types."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, ClassVar


def _redact_mapping(values: dict[str, Any]) -> dict[str, str]:
    return {str(key): "***" for key in values}


@dataclass(frozen=True)
class CredentialRecord:
    ref: str
    kind: str
    public: dict[str, Any] = field(default_factory=dict)
    secrets: dict[str, Any] = field(default_factory=dict)
    meta: dict[str, Any] = field(default_factory=dict)

    @property
    def values(self) -> dict[str, Any]:
        return {**self.public, **self.secrets}

    def __repr__(self) -> str:
        return (
            "CredentialRecord("
            f"ref={self.ref!r}, "
            f"kind={self.kind!r}, "
            f"public={self.public!r}, "
            f"secrets={_redact_mapping(self.secrets)!r}, "
            f"meta={self.meta!r})"
        )


@dataclass(frozen=True)
class ResolvedCredential:
    kind: str = "none"
    public: dict[str, Any] = field(default_factory=dict)
    secrets: dict[str, Any] = field(default_factory=dict)
    meta: dict[str, Any] = field(default_factory=dict)

    EMPTY: ClassVar["ResolvedCredential"]

    @property
    def values(self) -> dict[str, Any]:
        return {**self.public, **self.secrets}

    def __repr__(self) -> str:
        return (
            "ResolvedCredential("
            f"kind={self.kind!r}, "
            f"public={self.public!r}, "
            f"secrets={_redact_mapping(self.secrets)!r}, "
            f"meta={self.meta!r})"
        )


ResolvedCredential.EMPTY = ResolvedCredential()
