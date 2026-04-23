# -*- coding: utf-8 -*-
"""SIP voice channel -- dual-track architecture.

Two backend modes via ``SIPChannelConfig.sip_mode``:

* ``"dev"``     -- **PyVoIPBackend**: pure-Python pyVoIP.
* ``"livekit"`` -- **LiveKitBackend**: LiveKit SIP Server.
"""
from __future__ import annotations

import asyncio
import logging
import re as _re
from typing import (
    Any,
    Callable,
    Coroutine,
    Dict,
    Optional,
)

from qwenpaw.config.config import SIPChannelConfig

from ._audioop_compat import audioop  # noqa: F401  # must be first
from ..base import BaseChannel, OnReplySent, ProcessHandler
from .backend import SipBackend
from .session import SIPCallSessionManager
from .stt_tts import create_stt_engine, synthesize_tts, synthesize_tts_stream

logger = logging.getLogger(__name__)

# Type alias for the async write callback
_WriteFn = Callable[
    [bytes],
    Coroutine[Any, Any, None],
]


class SIPChannel(BaseChannel):
    """SIP voice channel backed by a pluggable SipBackend.

    ``uses_manager_queue = False`` because SIP calls are
    long-lived sessions with their own async loop.
    """

    channel = "sip"
    uses_manager_queue = False

    def __init__(
        self,
        process: ProcessHandler,
        on_reply_sent: OnReplySent = None,
        show_tool_details: bool = True,
        filter_tool_messages: bool = False,
        filter_thinking: bool = False,
    ) -> None:
        super().__init__(
            process,
            on_reply_sent,
            show_tool_details,
            filter_tool_messages=filter_tool_messages,
            filter_thinking=filter_thinking,
        )
        self.backend: Optional[SipBackend] = None
        self.session_mgr = SIPCallSessionManager()
        self._config: Optional[SIPChannelConfig] = None
        self._registrar: Optional[Any] = None
        self._call_tasks: dict[str, asyncio.Task] = {}
        self._timeout_tasks: dict[str, asyncio.Task] = {}
        self._write_fns: dict[str, _WriteFn] = {}

    # --------------------------------------------------------------
    # Factory
    # --------------------------------------------------------------

    @classmethod
    def from_config(
        cls,
        process: ProcessHandler,
        config: SIPChannelConfig,
        on_reply_sent: OnReplySent = None,
        show_tool_details: bool = True,
        filter_tool_messages: bool = False,
        filter_thinking: bool = False,
    ) -> "SIPChannel":
        instance = cls(
            process,
            on_reply_sent,
            show_tool_details,
            filter_tool_messages=filter_tool_messages,
            filter_thinking=filter_thinking,
        )
        instance._config = config
        instance.backend = _create_backend(config)
        return instance

    # --------------------------------------------------------------
    # Lifecycle
    # --------------------------------------------------------------

    async def start(self) -> None:
        if not self._config or not self._config.enabled:
            logger.info("SIP channel disabled, skip start")
            return
        if self.backend is None:
            logger.warning("SIP enabled but no backend")
            return

        # Auto-launch built-in registrar for zero-config dev mode
        if self._config.sip_mode == "dev" and not self._config.sip_server:
            await self._start_builtin_registrar()

        self.backend.on_incoming_call = self._on_incoming_call
        self.backend.on_call_ended = self._on_call_ended
        try:
            await self.backend.start()
        except Exception:
            logger.exception("Failed to start SIP backend")
            await self._stop_registrar()
            return
        logger.info(
            "SIP channel started (mode=%s)",
            self._config.sip_mode,
        )

    async def stop(self) -> None:
        for task in list(self._call_tasks.values()):
            task.cancel()
        for task in list(self._timeout_tasks.values()):
            task.cancel()
        self._timeout_tasks.clear()
        for sess in self.session_mgr.active_sessions():
            if sess.stt_engine:
                try:
                    await sess.stt_engine.stop()
                except Exception:
                    logger.debug(
                        "Error stopping STT for %s",
                        sess.call_id,
                        exc_info=True,
                    )
            self.session_mgr.end_session(sess.call_id)
        self._write_fns.clear()
        if self.backend is not None:
            try:
                await self.backend.stop()
            except Exception:
                logger.debug(
                    "Error stopping backend",
                    exc_info=True,
                )
        await self._stop_registrar()
        logger.info("SIP channel stopped")

    async def _start_builtin_registrar(self) -> None:
        """Launch the built-in SIP registrar for zero-config dev."""
        from .mini_registrar import MiniRegistrar

        reg = MiniRegistrar(bind="127.0.0.1", port=5060)
        await reg.start()
        self._registrar = reg

        # Rewire backend to connect to built-in registrar
        self.backend = _create_backend_for_builtin(
            self._config,
        )

        logger.info(
            "[SIP] Quickstart: register your softphone to "
            "127.0.0.1:5060 (user: any, no auth)",
        )
        logger.info(
            "[SIP] Dial 'sip:agent@127.0.0.1:5060' to talk with QwenPaw!",
        )

    async def _stop_registrar(self) -> None:
        """Stop the built-in registrar if running."""
        if self._registrar:
            try:
                await self._registrar.stop()
            except Exception:
                logger.debug(
                    "Error stopping registrar",
                    exc_info=True,
                )
            self._registrar = None

    # --------------------------------------------------------------
    # Sending (TTS playback)
    # --------------------------------------------------------------

    # -- Frame sizes for 20 ms at each backend's expected format --
    # dev (pyVoIP): 8 kHz × 1 byte (8-bit unsigned) × 20 ms = 160
    _FRAME_DEV = 160
    # livekit: 24 kHz × 2 bytes (16-bit signed) × 20 ms = 960
    _FRAME_LK = 960

    async def send(
        self,
        to_handle: str,
        text: str,
        meta: Optional[Dict[str, Any]] = None,
    ) -> None:
        if not text:
            return
        # Strip emoji and non-speech characters that TTS cannot handle
        text = _clean_for_tts(text)
        if not text:
            return
        session = self.session_mgr.get_session(to_handle)
        if session is None or session.status != "active":
            logger.warning(
                "send() inactive/unknown: %s",
                to_handle,
            )
            return
        write_fn = self._write_fns.get(to_handle)
        if write_fn is None:
            logger.warning(
                "send() no write_fn: %s",
                to_handle,
            )
            return
        try:
            cfg = self._config
            is_dev = cfg.sip_mode != "livekit"
            sr = 8000 if is_dev else 24000
            frame_size = self._FRAME_DEV if is_dev else self._FRAME_LK
            abort = session.tts_abort

            buf = b""
            async for chunk in synthesize_tts_stream(
                cfg.tts_provider,
                text,
                cfg.tts_voice,
                cfg.dashscope_api_key,
                sample_rate=sr,
            ):
                if abort.is_set():
                    break
                if is_dev:
                    chunk = _pcm16_to_pyvoip(chunk)
                buf += chunk
                while len(buf) >= frame_size:
                    await write_fn(buf[:frame_size])
                    buf = buf[frame_size:]
                    if is_dev:
                        await asyncio.sleep(0.02)
            if buf and not abort.is_set():
                await write_fn(buf)
        except Exception:
            logger.exception(
                "TTS/playback failed for %s",
                to_handle,
            )

    # --------------------------------------------------------------
    # AgentRequest conversion
    # --------------------------------------------------------------

    def build_agent_request_from_native(
        self,
        native_payload: Any,
    ) -> Any:
        from agentscope_runtime.engine.schemas.agent_schemas import (
            AgentRequest,
            ContentType,
            Message,
            MessageType,
            Role,
            TextContent,
        )

        text = native_payload.get("transcript", "")
        session_id = native_payload.get("session_id", "")
        user_id = native_payload.get("from_uri", "")

        msg = Message(
            type=MessageType.MESSAGE,
            role=Role.USER,
            content=[
                TextContent(type=ContentType.TEXT, text=text),
            ],
        )
        return AgentRequest(
            session_id=session_id,
            user_id=user_id,
            input=[msg],
            channel=self.channel,
        )

    # --------------------------------------------------------------
    # Backend callbacks
    # --------------------------------------------------------------

    async def _on_incoming_call(
        self,
        call_id: str,
        from_uri: str,
        to_uri: str,
        audio_in: asyncio.Queue,
        write_audio: _WriteFn,
    ) -> None:
        """Called when a new call is answered."""
        limit = self._config.max_concurrent_calls
        if 0 < limit <= self.session_mgr.active_count():
            logger.warning(
                "Rejecting call %s: at capacity (%d)",
                call_id,
                limit,
            )
            return
        cfg = self._config
        stt_engine = create_stt_engine(
            cfg.stt_provider,
            cfg.language,
            cfg.dashscope_api_key,
        )

        session = self.session_mgr.create_session(
            call_id=call_id,
            from_uri=from_uri,
            to_uri=to_uri,
        )
        session.status = "active"
        session.stt_engine = stt_engine
        self._write_fns[call_id] = write_audio

        stt_engine.on_transcript = lambda t: self._on_transcript(call_id, t)
        stt_engine.on_speech_start = lambda: self._on_speech_start(call_id)

        try:
            await stt_engine.start()
        except Exception:
            logger.exception(
                "Failed to start STT for %s",
                call_id,
            )
            # Best-effort: tell the caller before hanging up
            try:
                cfg = self._config
                is_dev = cfg.sip_mode != "livekit"
                sr = 8000 if is_dev else 24000
                err_msg = "语音服务暂时不可用，请稍后再试。"
                buf = b""
                async for chunk in synthesize_tts_stream(
                    cfg.tts_provider,
                    err_msg,
                    cfg.tts_voice,
                    cfg.dashscope_api_key,
                    sample_rate=sr,
                ):
                    if is_dev:
                        chunk = _pcm16_to_pyvoip(chunk)
                    buf += chunk
                if buf:
                    await write_audio(buf)
            except Exception:
                logger.debug(
                    "Failed to play error prompt for %s",
                    call_id,
                    exc_info=True,
                )
            self.session_mgr.end_session(call_id)
            self._write_fns.pop(call_id, None)
            return

        task = asyncio.create_task(
            self._audio_reader(
                call_id,
                audio_in,
                stt_engine,
            ),
        )
        self._call_tasks[call_id] = task

        # Play welcome greeting
        welcome = cfg.welcome_greeting
        if welcome:
            await self._play_welcome(
                call_id,
                write_audio,
                welcome,
            )

        logger.info(
            "SIP call started: %s from %s",
            call_id,
            from_uri,
        )

        # Start idle timeout
        self._reset_timeout(call_id)

    async def _play_welcome(
        self,
        call_id: str,
        write_audio: _WriteFn,
        welcome: str,
    ) -> None:
        """Synthesize and play the welcome greeting (streaming)."""
        try:
            cfg = self._config
            is_dev = cfg.sip_mode != "livekit"
            sr = 8000 if is_dev else 24000
            frame_size = self._FRAME_DEV if is_dev else self._FRAME_LK
            session = self.session_mgr.get_session(call_id)
            abort = session.tts_abort if session else None

            buf = b""
            async for chunk in synthesize_tts_stream(
                cfg.tts_provider,
                welcome,
                cfg.tts_voice,
                cfg.dashscope_api_key,
                sample_rate=sr,
            ):
                if abort and abort.is_set():
                    break
                if is_dev:
                    chunk = _pcm16_to_pyvoip(chunk)
                buf += chunk
                while len(buf) >= frame_size:
                    await write_audio(buf[:frame_size])
                    buf = buf[frame_size:]
                    if is_dev:
                        await asyncio.sleep(0.02)
            if buf and not (abort and abort.is_set()):
                await write_audio(buf)
        except Exception:
            logger.exception(
                "Failed to play welcome for %s",
                call_id,
            )

    async def _on_call_ended(self, call_id: str) -> None:
        """Called by the backend when a call ends."""
        timeout_task = self._timeout_tasks.pop(call_id, None)
        if timeout_task:
            timeout_task.cancel()
        task = self._call_tasks.pop(call_id, None)
        if task:
            task.cancel()
        session = self.session_mgr.get_session(call_id)
        if session and session.stt_engine:
            try:
                await session.stt_engine.stop()
            except Exception:
                logger.debug(
                    "Error stopping STT for %s",
                    call_id,
                    exc_info=True,
                )
        self.session_mgr.end_session(call_id)
        self._write_fns.pop(call_id, None)
        logger.info("SIP call ended: %s", call_id)

    async def _call_timeout(
        self,
        call_id: str,
        timeout: float,
    ) -> None:
        """Auto-hangup after *timeout* seconds of inactivity."""
        try:
            await asyncio.sleep(timeout)
            logger.info(
                "Call idle timeout (%ss): %s",
                timeout,
                call_id,
            )
            await self._on_call_ended(call_id)
        except asyncio.CancelledError:
            pass

    def _reset_timeout(self, call_id: str) -> None:
        """Reset the idle timeout for *call_id*."""
        old = self._timeout_tasks.pop(call_id, None)
        if old:
            old.cancel()
        cfg = self._config
        timeout = cfg.call_timeout
        if timeout > 0:
            self._timeout_tasks[call_id] = asyncio.create_task(
                self._call_timeout(call_id, timeout),
            )

    # --------------------------------------------------------------
    # Audio reader task
    # --------------------------------------------------------------

    async def _audio_reader(
        self,
        call_id: str,
        queue: asyncio.Queue,
        stt_engine: Any,
    ) -> None:
        """Forward PCM from audio queue to STT engine."""
        try:
            count = 0
            consecutive_errors = 0
            max_consecutive = 20
            is_lk = self._config.sip_mode == "livekit"
            while True:
                frame = await queue.get()
                if frame is None:
                    logger.info(
                        "Audio EOF for %s after %d frames",
                        call_id,
                        count,
                    )
                    break
                try:
                    if is_lk:
                        out = _pcm_48k16bit_to_16k16bit(frame)
                    else:
                        out = _pcm_8k8bit_to_16k16bit(frame)
                    await stt_engine.feed_audio(out)
                    consecutive_errors = 0
                except Exception:
                    consecutive_errors += 1
                    if consecutive_errors >= max_consecutive:
                        logger.warning(
                            "feed_audio: %d consecutive errors, "
                            "stopping STT for %s",
                            consecutive_errors,
                            call_id,
                        )
                        break
                    if consecutive_errors == 1:
                        logger.warning(
                            "feed_audio error frame %d: %s",
                            count,
                            call_id,
                            exc_info=True,
                        )
                    continue
                count += 1
                if count == 1:
                    logger.info(
                        "First STT frame %s: %d->%d bytes lk=%s",
                        call_id,
                        len(frame),
                        len(out),
                        is_lk,
                    )
                if count % 500 == 0:
                    logger.info(
                        "Fed %d frames to STT: %s",
                        count,
                        call_id,
                    )
        except asyncio.CancelledError:
            pass
        except Exception:
            logger.warning(
                "audio_reader error: %s",
                call_id,
                exc_info=True,
            )

    # --------------------------------------------------------------
    # Transcript callback
    # --------------------------------------------------------------

    def _on_speech_start(self, call_id: str) -> None:
        """Called from STT thread when user starts speaking."""
        session = self.session_mgr.get_session(call_id)
        if session:
            session.tts_abort.set()
            logger.debug("Barge-in: TTS aborted for %s", call_id)

    async def _on_transcript(
        self,
        call_id: str,
        transcript: str,
    ) -> None:
        if not transcript or not transcript.strip():
            return
        session = self.session_mgr.get_session(call_id)
        if session is None:
            return
        # Abort any in-progress TTS playback, then reset for this turn
        session.tts_abort.set()
        session.tts_abort = asyncio.Event()
        self._reset_timeout(call_id)

        logger.info(
            "Transcript for %s: %s",
            call_id,
            transcript[:80],
        )
        native_payload = {
            "transcript": transcript,
            "session_id": session.session_id,
            "from_uri": session.from_uri,
        }
        request = self.build_agent_request_from_native(
            native_payload,
        )

        try:
            # Import here to avoid top-level dependency
            from agentscope_runtime.engine.schemas import (
                agent_schemas as _as,
            )

            completed = _as.RunStatus.Completed
            async for event in self._process(request):
                obj = getattr(event, "object", None)
                status = getattr(event, "status", None)
                if obj != "message" or status is None:
                    continue
                if status == completed:
                    text = _extract_text(event)
                    if text:
                        logger.info(
                            "Agent reply %s: %s",
                            call_id,
                            text[:80],
                        )
                        await self.send(call_id, text)
        except Exception:
            logger.exception(
                "Error processing transcript: %s",
                call_id,
            )

    @property
    def config(self) -> Optional[SIPChannelConfig]:
        return self._config


