# -*- coding: utf-8 -*-
"""SIP call/audio custody. Only transcripts and completed text cross IPC."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from types import SimpleNamespace
import uuid

from .backend import SIPPlatformError
from .runtime import cancel_tasks


@dataclass
class CallBinding:
    call_id: str
    from_uri: str
    to_uri: str
    audio_in: object
    write_audio: object
    connection_epoch: str = field(default_factory=lambda: uuid.uuid4().hex)
    turn_id: int = 0
    abort: asyncio.Event = field(default_factory=asyncio.Event)
    play_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    tts_tasks: set = field(default_factory=set)
    reader: object = None
    timeout: object = None
    setup: object = None
    stt: object = None
    closing: bool = False
    cleanup_error: object = None
    cleanup_task: object = None
    cleanup_done: object = None

    @property
    def session_id(self):
        return "sip:" + self.call_id

    def route(self):
        return {
            "call_id": self.call_id,
            "connection_epoch": self.connection_epoch,
            "turn_id": str(self.turn_id),
        }


class SIPPlatform:
    _FRAME_DEV = 160
    _FRAME_LK = 960

    def __init__(self):
        self.backend = self._registrar = None
        self._calls = {}
        self._tasks = set()
        self._accepting = False
        self._on_transcript = self._state_changed = self._diagnostic = None

    async def start(self, config, on_transcript, state_changed, diagnostic):
        from .helpers import _create_backend, _create_backend_for_builtin

        self._config = SimpleNamespace(**config)
        self._on_transcript, self._state_changed, self._diagnostic = (
            on_transcript,
            state_changed,
            diagnostic,
        )
        cfg = self._config
        if cfg.sip_mode == "dev" and not cfg.sip_server:
            from .mini_registrar import MiniRegistrar

            self._registrar = MiniRegistrar(bind="127.0.0.1", port=5060)
            await self._registrar.start()
            self.backend = _create_backend_for_builtin(cfg)
        else:
            self.backend = _create_backend(cfg)
        self.backend.max_calls = cfg.max_concurrent_calls
        self.backend.on_incoming_call = self._incoming
        self.backend.on_call_ended = self._ended
        self.backend.on_state_changed = self._backend_state
        self._accepting = True
        try:
            await self.backend.start()
        except BaseException:
            self._accepting = False
            self.backend.quiesce()
            raise

    async def _backend_state(self, state):
        if self._accepting:
            await self._state_changed(state)

    def current(self, route):
        call = self._calls.get(route.get("call_id"))
        if (
            not self._accepting
            or call is None
            or call.closing
            or call.connection_epoch != route.get("connection_epoch")
            or str(call.turn_id) != route.get("turn_id")
            or call.abort.is_set()
        ):
            raise SIPPlatformError("CALL_CLOSED")
        return call

    def begin_turn(self, call):
        if (
            not self._accepting
            or self._calls.get(call.call_id) is not call
            or call.closing
        ):
            raise SIPPlatformError("CALL_CLOSED")
        self._interrupt(call)
        call.turn_id += 1
        call.abort = asyncio.Event()  # Each old TTS keeps its original Event.
        self._reset_timeout(call)
        return call.route()

    def target(self, call_id):
        call = self._calls.get(call_id)
        if call is None:
            raise SIPPlatformError("OUTBOUND_TARGET_UNKNOWN")
        return self.begin_turn(call)

    def _interrupt(self, call):
        call.abort.set()
        for task in tuple(call.tts_tasks):
            if not task.done():
                task.cancel()

    async def _incoming(
        self,
        call_id,
        from_uri,
        to_uri,
        audio_in,
        write_audio,
    ):
        limit = self._config.max_concurrent_calls
        if (
            not self._accepting
            or call_id in self._calls
            or (limit > 0 and len(self._calls) >= limit)
        ):
            await self.backend.hangup(call_id)
            return
        from .stt_tts import create_stt_engine

        call = CallBinding(call_id, from_uri, to_uri, audio_in, write_audio)
        self._calls[call_id] = call
        call.setup = asyncio.current_task()
        try:
            call.stt = create_stt_engine(
                self._config.stt_provider,
                self._config.language,
                self._config.dashscope_api_key,
            )
            call.stt.on_speech_start = (
                lambda: self._interrupt(call)
                if self._calls.get(call_id) is call and not call.closing
                else None
            )
            call.stt.on_transcript = lambda text: self._transcript(call, text)
            call.stt.on_error = lambda reason: self._fatal(call, reason)
            try:
                await call.stt.start()
            except Exception:
                try:
                    await self.play(call.route(), "语音服务暂时不可用，请稍后再试。")
                finally:
                    await self._end_call(call, hangup=True)
                return
            if call.closing or not self._accepting:
                return
            call.reader = asyncio.create_task(self._audio_reader(call))
            if self._config.welcome_greeting:
                try:
                    await self.play(
                        call.route(),
                        self._config.welcome_greeting,
                    )
                except SIPPlatformError as exc:
                    if exc.reason_code not in {
                        "CALL_INTERRUPTED",
                        "CALL_CLOSED",
                    }:
                        await self._diagnostic("SIP_WELCOME_FAILED")
            if self._calls.get(call_id) is call and not call.closing:
                self._reset_timeout(call)
        except asyncio.CancelledError:
            raise
        except Exception:
            await self._fatal(call, "SIP_CALL_SETUP_FAILED")
        finally:
            if call.setup is asyncio.current_task():
                call.setup = None

    async def _transcript(self, call, text):
        if (
            not text
            or not text.strip()
            or call.closing
            or self._calls.get(call.call_id) is not call
        ):
            return
        route = self.begin_turn(call)
        try:
            await self._on_transcript(call, route, text)
        except SIPPlatformError as exc:
            await self._fatal(call, exc.reason_code)
        except Exception:
            await self._fatal(call, "SIP_TRANSCRIPT_DELIVERY_FAILED")

    async def _fatal(self, call, reason):
        try:
            await self._end_call(call, hangup=True)
        finally:
            await self._diagnostic(reason)

    async def _audio_reader(self, call):
        from .helpers import _pcm_48k16bit_to_16k16bit, _pcm_8k8bit_to_16k16bit

        errors = 0
        while not call.closing:
            frame = await call.audio_in.get()
            if frame is None:
                await self._end_call(call, hangup=True)
                return
            try:
                pcm = (
                    _pcm_48k16bit_to_16k16bit(frame)
                    if self._config.sip_mode == "livekit"
                    else _pcm_8k8bit_to_16k16bit(frame)
                )
                await call.stt.feed_audio(pcm)
                errors = 0
            except asyncio.CancelledError:
                raise
            except Exception:
                errors += 1
                if errors >= 20:
                    await self._fatal(call, "SIP_AUDIO_FEED_FAILED")
                    return

    def _track_task(self, task):
        if task in self._tasks:
            return
        self._tasks.add(task)

        def done(completed):
            if completed.cancelled() or completed.exception() is None:
                self._tasks.discard(completed)
            else:
                self._accepting = False

        task.add_done_callback(done)

    def _reset_timeout(self, call):
        if call.timeout is not None:
            call.timeout.cancel()
            self._track_task(call.timeout)
        if self._config.call_timeout > 0:
            call.timeout = asyncio.create_task(self._timeout(call))
        else:
            call.timeout = None
        for task in tuple(self._tasks):
            if task.done():
                if not task.cancelled() and task.exception() is not None:
                    continue
                self._tasks.discard(task)

    async def _timeout(self, call):
        await asyncio.sleep(self._config.call_timeout)
        await self._end_call(call, hangup=True)

    async def play(self, route, text):
        from .helpers import _clean_for_tts, _pcm16_to_pyvoip
        from .stt_tts import synthesize_tts_stream

        call = self.current(route)
        abort = call.abort
        text = _clean_for_tts(text)
        if not text:
            return
        wrote = False

        async def speak():
            nonlocal wrote
            async with call.play_lock:
                self.current(route)
                is_dev = self._config.sip_mode != "livekit"
                sr = 8000 if is_dev else 24000
                size = self._FRAME_DEV if is_dev else self._FRAME_LK
                buffer = b""
                stream = synthesize_tts_stream(
                    self._config.tts_provider,
                    text,
                    self._config.tts_voice,
                    self._config.dashscope_api_key,
                    sample_rate=sr,
                )

                async def write(frame):
                    nonlocal wrote
                    self.current(route)
                    if abort.is_set():
                        raise SIPPlatformError(
                            "CALL_INTERRUPTED",
                            side_effect_possible=wrote,
                        )
                    prior_wrote = wrote
                    wrote = True
                    try:
                        await call.write_audio(frame)
                    except SIPPlatformError as exc:
                        # The native closure can prove it rejected before
                        # its first effect. Prior audio still stays unknown.
                        wrote = prior_wrote or exc.side_effect_possible
                        raise

                try:
                    async for chunk in stream:
                        if abort.is_set():
                            raise SIPPlatformError(
                                "CALL_INTERRUPTED",
                                side_effect_possible=wrote,
                            )
                        self.current(route)
                        buffer += _pcm16_to_pyvoip(chunk) if is_dev else chunk
                        while len(buffer) >= size:
                            await write(buffer[:size])
                            buffer = buffer[size:]
                            if is_dev:
                                await asyncio.sleep(0.02)
                    if buffer:
                        await write(buffer)
                finally:
                    await stream.aclose()

        task = asyncio.create_task(speak())
        call.tts_tasks.add(task)
        try:
            await asyncio.shield(task)
            return wrote
        except asyncio.CancelledError:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            if asyncio.current_task().cancelling():
                raise
            raise SIPPlatformError(
                "CALL_INTERRUPTED",
                side_effect_possible=wrote,
            ) from None
        except SIPPlatformError as exc:
            raise SIPPlatformError(
                exc.reason_code,
                side_effect_possible=wrote or exc.side_effect_possible,
            ) from exc
        except Exception as exc:
            raise SIPPlatformError(
                "SIP_TTS_PLAYBACK_FAILED",
                side_effect_possible=wrote,
            ) from exc
        finally:
            if task.done():
                call.tts_tasks.discard(task)

    async def _ended(self, call_id):
        call = self._calls.get(call_id)
        if call is not None:
            await self._end_call(call)

    async def _end_call(self, call, *, hangup=False):
        if call.closing and call.cleanup_error is None:
            if (
                call.cleanup_task is not asyncio.current_task()
                and call.cleanup_done is not None
            ):
                error = await asyncio.shield(call.cleanup_done)
                if error is not None:
                    raise RuntimeError("SIP_CALL_STOP_INCOMPLETE") from error
            return
        call.cleanup_task = asyncio.current_task()
        completion = asyncio.get_running_loop().create_future()
        call.cleanup_done = completion
        call.closing = True
        call.cleanup_error = None
        try:
            await self._cleanup_call(call, hangup=hangup)
        except BaseException as exc:
            call.cleanup_error = exc
            raise
        finally:
            # A native reader may await this while close() later joins it.
            # Complete this call's cleanup, not the enclosing stop task.
            completion.set_result(call.cleanup_error)
            call.cleanup_task = None

    async def _cleanup_call(self, call, *, hangup):
        self._interrupt(call)
        failures = []
        try:
            await cancel_tasks(
                [
                    t
                    for t in (
                        call.setup,
                        call.reader,
                        call.timeout,
                        *call.tts_tasks,
                    )
                    if t is not None
                ],
            )
        except Exception as exc:
            failures.append(exc)
        if call.stt is not None:
            try:
                await call.stt.stop()
            except Exception as exc:
                failures.append(exc)
            else:
                for name in ("_dispatch_task", "_error_task"):
                    task = getattr(call.stt, name, None)
                    if task is asyncio.current_task():
                        self._track_task(task)
                call.stt = None
        if hangup and self.backend is not None:
            try:
                await self.backend.hangup(call.call_id)
            except Exception as exc:
                failures.append(exc)
        if failures:
            call.cleanup_error = failures[0]
            raise RuntimeError("SIP_CALL_STOP_INCOMPLETE") from failures[0]
        if self._calls.get(call.call_id) is call:
            self._calls.pop(call.call_id)

    async def close(self):
        self._accepting = False
        if self.backend is not None:
            self.backend.quiesce()
        for call in self._calls.values():
            self._interrupt(call)
        failures = []
        for call in list(self._calls.values()):
            try:
                await self._end_call(call)
            except Exception as exc:
                failures.append(exc)
        try:
            await cancel_tasks(self._tasks)
        except Exception as exc:
            failures.append(exc)
        if self.backend is not None:
            try:
                await self.backend.stop()
            except Exception as exc:
                failures.append(exc)
            else:
                self.backend = None
        if self._registrar is not None:
            try:
                await self._registrar.stop()
            except Exception as exc:
                failures.append(exc)
            else:
                self._registrar = None
        if failures or self._calls:
            raise RuntimeError("SIP_PLATFORM_STOP_INCOMPLETE") from (
                failures[0] if failures else None
            )
        self._tasks.clear()
