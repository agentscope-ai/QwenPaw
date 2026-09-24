# -*- coding: utf-8 -*-
"""Immutable business scope used to bind storage repositories."""

from dataclasses import dataclass


@dataclass(frozen=True)
class StorageScope:
    """Deployment-local ownership, separate from database credentials."""

    tenant_id: str
    workspace_id: str
    agent_id: str

    def __post_init__(self) -> None:
        if not all((self.tenant_id, self.workspace_id, self.agent_id)):
            raise ValueError(f"Storage scope identifiers must not be empty")
