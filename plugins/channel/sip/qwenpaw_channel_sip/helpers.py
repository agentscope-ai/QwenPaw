# -*- coding: utf-8 -*-
"""Original SIP text, audio and backend factory algorithms."""
from __future__ import annotations
import re as _re
from typing import Any
from .backend import SipBackend

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
    from ._audioop_compat import audioop

    pcm8 = audioop.lin2lin(data, 2, 1)
    return audioop.bias(pcm8, 1, 128)


def _pcm_8k8bit_to_16k16bit(data: bytes) -> bytes:
    """8-bit unsigned 8 kHz -> 16-bit signed 16 kHz."""
    from ._audioop_compat import audioop

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
    from ._audioop_compat import audioop

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
    from ._audioop_compat import audioop
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


def _create_backend(config: Any) -> SipBackend:
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
    config: Any,
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
