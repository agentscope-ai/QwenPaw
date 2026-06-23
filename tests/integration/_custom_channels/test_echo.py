# -*- coding: utf-8 -*-
"""Minimal custom channel for integration testing.

Dropped into ``<working_dir>/custom_channels/`` by the test fixture.
The channel registry auto-discovers it and exposes it as channel type
``test_echo``.  Outbound ``send()`` POSTs to a callback URL so the
test process can verify the message pipeline end-to-end.
"""
from __future__ import annotations

import logging
import os
from typing import Any, Optional

from qwenpaw.app.channels.base import BaseChannel

logger = logging.getLogger(__name__)


class IntegEchoChannel(BaseChannel):
    channel = "test_echo"

    async def start(self) -> None:
        logger.info("test_echo channel started")

    async def stop(self) -> None:
        logger.info("test_echo channel stopped")

    async def send(  # pylint: disable=unused-argument
        self,
        to_handle: str,
        text: str,
        meta: Optional[dict[str, Any]] = None,
    ) -> None:
        callback = os.environ.get("TEST_CHANNEL_CALLBACK_URL", "")
        if not callback:
            logger.warning("TEST_CHANNEL_CALLBACK_URL not set")
            return
        try:
            import aiohttp

            async with aiohttp.ClientSession() as session:
                await session.post(
                    callback,
                    json={
                        "channel": self.channel,
                        "to": to_handle,
                        "text": text,
                    },
                    timeout=aiohttp.ClientTimeout(total=5),
                )
        except Exception:
            logger.exception("test_echo send failed")

    @classmethod
    def from_config(
        cls,
        process,
        config,  # pylint: disable=unused-argument
        on_reply_sent=None,
        show_tool_details=True,
        filter_tool_messages=False,
        filter_thinking=False,
    ) -> "IntegEchoChannel":
        return cls(
            process=process,
            on_reply_sent=on_reply_sent,
            show_tool_details=show_tool_details,
            filter_tool_messages=filter_tool_messages,
            filter_thinking=filter_thinking,
        )
