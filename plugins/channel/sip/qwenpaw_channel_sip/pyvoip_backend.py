# -*- coding: utf-8 -*-
"""pyVoIP dev backend. Native readers and callbacks remain worker owned."""
from __future__ import annotations

import asyncio
import concurrent.futures
from collections import deque
import threading
import time

from .backend import SIPPlatformError
from .runtime import ResourceClaim, run_native

_AUDIO_QUEUE_MAX_FRAMES = 150


def _put_latest_audio(queue, frame):
    if queue.full():
        try:
            queue.get_nowait()
        except asyncio.QueueEmpty:
            pass
    queue.put_nowait(frame)


class _ThreadAudioBridge:
    """At most one queued loop callback and 150 pending native PCM frames."""

    def __init__(self, loop, target):
        self.loop, self.target = loop, target
        self.frames = deque(maxlen=_AUDIO_QUEUE_MAX_FRAMES)
        self.guard = threading.Lock()
        self.scheduled = False

    def put(self, frame):
        with self.guard:
            self.frames.append(frame)
            if self.scheduled:
                return
            self.scheduled = True
        self.loop.call_soon_threadsafe(self.drain)

    def drain(self):
        with self.guard:
            frames = tuple(self.frames)
            self.frames.clear()
            self.scheduled = False
        for frame in frames:
            _put_latest_audio(self.target, frame)


