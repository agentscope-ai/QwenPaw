# -*- coding: utf-8 -*-
"""PyVoIP backend -- pure-Python SIP/RTP for local dev.

**Dev / local mode only.**  Single-concurrency, no jitter
buffer, no NAT traversal.
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Optional

from .backend import CallEndedCallback, IncomingCallCallback

logger = logging.getLogger(__name__)


class PyVoIPBackend:
    """SipBackend backed by pyVoIP 1.6.x."""

    def __init__(
        self,
        server: str,
        port: int,
        username: str,
        password: str,
        *,
        bind_ip: str = "0.0.0.0",
        sip_port: int = 5060,
        rtp_port_low: int = 10000,
        rtp_port_high: int = 20000,
    ) -> None:
        self._server = server
        self._port = port
        self._username = username
        self._password = password
        self._bind_ip = bind_ip
        self._sip_port = sip_port
        self._rtp_port_low = rtp_port_low
        self._rtp_port_high = rtp_port_high

        self._phone: Any = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._active_calls: dict[str, Any] = {}

        self.on_incoming_call: Optional[IncomingCallCallback] = None
        self.on_call_ended: Optional[CallEndedCallback] = None

    # ----------------------------------------------------------
    # Lifecycle
    # ----------------------------------------------------------

    async def start(self) -> None:
        from pyVoIP.VoIP import VoIPPhone

        self._loop = asyncio.get_running_loop()
        self._phone = VoIPPhone(
            self._server,
            self._port,
            self._username,
            self._password,
            callCallback=self._on_call,
            myIP=self._bind_ip,
            sipPort=self._sip_port,
            rtpPortLow=self._rtp_port_low,
            rtpPortHigh=self._rtp_port_high,
        )
        try:
            await asyncio.to_thread(self._phone.start)
        except OSError as e:
            if "Address already in use" in str(e):
                raise RuntimeError(
                    f"SIP port {self._sip_port} already in use. "
                    "If multiple agents use SIP, configure a "
                    "unique 'sip_port' for each agent.",
                ) from e
            raise
        logger.info(
            "PyVoIP started: %s@%s:%s (sip_port=%s)",
            self._username,
            self._server,
            self._port,
            self._sip_port,
        )

    async def stop(self) -> None:
        if self._phone is not None:
            await asyncio.to_thread(self._phone.stop)
            self._phone = None
        self._active_calls.clear()
        logger.info("PyVoIP backend stopped")

    # ----------------------------------------------------------
    # Audio playback
    # ----------------------------------------------------------

    async def play_audio(
        self,
        call_id: str,
        audio: bytes,
    ) -> None:
        call = self._active_calls.get(call_id)
        if call is None:
            logger.warning(
                "play_audio: unknown call %s",
                call_id,
            )
            return
        await asyncio.to_thread(call.write_audio, audio)

    # ----------------------------------------------------------
    # pyVoIP call callback (runs in pyVoIP's thread)
    # ----------------------------------------------------------

    def _on_call(self, call: Any) -> None:
        """Called by pyVoIP when a new call arrives."""
        from pyVoIP.VoIP import CallState, InvalidStateError

        try:
            call.answer()
        except InvalidStateError:
            logger.debug("Call ended before answer")
            return

        call_id = self._extract_call_id(call)
        from_uri = self._extract_header(
            call,
            "From",
            "unknown",
        )
        to_uri = self._extract_header(call, "To", "")

        self._active_calls[call_id] = call

        audio_queue: asyncio.Queue = asyncio.Queue()

        async def _write_audio(data: bytes) -> None:
            c = self._active_calls.get(call_id)
            if c is not None:
                await asyncio.to_thread(
                    c.write_audio,
                    data,
                )

        if self.on_incoming_call and self._loop:
            asyncio.run_coroutine_threadsafe(
                self.on_incoming_call(
                    call_id,
                    from_uri,
                    to_uri,
                    audio_queue,
                    _write_audio,
                ),
                self._loop,
            )

        # Read audio in pyVoIP's thread
        try:
            while call.state == CallState.ANSWERED:
                try:
                    pcm = call.read_audio(
                        length=160,
                        blocking=False,
                    )
                except InvalidStateError:
                    break
                if pcm and self._loop:
                    self._loop.call_soon_threadsafe(
                        audio_queue.put_nowait,
                        pcm,
                    )
                time.sleep(0.018)
        except Exception:
            logger.debug(
                "read_audio loop error: %s",
                call_id,
                exc_info=True,
            )
        finally:
            if self._loop:
                self._loop.call_soon_threadsafe(
                    audio_queue.put_nowait,
                    None,
                )
            self._active_calls.pop(call_id, None)
            if self.on_call_ended and self._loop:
                asyncio.run_coroutine_threadsafe(
                    self.on_call_ended(call_id),
                    self._loop,
                )

        try:
            if call.state == CallState.ANSWERED:
                call.hangup()
        except InvalidStateError:
            pass

    # ----------------------------------------------------------
    # Helpers
    # ----------------------------------------------------------

    @staticmethod
    def _extract_call_id(call: Any) -> str:
        req = getattr(call, "request", None)
        if req is not None:
            headers = getattr(req, "headers", {})
            cid = headers.get("Call-ID", "")
            if isinstance(cid, list):
                cid = cid[0] if cid else ""
            if cid:
                return str(cid)
        return str(id(call))

    @staticmethod
    def _extract_header(
        call: Any,
        header: str,
        default: str,
    ) -> str:
        req = getattr(call, "request", None)
        if req is not None:
            headers = getattr(req, "headers", {})
            val = headers.get(header, default)
            if isinstance(val, list):
                val = val[0] if val else default
            return str(val)
        return default
