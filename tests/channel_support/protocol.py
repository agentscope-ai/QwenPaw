# -*- coding: utf-8 -*-
"""Small protocol calls shared by native platform tests (no test cases)."""

import asyncio
from qwenpaw.channel_protocol.models import SendParams, ResponseFinishParams


async def eventually(predicate):
    async with asyncio.timeout(3):
        while not predicate():
            await asyncio.sleep(0.01)


async def open_route(peer, identity, target, **meta):
    result = await peer.methods["channel.response.open"](
        {**identity.to_mapping(), "to_handle": target, "meta": meta},
        None,
    )
    return result["response_handle"]


async def send(
    peer,
    identity,
    handle,
    *,
    delivery="answer",
    parts=None,
    **fields,
):
    value = {
        **identity.to_mapping(),
        "to_handle": handle,
        "delivery_id": delivery,
        "operation": "message.create",
        **fields,
    }
    if value["operation"].startswith("stream."):
        value.setdefault("accumulated_text", "")
        value.setdefault("sequence", 0)
    if parts is not None:
        value["content_parts"] = parts
    elif value["operation"] == "message.create":
        value["content_parts"] = [{"type": "text", "text": "native answer"}]
    return await peer.methods["channel.send"](
        SendParams.from_mapping(value),
        None,
    )


async def finish(peer, identity, handle):
    return await peer.methods["channel.response.finish"](
        ResponseFinishParams.from_mapping(
            {
                **identity.to_mapping(),
                "response_handle": handle,
                "outcome": "completed",
            },
        ),
        None,
    )
