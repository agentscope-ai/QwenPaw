# -*- coding: utf-8 -*-
# pylint: disable=protected-access,redefined-outer-name
"""Unit tests for the pure helpers in app/channels/sip/__init__.py.

SIPChannel itself needs a live socket/registrar and is exercised elsewhere;
these module-level helpers (TTS text cleanup, event text extraction, PCM/WAV
conversion, backend factory) are pure or only need a config object, so they are
tested directly. Audio expectations were measured against the real audioop shim
rather than assumed.
"""

import io
import struct
import wave
from types import SimpleNamespace

from qwenpaw.app.channels.sip import (
    _clean_for_tts,
    _create_backend,
    _create_backend_for_builtin,
    _extract_text,
    _pcm16_to_pyvoip,
    _pcm_48k16bit_to_16k16bit,
    _pcm_8k8bit_to_16k16bit,
    _wav_to_backend_pcm,
    _wav_to_pyvoip_pcm,
    _wav_to_raw_pcm16,
)


def _make_wav(frames, sampwidth=2, framerate=16000, channels=1):
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(channels)
        w.setsampwidth(sampwidth)
        w.setframerate(framerate)
        w.writeframes(frames)
    return buf.getvalue()


# ── _clean_for_tts ──────────────────────────────────────────────────


class TestCleanForTts:
    def test_strips_emoji(self):
        assert _clean_for_tts("hi 😀 there") == "hi there"

    def test_strips_zero_width_joiner_sequences(self):
        # family emoji built from ZWJ
        assert _clean_for_tts("a\U0001f468\u200d\U0001f469b") == "ab"

    def test_strips_variation_selector(self):
        assert _clean_for_tts("x\u2764\ufe0fy") == "xy"

    def test_strips_dingbats_and_misc_symbols(self):
        assert _clean_for_tts("\u2702cut\u23e9") == "cut"

    def test_collapses_runs_of_whitespace(self):
        assert _clean_for_tts("a\n\n  b\t\tc") == "a b c"

    def test_strips_surrounding_whitespace(self):
        assert _clean_for_tts("   padded   ") == "padded"

    def test_plain_text_is_unchanged(self):
        assert _clean_for_tts("hello world") == "hello world"

    def test_empty_and_emoji_only_become_empty(self):
        assert _clean_for_tts("") == ""
        assert _clean_for_tts("😀😀") == ""

    def test_keeps_cjk_text(self):
        """CJK is not emoji and must survive (TTS legitimately reads it)."""
        assert _clean_for_tts("你好 世界") == "你好 世界"

    def test_emoji_between_cjk_is_removed(self):
        assert _clean_for_tts("你好😀世界") == "你好世界"


# ── _extract_text ───────────────────────────────────────────────────


class _Part:
    def __init__(self, text):
        self.text = text


class TestExtractText:
    def test_prefers_get_text_content(self):
        event = SimpleNamespace(
            get_text_content=lambda: [_Part("a"), _Part("b")],
            content=[],
        )
        assert _extract_text(event) == "a b"

    def test_get_text_content_skips_parts_without_text(self):
        event = SimpleNamespace(
            get_text_content=lambda: [_Part("keep"), SimpleNamespace(other=1)],
            content=[],
        )
        assert _extract_text(event) == "keep"

    def test_falls_back_to_content_when_no_get_text_content(self):
        event = SimpleNamespace(content=[_Part("from content")])
        assert _extract_text(event) == "from content"

    def test_falls_back_when_get_text_content_returns_empty(self):
        event = SimpleNamespace(
            get_text_content=lambda: [],
            content=[_Part("fallback")],
        )
        assert _extract_text(event) == "fallback"

    def test_falls_back_when_get_text_content_joins_to_empty(self):
        event = SimpleNamespace(
            get_text_content=lambda: [_Part("")],
            content=[_Part("real")],
        )
        assert _extract_text(event) == "real"

    def test_uses_message_content_as_last_resort(self):
        message = SimpleNamespace(content=[_Part("from message")])
        event = SimpleNamespace(content=[], message=message)
        assert _extract_text(event) == "from message"

    def test_returns_empty_when_nothing_has_text(self):
        event = SimpleNamespace(content=[], message=None)
        assert _extract_text(event) == ""

    def test_returns_empty_for_a_bare_object(self):
        assert _extract_text(object()) == ""

    def test_message_without_content_yields_empty(self):
        event = SimpleNamespace(
            content=[],
            message=SimpleNamespace(content=[]),
        )
        assert _extract_text(event) == ""


