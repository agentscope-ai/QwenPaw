# -*- coding: utf-8 -*-
from unittest.mock import AsyncMock, MagicMock

import pytest
from agentscope.message import Msg

from copaw.agents.memory.powermem_in_memory import PowerMemInMemoryMemory


@pytest.fixture
def mock_pm():
    mock = MagicMock()
    mock.add = AsyncMock(return_value={"id": 1})
    mock.get_all = AsyncMock(return_value={"results": []})
    mock.search = AsyncMock(return_value={"results": []})
    return mock


@pytest.fixture
def mem(mock_pm):
    return PowerMemInMemoryMemory(
        powermem=mock_pm,
        agent_id="test_agent",
        working_dir="/tmp/test",
    )


@pytest.mark.asyncio
async def test_add(mem, mock_pm):
    msg = Msg(name="user", content="Hello", role="user")
    msg.id = "msg1"
    await mem.add(msg)

    assert len(mem.content) == 1
    assert mem.content[0][0].id == "msg1"
    mock_pm.add.assert_called_once()


@pytest.mark.asyncio
async def test_delete(mem):
    for i in range(5):
        msg = Msg(name="user", content=f"Message {i}", role="user")
        msg.id = f"msg{i}"
        await mem.add(msg)

    deleted = await mem.delete(["msg0", "msg1"])

    assert deleted == 2
    assert len(mem.content) == 3


def test_get_memory_prepend_summary(mem):
    mem.update_compressed_summary("Previous summary")

    msg = Msg(name="user", content="Hello", role="user")
    mem.content.append((msg, []))

    memory = mem.get_memory(prepend_summary=True)

    assert memory[0].role == "system"
    assert "Previous summary" in memory[0].content


def test_get_compressed_summary(mem):
    assert mem.get_compressed_summary() == ""

    mem.update_compressed_summary("New summary")
    assert mem.get_compressed_summary() == "New summary"

    mem.clear_compressed_summary()
    assert mem.get_compressed_summary() == ""


def test_size(mem):
    assert mem.size() == 0

    for i in range(3):
        msg = Msg(name="user", content=f"Msg {i}", role="user")
        msg.id = f"msg{i}"
        mem.content.append((msg, []))

    assert mem.size() == 3
