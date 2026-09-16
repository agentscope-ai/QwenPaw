# -*- coding: utf-8 -*-
"""用户个人资料库的领域模型。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID


@dataclass(frozen=True, slots=True)
class PersonalLibraryDocument:
    """一个已登记且属于单一用户、单一 Agent 的资料文件。"""

    id: UUID
    owner_user_id: UUID
    agent_id: UUID
    relative_path: str
    name: str
    media_type: str
    size: int
    sha256: str
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class PersonalLibraryDocumentContent:
    """资料文本的单次读取结果。"""

    document: PersonalLibraryDocument
    content: str
    offset: int
    next_offset: int | None
    truncated: bool