# --------------------------------------------------------------
# Helpers
# --------------------------------------------------------------


_EMOJI_RE = _re.compile(
    "[\U00010000-\U0010ffff"  # supplementary planes (most emoji)
    "\U0000200d"  # zero-width joiner
    "\U0000fe0f"  # variation selector
    "\U000023e9-\U000023fa"  # misc symbols
    "\U00002702-\U000027b0"  # dingbats
    "\U0000fe00-\U0000fe0f"  # variation selectors
    "]+",
    flags=_re.UNICODE,
)


def _clean_for_tts(text: str) -> str:
    """Remove emoji and characters that DashScope TTS rejects."""
    text = _EMOJI_RE.sub("", text)
    # Collapse multiple whitespace/newlines into single space
    text = _re.sub(r"\s+", " ", text).strip()
    return text


def _extract_text(event: Any) -> str:
    """Extract text from an agent response event."""
    if hasattr(event, "get_text_content"):
        parts = event.get_text_content()
        if parts:
            text = " ".join(
                p.text for p in parts if hasattr(p, "text") and p.text
            )
            if text:
                return text
    content = getattr(event, "content", None) or []
    for part in content:
        if hasattr(part, "text") and part.text:
            return part.text
    message = getattr(event, "message", None)
    if message:
        mc = getattr(message, "content", None) or []
        for part in mc:
            if hasattr(part, "text") and part.text:
                return part.text
    return ""


