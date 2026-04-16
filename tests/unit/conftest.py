# -*- coding: utf-8 -*-
"""Unit test configuration for qwenpaw test suite."""

import sys
from types import SimpleNamespace
from unittest.mock import MagicMock

from pydantic import BaseModel

sys.modules["agentscope_runtime"] = MagicMock()
sys.modules["agentscope_runtime.engine"] = MagicMock()
sys.modules["agentscope_runtime.engine.runner"] = MagicMock()
sys.modules["agentscope_runtime.engine.schemas"] = MagicMock()

mock_runner_class = MagicMock()
sys.modules["agentscope_runtime.engine.runner"].Runner = mock_runner_class


class MockMessage(BaseModel):
    model_config = {"arbitrary_types_allowed": True}


sys.modules[
    "agentscope_runtime.engine.schemas.agent_schemas"
] = SimpleNamespace(
    Message=MockMessage,
    AgentRequest=MagicMock(),
    TextContent=MagicMock(),
    ImageContent=MagicMock(),
    AudioContent=MagicMock(),
    VideoContent=MagicMock(),
    FileContent=MagicMock(),
    DataContent=MagicMock(),
    FunctionCall=MagicMock(),
    FunctionCallOutput=MagicMock(),
    MessageType=MagicMock(),
)

sys.modules["apscheduler"] = MagicMock()
sys.modules["apscheduler.schedulers"] = MagicMock()
sys.modules["apscheduler.schedulers.asyncio"] = MagicMock()
