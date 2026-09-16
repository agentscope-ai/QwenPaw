# -*- coding: utf-8 -*-
from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest

from qwenpaw.agents.tools.personal_library import build_personal_library_tools
from qwenpaw.personal_library.service import PersonalLibraryService
from tests.unit.personal_library.test_runtime_access import GrantRepository


@pytest.mark.asyncio
async def test_tool_reads_current_agent_library_without_separate_grant(tmp_path: Path) -> None:
    owner_id = uuid4()
    repository = GrantRepository()
    service = PersonalLibraryService(repository=repository, working_dir=tmp_path)
    document = await service.create_text(owner_user_id=owner_id, relative_path="note.md", content="hello")
    _search, read = build_personal_library_tools(service=service, owner_user_id=owner_id, agent_key="default")
    result = await read(str(document.id))
    assert result["content"] == "hello"
