# -*- coding: utf-8 -*-
"""Runner-owned Twilio webhook management."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from functools import partial
import logging
from typing import Any

logger = logging.getLogger(__name__)

_DEFAULT_HTTP_TIMEOUT_S = 30.0
_AUTHENTICATION_FAILURE_STATUSES = frozenset({401, 403, 404})


class TwilioAuthenticationError(RuntimeError):
    """Report rejected Twilio credentials or phone-number ownership."""


@dataclass(frozen=True)
class VoiceWebhookSnapshot:
    """Capture the Twilio webhook fields managed by Voice."""

    voice_url: str = ""
    voice_method: str = "POST"
    status_callback: str = ""
    status_callback_method: str = "POST"

    @classmethod
    def from_resource(cls, resource: Any) -> "VoiceWebhookSnapshot":
        """Normalize one IncomingPhoneNumber resource."""
        return cls(
            voice_url=str(getattr(resource, "voice_url", "") or ""),
            voice_method=str(
                getattr(resource, "voice_method", "POST") or "POST",
            ),
            status_callback=str(
                getattr(resource, "status_callback", "") or "",
            ),
            status_callback_method=str(
                getattr(
                    resource,
                    "status_callback_method",
                    "POST",
                )
                or "POST",
            ),
        )

    def to_update_kwargs(self) -> dict[str, str]:
        """Return an exact Twilio update for the captured fields."""
        return {
            "voice_url": self.voice_url,
            "voice_method": self.voice_method,
            "status_callback": self.status_callback,
            "status_callback_method": self.status_callback_method,
        }


class RunnerTwilioManager:
    """Manage Twilio webhook ownership for one Voice Runner."""

    def __init__(
        self,
        account_sid: str,
        auth_token: str,
        *,
        http_timeout_s: float = _DEFAULT_HTTP_TIMEOUT_S,
    ) -> None:
        if http_timeout_s <= 0:
            raise ValueError("Twilio HTTP timeout must be positive")
        self._account_sid = account_sid
        self._auth_token = auth_token
        self._http_timeout_s = http_timeout_s
        self._client = None  # lazy init

    def _get_client(self):
        if self._client is None:
            from twilio.http.http_client import TwilioHttpClient
            from twilio.rest import Client

            http_client = TwilioHttpClient(
                timeout=self._http_timeout_s,
                max_retries=0,
            )
            self._client = Client(
                self._account_sid,
                self._auth_token,
                http_client=http_client,
            )
        return self._client

    async def _run_sync(self, fn, *args, **kwargs):
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, partial(fn, *args, **kwargs))

    async def _settled_sync(self, fn):
        """Wait for one submitted SDK request despite caller cancellation."""
        task = asyncio.create_task(self._run_sync(fn))
        cancellation: asyncio.CancelledError | None = None
        while not task.done():
            try:
                await asyncio.shield(task)
            except asyncio.CancelledError as exc:
                cancellation = exc
        try:
            result = task.result()
        except BaseException:
            if cancellation is not None:
                logger.warning(
                    f"Twilio request settled with "
                    f"{type(task.exception()).__name__} after cancellation",
                )
            raise
        if cancellation is not None:
            raise cancellation
        return result

    async def fetch_voice_webhook(
        self,
        phone_number_sid: str,
    ) -> VoiceWebhookSnapshot:
        """Fetch the exact webhook fields managed by Voice."""
        from twilio.base.exceptions import TwilioRestException

        client = self._get_client()

        def _fetch():
            return client.incoming_phone_numbers(phone_number_sid).fetch()

        try:
            resource = await self._settled_sync(_fetch)
        except TwilioRestException as exc:
            if exc.status not in _AUTHENTICATION_FAILURE_STATUSES:
                raise
            raise TwilioAuthenticationError(
                "Twilio credentials or phone number rejected",
            ) from exc
        return VoiceWebhookSnapshot.from_resource(resource)

    async def apply_voice_webhook(
        self,
        phone_number_sid: str,
        snapshot: VoiceWebhookSnapshot,
    ) -> None:
        """Apply one exact webhook snapshot with bounded settlement."""
        client = self._get_client()

        def _apply():
            client.incoming_phone_numbers(phone_number_sid).update(
                **snapshot.to_update_kwargs(),
            )

        await self._settled_sync(_apply)

    async def close(self) -> None:
        """Release the owned SDK HTTP session after transactions settle."""
        client = self._client
        if client is None:
            return
        session = getattr(client.http_client, "session", None)
        if session is not None:
            await self._settled_sync(session.close)
        self._client = None


__all__ = [
    "RunnerTwilioManager",
    "TwilioAuthenticationError",
    "VoiceWebhookSnapshot",
]
