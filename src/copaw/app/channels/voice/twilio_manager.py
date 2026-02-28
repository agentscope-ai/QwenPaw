# -*- coding: utf-8 -*-
"""Twilio API wrapper for the Voice channel."""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from functools import partial
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class AvailableNumber:
    phone_number: str
    friendly_name: str
    locality: str
    region: str
    country: str


@dataclass
class ProvisionedNumber:
    sid: str
    phone_number: str
    friendly_name: str


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

    async def validate_credentials(self) -> bool:
        """Check if the Twilio credentials are valid."""
        try:
            client = self._get_client()
            await self._run_sync(client.api.accounts(self._account_sid).fetch)
            return True
        except Exception:
            logger.exception("Twilio credential validation failed")
            return False

    async def search_available_numbers(
        self,
        country: str = "US",
        area_code: Optional[str] = None,
    ) -> list[AvailableNumber]:
        """Search for available phone numbers."""
        client = self._get_client()

        def _search():
            kwargs = {"limit": 10}
            if area_code:
                kwargs["area_code"] = area_code
            numbers = client.available_phone_numbers(country).local.list(
                **kwargs,
            )
            return [
                AvailableNumber(
                    phone_number=n.phone_number,
                    friendly_name=n.friendly_name,
                    locality=getattr(n, "locality", ""),
                    region=getattr(n, "region", ""),
                    country=country,
                )
                for n in numbers
            ]

        return await self._run_sync(_search)

    async def provision_number(
        self,
        phone_number: str,
        voice_url: str,
    ) -> ProvisionedNumber:
        """Purchase a phone number and configure its voice webhook."""
        client = self._get_client()

        def _provision():
            number = client.incoming_phone_numbers.create(
                phone_number=phone_number,
                voice_url=voice_url,
                voice_method="POST",
            )
            return ProvisionedNumber(
                sid=number.sid,
                phone_number=number.phone_number,
                friendly_name=number.friendly_name,
            )

        return await self._run_sync(_provision)

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

        await self._run_sync(_configure)
        logger.info(
            "Twilio webhook configured: sid=%s url=%s",
            phone_number_sid,
            webhook_url,
        )