# --------------------------------------------------------------
# Audio format conversion
# --------------------------------------------------------------


def _pcm16_to_pyvoip(data: bytes) -> bytes:
    """16-bit signed PCM -> 8-bit unsigned for pyVoIP."""
    pcm8 = audioop.lin2lin(data, 2, 1)
    return audioop.bias(pcm8, 1, 128)


def _pcm_8k8bit_to_16k16bit(data: bytes) -> bytes:
    """8-bit unsigned 8 kHz -> 16-bit signed 16 kHz."""
    pcm16 = audioop.bias(data, 1, -128)
    pcm16 = audioop.lin2lin(pcm16, 1, 2)
    pcm16, _ = audioop.ratecv(
        pcm16,
        2,
        1,
        8000,
        16000,
        None,
    )
    return pcm16


def _pcm_48k16bit_to_16k16bit(data: bytes) -> bytes:
    """16-bit signed 48 kHz -> 16-bit signed 16 kHz."""
    pcm16, _ = audioop.ratecv(
        data,
        2,
        1,
        48000,
        16000,
        None,
    )
    return pcm16


def _wav_to_backend_pcm(
    wav_bytes: bytes,
    sip_mode: str,
) -> bytes:
    """Convert TTS WAV to backend-expected format."""
    if sip_mode == "livekit":
        return _wav_to_raw_pcm16(wav_bytes)
    return _wav_to_pyvoip_pcm(wav_bytes)


