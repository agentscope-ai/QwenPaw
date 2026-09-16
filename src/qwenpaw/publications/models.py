# -*- coding: utf-8 -*-
"""共享应用发布的存储无关领域记录。"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

SharedAppStatus = Literal["draft", "active", "retired"]
ReviewStatus = Literal["pending", "approved", "rejected"]


class _Record(BaseModel):
    model_config = ConfigDict(frozen=True)


class SharedAppRecord(_Record):
    id: UUID
    agent_id: UUID
    owner_user_id: UUID
    status: SharedAppStatus
    current_publication_id: UUID | None = None
    created_at: datetime
    updated_at: datetime


class SharedAppDraftRecord(_Record):
    id: UUID
    shared_app_id: UUID
    revision: int = Field(ge=1)
    manifest: dict[str, Any]
    workspace_key: str
    created_by: UUID
    updated_at: datetime


class SharedAppPublicationRecord(_Record):
    id: UUID
    shared_app_id: UUID
    version: str = Field(pattern=r"^r[1-9][0-9]*$")
    immutable_manifest: dict[str, Any]
    baseline_workspace_key: str
    submitted_by: UUID
    reviewed_by: UUID | None = None
    review_status: ReviewStatus
    review_note: str | None = None
    reviewed_at: datetime | None = None
    published_at: datetime | None = None
    retired_at: datetime | None = None


class SharedAppUserWorkspaceRecord(_Record):
    shared_app_id: UUID
    publication_id: UUID
    user_id: UUID
    workspace_key: str
    quota: int | None = None
    status: Literal["initializing", "active", "failed"]
    created_at: datetime
    updated_at: datetime


class DependencyCheck(_Record):
    kind: Literal["model", "skill", "mcp", "plugin", "credential"]
    reference: str
    ok: bool
    code: str | None = None
    message: str | None = None


class DependencyReport(_Record):
    items: tuple[DependencyCheck, ...] = ()

    @property
    def ok(self) -> bool:
        return all(item.ok for item in self.items)
