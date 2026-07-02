# -*- coding: utf-8 -*-
"""QwenPaw offloader redacts secrets before persistence."""

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from agentscope.message import Msg, TextBlock

from qwenpaw.agents.offloader import QwenPawOffloader


@pytest.mark.asyncio
async def test_offload_context_redacts_dialog_jsonl(tmp_path):
    offloader = QwenPawOffloader(
        dialog_path=str(tmp_path / "dialog"),
        tool_results_dir=str(tmp_path / "tool_results"),
    )
    secret = "sk-abcdefghijklmnopqrstuvwxyz"
    msg = Msg(
        name="tool",
        role="assistant",
        content=[TextBlock(type="text", text=f"token={secret}")],
    )

    path = await offloader.offload_context("session-1", [msg])

    body = Path(path).read_text(encoding="utf-8")
    payload = json.loads(body)
    assert secret not in body
    assert "sk-a****wxyz" in str(payload)


@pytest.mark.asyncio
async def test_offload_tool_result_redacts_text_file(tmp_path):
    offloader = QwenPawOffloader(
        dialog_path=str(tmp_path / "dialog"),
        tool_results_dir=str(tmp_path / "tool_results"),
    )
    secret = "ghp_abcdefghijklmnopqrstuvwxyz123456"
    tool_result = SimpleNamespace(output=f"token={secret}")

    path = await offloader.offload_tool_result("session-1", tool_result)

    body = Path(path).read_text(encoding="utf-8")
    assert secret not in body
    assert "ghp_****3456" in body