class PyVoIPBackend:
    def __init__(
        self,
        server,
        port,
        username,
        password,
        *,
        bind_ip="0.0.0.0",
        sip_port=5060,
        rtp_port_low=10000,
        rtp_port_high=20000,
    ):
        self._server, self._port = server, port
        self._username, self._password = username, password
        self._bind_ip, self._sip_port = bind_ip, sip_port
        self._rtp_port_low, self._rtp_port_high = rtp_port_low, rtp_port_high
        self._phone = None
        self._claim = None
        self._loop = None
        self._running = False
        self._active_calls = {}
        self._readers = set()
        self._callbacks = set()
        self._guard = threading.Lock()
        self.max_calls = 5
        self.on_incoming_call = None
        self.on_call_ended = None
        self.on_state_changed = None

    async def start(self):
        from ._audioop_compat import audioop

        if audioop is None:
            raise RuntimeError("SIP_AUDIOOP_UNAVAILABLE")
        from pyVoIP.VoIP import VoIPPhone

        self._loop = asyncio.get_running_loop()
        self._claim = ResourceClaim(
            "sip://localhost:" + str(self._sip_port),
            "dev-listener",
            reason_code="SIP_PORT_ALREADY_IN_USE",
        )
        self._claim.acquire()
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
        self._running = True
        try:
            await run_native(self._phone.start)
        except OSError as exc:
            self._running = False
            if getattr(exc, "errno", None) in {
                48,
                98,
                10048,
            } or "Address already in use" in str(exc):
                raise RuntimeError("SIP_PORT_ALREADY_IN_USE") from exc
            raise
        if self.on_state_changed:
            await self.on_state_changed("connected")

    def _submit(self, coroutine):
        future = asyncio.run_coroutine_threadsafe(coroutine, self._loop)
        with self._guard:
            self._callbacks.add(future)

        def done(completed):
            if completed.cancelled() or completed.exception() is None:
                with self._guard:
                    self._callbacks.discard(completed)
            else:
                self._running = False

        future.add_done_callback(done)
        return future

    def quiesce(self):
        self._running = False

    async def stop(self):
        self._running = False
        with self._guard:
            calls = list(self._active_calls.values())
        failures = []
        for call in calls:
            try:
                await self._hangup(call)
            except Exception as exc:
                failures.append(exc)
        if self._phone is not None:
            try:
                await run_native(self._phone.stop)
            except Exception as exc:
                failures.append(exc)
            else:
                self._phone = None
        # Callbacks need the event loop while each native reader settles.
        with self._guard:
            readers = list(self._readers)
        for thread in readers:
            if thread is not threading.current_thread():
                await run_native(thread.join)
        with self._guard:
            callbacks = list(self._callbacks)
        if callbacks:
            results = await asyncio.gather(
                *(asyncio.wrap_future(f) for f in callbacks),
                return_exceptions=True,
            )
            failures.extend(
                r
                for r in results
                if isinstance(r, BaseException)
                and not isinstance(
                    r,
                    (
                        asyncio.CancelledError,
                        concurrent.futures.CancelledError,
                    ),
                )
            )
        if failures:
            raise RuntimeError("SIP_BACKEND_STOP_INCOMPLETE") from failures[0]
        with self._guard:
            self._callbacks.clear()
            if self._active_calls or self._readers:
                raise RuntimeError("SIP_READERS_REMAIN")
        if self._claim is not None:
            self._claim.close()
            self._claim = None

    async def _hangup(self, call):
        from pyVoIP.VoIP import InvalidStateError

        try:
            await run_native(call.hangup)
        except InvalidStateError:
            pass  # The native call already ended.

    async def hangup(self, call_id):
        with self._guard:
            call = self._active_calls.get(call_id)
        if call is not None:
            await self._hangup(call)

    async def play_audio(self, call_id, audio):
        with self._guard:
            call = self._active_calls.get(call_id)
        if call is None or not self._running:
            raise SIPPlatformError("CALL_CLOSED")
        await run_native(call.write_audio, audio)

    def _on_call(self, call):
        from pyVoIP.VoIP import CallState, InvalidStateError

        call_id = self._extract_call_id(call)
        thread = threading.current_thread()
        with self._guard:
            allowed = (
                self._running
                and call_id not in self._active_calls
                and (
                    self.max_calls <= 0
                    or len(self._active_calls) < self.max_calls
                )
            )
            if allowed:
                self._active_calls[call_id] = call
                self._readers.add(thread)
        if not allowed:
            try:
                call.hangup()
            except InvalidStateError:
                pass
            return
        audio_queue = asyncio.Queue(maxsize=_AUDIO_QUEUE_MAX_FRAMES)
        bridge = _ThreadAudioBridge(self._loop, audio_queue)

        async def write_audio(data):
            with self._guard:
                current = self._active_calls.get(call_id) is call
            if (
                not self._running
                or not current
                or call.state != CallState.ANSWERED
            ):
                raise SIPPlatformError("CALL_CLOSED")
            # Captures this native call, never a future call with the same ID.
            await run_native(call.write_audio, data)

        incoming = None
        ended = None
        try:
            call.answer()
            if self.on_incoming_call:
                incoming = self._submit(
                    self.on_incoming_call(
                        call_id,
                        self._extract_header(call, "From", "unknown"),
                        self._extract_header(call, "To", ""),
                        audio_queue,
                        write_audio,
                    ),
                )
            while self._running and call.state == CallState.ANSWERED:
                pcm = call.read_audio(length=160, blocking=False)
                if pcm:
                    bridge.put(pcm)
                time.sleep(0.018)
        except InvalidStateError:
            pass
        finally:
            bridge.put(None)
            if self.on_call_ended:
                ended = self._submit(self.on_call_ended(call_id))
            # Keep the ID reserved until loop callbacks finish. Reusing it
            # cannot make an old end callback terminate the replacement call.
            try:
                for future in (incoming, ended):
                    if future is not None:
                        future.result()
            finally:
                with self._guard:
                    if self._active_calls.get(call_id) is call:
                        self._active_calls.pop(call_id)
                    self._readers.discard(thread)

    @staticmethod
    def _extract_call_id(call):
        req = getattr(call, "request", None)
        if req is not None:
            value = getattr(req, "headers", {}).get("Call-ID", "")
            if isinstance(value, list):
                value = value[0] if value else ""
            if value:
                return str(value)
        return str(id(call))

    @staticmethod
    def _extract_header(call, header, default):
        req = getattr(call, "request", None)
        if req is not None:
            value = getattr(req, "headers", {}).get(header, default)
            if isinstance(value, list):
                value = value[0] if value else default
            return str(value)
        return default
