# -*- coding: utf-8 -*-
"""Twilio API wrapper for the Voice channel."""
from __future__ import annotations

import asyncio
import logging
from functools import partial

logger = logging.getLogger(__name__)


class TwilioManager:
    """Async wrapper around the synchronous ``twilio`` Python SDK."""

    def __init__(self, account_sid: str, auth_token: str) -> None:
        self._account_sid = account_sid
        self._auth_token = auth_token
        self._client = None  # lazy init

    def _get_client(self):
        if self._client is None:
            from twilio.rest import Client

            self._client = Client(self._account_sid, self._auth_token)
        return self._client

    async def _run_sync(self, fn, *args, **kwargs):
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, partial(fn, *args, **kwargs))

    async def configure_voice_webhook(
        self,
        phone_number_sid: str,
        webhook_url: str,
        status_callback_url: str = "",
    ) -> None:
        """Update the voice webhook URL on an existing phone number."""
        client = self._get_client()

        def _configure():
            kwargs = {
                "voice_url": webhook_url,
                "voice_method": "POST",
            }
            if status_callback_url:
                kwargs["status_callback"] = status_callback_url
                kwargs["status_callback_method"] = "POST"
            client.incoming_phone_numbers(phone_number_sid).update(
                **kwargs,
            )

        await asyncio.wait_for(self._run_sync(_configure), timeout=30)
        logger.info(
            "Twilio webhook configured: sid=%s url=%s",
            phone_number_sid,
            webhook_url,
        )
