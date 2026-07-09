# -*- coding: utf-8 -*-
from unittest.mock import AsyncMock

import pytest
from agentscope.message import Msg, TextBlock

from qwenpaw.agents.memory.reme_light_memory_manager import (
    ReMeLightMemoryManager,
)


def _msg(role: str, text: str) -> Msg:
    return Msg(
        name="user" if role == "user" else "QwenPaw",
        role=role,
        content=[TextBlock(type="text", text=text)],
    )


@pytest.mark.asyncio
async def test_summarize_skips_reme_job_without_session_id(tmp_path) -> None:
    manager = ReMeLightMemoryManager(
        working_dir=str(tmp_path),
        agent_id="default",
    )
    manager._run_reme_job = AsyncMock()

    result = await manager.summarize([_msg("user", "hello")])

    assert result == ""
    manager._run_reme_job.assert_not_awaited()
