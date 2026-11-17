# -*- coding: utf-8 -*-
"""MQTT transport implemented against the public process-channel SDK."""

from dataclasses import replace

from qwenpaw.plugins.channel_workers import (
    ChannelDeliveryError,
    ChannelDriver,
    ChannelSendResult,
    ResponsePolicy,
)
from qwenpaw.plugins.channels import ChannelMessage
from qwenpaw.plugins.messages import ContentBlock

from .platform import MQTTDeliveryError, MQTTPlatform


class MQTTDriver(ChannelDriver):
    response_policy = ResponsePolicy(configured_prefix=False)

    def __init__(self):
        self._platform = None

    async def start(self, ch):
        async def receive(value):
            sender = value["sender"]
            await ch.receive(
                ChannelMessage(
                    sender_id=sender,
                    content=(ContentBlock(text=value["text"]),),
                    session_id="mqtt:" + sender,
                    reply_to=sender,
                    message_id=value["event_id"],
                    metadata={
                        "topic": value["topic"],
                        "client_id": sender,
                        "raw_payload": value["payload"],
                    },
                ),
            )

        self._platform = MQTTPlatform(
            dict(ch.config),
            receive,
            ch.report_status,
            ch.resources,
        )
        ch.resources.defer(self._platform.stop, "MQTT client shutdown")
        await ch.report_status("connecting")
        try:
            await self._platform.start()
        except BaseException:
            await ch.report_status("failed")
            raise

    async def resolve_target(self, ch, target):
        client_id = target.metadata.get("client_id")
        session = target.session_id or target.metadata.get("session_id")
        if not client_id:
            if session and session.startswith("mqtt:"):
                client_id = session.split(":", 1)[1]
            elif target.key.startswith("mqtt:"):
                client_id = target.key.split(":", 1)[1]
            else:
                client_id = target.user_id or target.key
        if not client_id:
            raise ValueError("OUTBOUND_TARGET_UNKNOWN")
        return replace(target, key=str(client_id))

    async def send(self, ch, response):
        if response.operation != "message.create":
            raise ChannelDeliveryError(
                "OPERATION_UNSUPPORTED",
                side_effect_possible=False,
            )
        parts = []
        for block in response.content:
            part = {"type": block.type}
            if block.type == "text":
                part["text"] = block.text
            elif block.attachment is not None:
                part[block.type + "_url"] = block.attachment.url
            parts.append(part)
        try:
            result = await self._platform.publish_parts(
                response.target.key,
                parts,
            )
        except MQTTDeliveryError as exc:
            raise ChannelDeliveryError(
                exc.reason_code,
                side_effect_possible=exc.side_effect_possible,
                retryable=exc.retryable,
            ) from exc
        return ChannelSendResult(result["message_id"])

    async def stop(self, ch):
        if self._platform is not None:
            await self._platform.stop()
