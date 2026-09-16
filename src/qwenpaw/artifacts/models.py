from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal
from uuid import UUID

ArtifactStatus = Literal["active", "deleted"]


@dataclass(frozen=True, slots=True)
class AgentArtifact:
    id: UUID
    owner_user_id: UUID
    agent_id: UUID
    conversation_id: UUID | None
    relative_path: str
    original_name: str
    media_type: str
    size: int
    sha256: str
    source_tool: str
    status: ArtifactStatus
    created_at: datetime
    deleted_at: datetime | None