# ── PCM conversion ─────────────────────────────────────────────────


class TestPcmConversion:
    def test_pcm16_to_pyvoip_halves_the_width(self):
        pcm16 = struct.pack("<4h", 0, 1000, -1000, 32767)
        out = _pcm16_to_pyvoip(pcm16)
        assert len(out) == 4  # 4 frames x 1 byte

    def test_pcm16_silence_maps_to_the_unsigned_midpoint(self):
        # 16-bit 0 is silence; 8-bit unsigned silence is 128.
        out = _pcm16_to_pyvoip(struct.pack("<h", 0))
        assert out == bytes([128])

    def test_pcm16_is_unsigned_after_bias(self):
        out = _pcm16_to_pyvoip(struct.pack("<4h", -32768, -1, 1, 32767))
        assert all(0 <= b <= 255 for b in out)

    def test_8k8bit_to_16k16bit_upsamples(self):
        out = _pcm_8k8bit_to_16k16bit(bytes([128, 255]))
        # 8k -> 16k roughly doubles the frame count, 1 -> 2 bytes each.
        assert len(out) >= 4
        assert len(out) % 2 == 0  # 16-bit output is an even number of bytes

    def test_8k_silence_stays_near_silence(self):
        out = _pcm_8k8bit_to_16k16bit(bytes([128]) * 4)
        samples = struct.unpack(f"<{len(out) // 2}h", out)
        assert max(abs(s) for s in samples) < 1000

    def test_48k_to_16k_downsamples(self):
        pcm48 = struct.pack("<6h", *([0] * 6))
        out = _pcm_48k16bit_to_16k16bit(pcm48)
        # 48k -> 16k is a third the rate; stays 16-bit.
        assert len(out) % 2 == 0
        assert len(out) <= len(pcm48)

    def test_48k_conversion_preserves_16bit_width(self):
        out = _pcm_48k16bit_to_16k16bit(struct.pack("<8h", *range(8)))
        assert len(out) % 2 == 0


# ── WAV conversion ─────────────────────────────────────────────────


class TestWavConversion:
    def test_raw_pcm16_extracts_frames(self):
        wav = _make_wav(struct.pack("<4h", 0, 1000, -1000, 32767))
        assert len(_wav_to_raw_pcm16(wav)) == 8  # 4 frames x 2 bytes

    def test_raw_pcm16_round_trips_the_samples(self):
        frames = struct.pack("<3h", 111, -222, 333)
        wav = _make_wav(frames)
        assert _wav_to_raw_pcm16(wav) == frames

    def test_pyvoip_pcm_halves_the_width(self):
        wav = _make_wav(struct.pack("<4h", 0, 1000, -1000, 32767))
        assert len(_wav_to_pyvoip_pcm(wav)) == 4  # 4 frames x 1 byte

    def test_backend_pcm_livekit_matches_raw(self):
        wav = _make_wav(struct.pack("<4h", 0, 1000, -1000, 32767))
        assert _wav_to_backend_pcm(wav, "livekit") == _wav_to_raw_pcm16(wav)

    def test_backend_pcm_pyvoip_matches_pyvoip(self):
        wav = _make_wav(struct.pack("<4h", 0, 1000, -1000, 32767))
        assert _wav_to_backend_pcm(wav, "pyvoip") == _wav_to_pyvoip_pcm(wav)

    def test_backend_pcm_unknown_mode_defaults_to_pyvoip(self):
        wav = _make_wav(struct.pack("<2h", 0, 100))
        assert _wav_to_backend_pcm(
            wav,
            "something-else",
        ) == _wav_to_pyvoip_pcm(wav)

    def test_raw_pcm16_returns_input_when_not_a_wav(self):
        assert _wav_to_raw_pcm16(b"not-a-wav") == b"not-a-wav"

    def test_pyvoip_pcm_returns_biased_input_when_not_a_wav(self):
        # On the except path it treats the bytes as 16-bit (sampwidth=2):
        # 2 input bytes -> lin2lin to 1 byte -> bias, so the result is 1 byte.
        out = _wav_to_pyvoip_pcm(b"\x00\x00")
        assert len(out) == 1

    def test_single_channel_8bit_wav(self):
        wav = _make_wav(bytes([128, 200]), sampwidth=1)
        out = _wav_to_pyvoip_pcm(wav)
        assert len(out) == 2  # already 8-bit, only biased


