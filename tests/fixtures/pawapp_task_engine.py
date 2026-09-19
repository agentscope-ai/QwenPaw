# -*- coding: utf-8 -*-
# pylint: disable=protected-access
"""Test-only Engine process: real API/stores/envelope, controlled execution.

Run with the Engine's interpreter, not the Host's dependency environment.
All state goes under the supplied temporary home; no model calls are made.
"""

from __future__ import annotations

import asyncio
import json
import socket
import sys
from pathlib import Path
from types import SimpleNamespace

import uvicorn
from agentscope.event import (
    TextBlockDeltaEvent,
    TextBlockEndEvent,
    TextBlockStartEvent,
)

from qwenpaw_data.host.core.api.app import create_app
from qwenpaw_data.host.core.api.routers.datasources import (
    get_context_manager_client,
)
from qwenpaw_data.host.core.runtime.chat_runtime import ChatRuntime
from qwenpaw_data.host.core.runtime.envelope import Envelope
from qwenpaw_data.host.core.stream.output_stream import OutputStream


def main():
    home = Path(sys.argv[1])
    port_file = Path(sys.argv[2])
    app = create_app(home=home, model=object())
    app.dependency_overrides[
        get_context_manager_client
    ] = lambda: SimpleNamespace(
        list_datasources=lambda: SimpleNamespace(
            items=[
                SimpleNamespace(
                    datasource_id="sales",
                    datasource_name="Sales",
                    datasource_type="test",
                ),
            ],
        ),
    )
    resume = asyncio.Event()

    async def execute(runtime, chat_id, *, identity):
        del identity
        chat = await runtime.chats.get(chat_id)
        stream = OutputStream(
            runtime.events,
            session_id=chat.session_id,
            chat_id=chat.id,
            identity=chat.identity,
        )
        envelope = Envelope(stream)
        await envelope.begin()
        if chat.user_input == "clarify":
            call_id = "clarification-1"
            await stream.message_complete(
                msg_id="question",
                sequence=0,
                type="plugin_call",
                role="assistant",
                source_id=call_id,
                content=[
                    {
                        "type": "data",
                        "data": {
                            "call_id": call_id,
                            "name": "ask_user_question",
                            "arguments": json.dumps(
                                {
                                    "title": "Choose a period",
                                    "questions": [
                                        {
                                            "question": "Which period?",
                                            "multiSelect": False,
                                            "options": [
                                                {"label": "Q1"},
                                                {"label": "Q2"},
                                            ],
                                        },
                                    ],
                                },
                            ),
                        },
                    },
                ],
            )
            result = await runtime._executor._clarification.wait_for_answer(
                call_id,
            )
            await stream.message_complete(
                msg_id="clarification-result",
                sequence=1,
                type="plugin_call_output",
                role="tool",
                source_id=call_id,
                content=[
                    block.model_dump(mode="json") for block in result.output
                ],
            )
        await envelope.translate_event(
            TextBlockStartEvent(
                reply_id="test",
                block_id="answer",
            ),
        )
        await envelope.translate_event(
            TextBlockDeltaEvent(
                reply_id="test",
                block_id="answer",
                delta="Revenue is ",
            ),
        )
        if chat.user_input == "pause":
            await resume.wait()
            if runtime._cancel_requested:
                await runtime._finish(chat, envelope, "canceled")
                return
        await envelope.translate_event(
            TextBlockDeltaEvent(
                reply_id="test",
                block_id="answer",
                delta="42.",
            ),
        )
        await envelope.translate_event(
            TextBlockEndEvent(
                reply_id="test",
                block_id="answer",
            ),
        )
        await runtime._finish(
            chat,
            envelope,
            "completed",
        )

    ChatRuntime._run = execute

    async def cancel(runtime):
        if runtime._finished.is_set():
            return
        runtime._cancel_requested = True
        resume.set()
        await runtime._finished.wait()

    ChatRuntime.cancel = cancel

    @app.post("/__test__/release")
    async def release():
        resume.set()
        return {"released": True}

    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port_file.write_text(str(sock.getsockname()[1]), encoding="utf-8")
        server = uvicorn.Server(uvicorn.Config(app, log_level="error"))
        asyncio.run(server.serve(sockets=[sock]))


if __name__ == "__main__":
    main()
