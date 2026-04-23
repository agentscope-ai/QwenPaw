# -*- coding: utf-8 -*-
"""SipBackend Protocol -- abstraction for Dev / Production.

* **PyVoIPBackend** (``sip_mode="dev"``)
* **LiveKitBackend** (``sip_mode="livekit"``)
"""
from __future__ import annotations

import asyncio
from typing import (
    Any,
    Callable,
    Coroutine,
    Optional,
    Protocol,
    runtime_checkable,
)

IncomingCallCallback = Callable[
    [
        str,
        str,
        str,
        asyncio.Queue,
        Callable[[bytes], Coroutine[Any, Any, None]],
    ],
    Coroutine[Any, Any, None],
]

CallEndedCallback = Callable[
    [str],
    Coroutine[Any, Any, None],
]


@runtime_checkable
class SipBackend(Protocol):
    """Pluggable SIP/RTP backend."""

    on_incoming_call: Optional[IncomingCallCallback]
    on_call_ended: Optional[CallEndedCallback]

    async def start(self) -> None:
        """Start the backend."""

    async def stop(self) -> None:
        """Stop the backend."""

    async def play_audio(
        self,
        call_id: str,
        audio: bytes,
    ) -> None:
        """Send raw PCM audio to the caller."""