# ── backend factory ────────────────────────────────────────────────


class TestCreateBackend:
    def test_livekit_mode_builds_a_livekit_backend(self):
        from qwenpaw.app.channels.sip.livekit_backend import LiveKitBackend
        from qwenpaw.config.config import SIPChannelConfig

        cfg = SIPChannelConfig(sip_mode="livekit", livekit_url="wss://x")
        backend = _create_backend(cfg)
        assert isinstance(backend, LiveKitBackend)

    def test_pyvoip_mode_builds_a_pyvoip_backend(self):
        from qwenpaw.app.channels.sip.pyvoip_backend import PyVoIPBackend
        from qwenpaw.config.config import SIPChannelConfig

        cfg = SIPChannelConfig(sip_mode="pyvoip", sip_server="1.2.3.4")
        backend = _create_backend(cfg)
        assert isinstance(backend, PyVoIPBackend)

    def test_server_with_port_is_split(self):
        from qwenpaw.config.config import SIPChannelConfig

        cfg = SIPChannelConfig(sip_mode="pyvoip", sip_server="1.2.3.4:5070")
        backend = _create_backend(cfg)
        assert backend._server == "1.2.3.4"
        assert backend._port == 5070

    def test_server_without_port_defaults_to_5060(self):
        from qwenpaw.config.config import SIPChannelConfig

        cfg = SIPChannelConfig(sip_mode="pyvoip", sip_server="1.2.3.4")
        assert _create_backend(cfg)._port == 5060

    def test_server_with_a_non_numeric_port_falls_back_to_5060(self):
        from qwenpaw.config.config import SIPChannelConfig

        cfg = SIPChannelConfig(sip_mode="pyvoip", sip_server="1.2.3.4:abc")
        assert _create_backend(cfg)._port == 5060

    def test_server_with_ipv6_style_colon_splits_on_the_last_one(self):
        from qwenpaw.config.config import SIPChannelConfig

        cfg = SIPChannelConfig(sip_mode="pyvoip", sip_server="host:1:5080")
        backend = _create_backend(cfg)
        assert backend._server == "host:1"
        assert backend._port == 5080


class TestCreateBackendForBuiltin:
    def test_forces_localhost_and_registrar_defaults(self):
        from qwenpaw.app.channels.sip.pyvoip_backend import PyVoIPBackend
        from qwenpaw.config.config import SIPChannelConfig

        cfg = SIPChannelConfig(sip_mode="pyvoip")
        backend = _create_backend_for_builtin(cfg)
        assert isinstance(backend, PyVoIPBackend)
        assert backend._server == "127.0.0.1"
        assert backend._port == 5060

    def test_rewrites_wildcard_bind_ip_to_loopback(self):
        from qwenpaw.config.config import SIPChannelConfig

        cfg = SIPChannelConfig(sip_mode="pyvoip", sip_host="0.0.0.0")
        assert _create_backend_for_builtin(cfg)._bind_ip == "127.0.0.1"

    def test_keeps_an_explicit_bind_ip(self):
        from qwenpaw.config.config import SIPChannelConfig

        cfg = SIPChannelConfig(sip_mode="pyvoip", sip_host="10.0.0.5")
        assert _create_backend_for_builtin(cfg)._bind_ip == "10.0.0.5"

    def test_supplies_default_credentials_when_absent(self):
        from qwenpaw.config.config import SIPChannelConfig

        cfg = SIPChannelConfig(
            sip_mode="pyvoip",
            sip_username="",
            sip_password="",
        )
        backend = _create_backend_for_builtin(cfg)
        assert backend._username == "agent"
        assert backend._password == "pass"

    def test_keeps_explicit_credentials(self):
        from qwenpaw.config.config import SIPChannelConfig

        cfg = SIPChannelConfig(
            sip_mode="pyvoip",
            sip_username="bob",
            sip_password="secret",
        )
        backend = _create_backend_for_builtin(cfg)
        assert backend._username == "bob"
        assert backend._password == "secret"