def _wav_to_raw_pcm16(wav_bytes: bytes) -> bytes:
    """Extract raw 16-bit signed PCM from WAV."""
    import io
    import wave

    try:
        with wave.open(io.BytesIO(wav_bytes), "rb") as wf:
            return wf.readframes(wf.getnframes())
    except Exception:
        return wav_bytes


def _wav_to_pyvoip_pcm(wav_bytes: bytes) -> bytes:
    """Convert WAV to 8-bit unsigned for pyVoIP."""
    import io
    import wave

    try:
        with wave.open(io.BytesIO(wav_bytes), "rb") as wf:
            pcm = wf.readframes(wf.getnframes())
            sampwidth = wf.getsampwidth()
    except Exception:
        pcm = wav_bytes
        sampwidth = 2

    if sampwidth == 2:
        pcm = audioop.lin2lin(pcm, 2, 1)
    pcm = audioop.bias(pcm, 1, 128)
    return pcm


# --------------------------------------------------------------
# Backend factory
# --------------------------------------------------------------


def _create_backend(config: SIPChannelConfig) -> SipBackend:
    if config.sip_mode == "livekit":
        from .livekit_backend import LiveKitBackend

        return LiveKitBackend(
            livekit_url=config.livekit_url,
            livekit_api_key=config.livekit_api_key,
            livekit_api_secret=config.livekit_api_secret,
            sip_trunk_id=config.livekit_sip_trunk_id,
            room_name=config.livekit_room_name,
            output_sample_rate=config.livekit_output_sample_rate,
        )
    from .pyvoip_backend import PyVoIPBackend

    server = config.sip_server
    port = 5060
    host = server
    if ":" in server:
        parts = server.rsplit(":", 1)
        host = parts[0]
        try:
            port = int(parts[1])
        except ValueError:
            port = 5060

    return PyVoIPBackend(
        server=host,
        port=port,
        username=config.sip_username,
        password=config.sip_password,
        bind_ip=config.sip_host,
        sip_port=config.sip_port,
        rtp_port_low=config.rtp_port_low,
        rtp_port_high=config.rtp_port_high,
    )


def _create_backend_for_builtin(
    config: SIPChannelConfig,
) -> "SipBackend":
    """Create a PyVoIP backend wired to the built-in registrar."""
    from .pyvoip_backend import PyVoIPBackend

    # pyVoIP uses myIP for SDP c= line and Contact header.
    # 0.0.0.0 is fine for *listening* but breaks SDP (peers
    # don't know where to send RTP).  Force 127.0.0.1 for the
    # built-in registrar (local-only) scenario.
    bind_ip = config.sip_host
    if bind_ip == "0.0.0.0":
        bind_ip = "127.0.0.1"

    return PyVoIPBackend(
        server="127.0.0.1",
        port=5060,
        username=config.sip_username or "agent",
        password=config.sip_password or "pass",
        bind_ip=bind_ip,
        sip_port=config.sip_port,
        rtp_port_low=config.rtp_port_low,
        rtp_port_high=config.rtp_port_high,
    )
