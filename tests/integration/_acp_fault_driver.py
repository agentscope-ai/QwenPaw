# -*- coding: utf-8 -*-
"""Minimal ACP agent subprocess used by the fault-injection tests.

The scenario is selected with ``QWENPAW_FAULT_SCENARIO``.  The module
patches only the workspace boundary so the real ACP server, prompt loop
and process shutdown path are exercised.
"""

# pylint: disable=protected-access,unused-argument

from __future__ import annotations

import asyncio
import os
import pathlib
from types import SimpleNamespace

import httpx
import openai

from qwenpaw.agents.acp import server
from qwenpaw.providers.retry_chat_model import StreamIdleTimeoutError

_SCENARIO = os.environ[f"QWENPAW_FAULT_SCENARIO"]


def _provider_error(message: str) -> openai.BadRequestError:
    request = httpx.Request(
        "POST",
        "https://example.test/v1/chat/completions",
    )
    response = httpx.Response(400, request=request)
    return openai.BadRequestError(
        message,
        response=response,
        body={"error": {"message": message}},
    )


class _FaultWorkspace:
    async def stream_query(self, request):
        del request
        if _SCENARIO == "moderation":
            raise _provider_error(
                "400 data_inspection_failed: inappropriate content",
            )
        if _SCENARIO == "idle":
            raise StreamIdleTimeoutError("policy", 600.0)
        if _SCENARIO == "hang":
            yield SimpleNamespace(
                object="content",
                text="started",
                delta=False,
                msg_id="m1",
            )
            await asyncio.sleep(60)


async def _ensure_workspace(self):
    return _FaultWorkspace()


async def _advertise_commands(self, session_id):
    return None


async def _bridge_approval_requests(
    self,
    session_id,
    *,
    poll_interval=0.25,
):
    del poll_interval
    await asyncio.sleep(3600)


async def _build_model_state(self):
    return None


async def _sync_session_mcp(self, session_id, mcp_servers):
    return None


async def _shutdown_workspace(self):
    marker = os.environ.get("QWENPAW_FAULT_MARKER")
    if marker:
        pathlib.Path(marker).write_text("shutdown", encoding="utf-8")


server.QwenPawACPAgent._ensure_workspace = _ensure_workspace
server.QwenPawACPAgent._advertise_commands = _advertise_commands
server.QwenPawACPAgent._bridge_approval_requests = _bridge_approval_requests
server.QwenPawACPAgent._build_model_state = _build_model_state
server.QwenPawACPAgent._sync_session_mcp = _sync_session_mcp
server.QwenPawACPAgent._shutdown_workspace = _shutdown_workspace


if __name__ == "__main__":
    try:
        asyncio.run(server.run_qwenpaw_agent())
    finally:
        server.silence_stdout()
