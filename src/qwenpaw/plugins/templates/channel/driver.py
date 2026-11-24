# -*- coding: utf-8 -*-
"""Runnable local mailbox example. Replace storage delivery with a platform API."""

import hashlib

from qwenpaw.plugins.channel_workers import (
    ChannelDriver,
    ChannelResponse,
    ChannelSendResult,
    ChannelWorkerContext,
)


class MailboxDriver(ChannelDriver):
    async def start(self, ch: ChannelWorkerContext) -> None:
        await ch.storage.awrite_json("status.json", {"connected": True})
        await ch.report_status("connected")

    async def send(
        self,
        ch: ChannelWorkerContext,
        response: ChannelResponse,
    ) -> ChannelSendResult:
        step = await ch.delivery.prepare_step("write-mailbox")
        if step.completed and step.result is not None:
            return step.result
        key = hashlib.sha256(response.delivery_id.encode()).hexdigest()
        await ch.storage.awrite_json(
            f"outbox/{key}.json",
            {
                "workspace": ch.workspace_id,
                "user": response.target.user_id,
                "session": response.target.session_id,
                "content": [
                    {
                        "type": block.type,
                        "text": block.text,
                        "attachment": (
                            block.attachment.url if block.attachment else None
                        ),
                    }
                    for block in response.content
                ],
            },
        )
        result = ChannelSendResult(key)
        await ch.delivery.record_progress(step, result)
        return result

    async def stop(self, ch: ChannelWorkerContext) -> None:
        await ch.storage.awrite_json("status.json", {"connected": False})
