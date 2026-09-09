# -*- coding: utf-8 -*-
# pylint: disable=protected-access
"""Audio-fallback error classifier (follow-up to issue #7015).

``_is_audio_fallback_error`` gates the strip-audio-and-retry path in
``QwenPawAgent._reasoning``.  The original classifier only recognized
DashScope's modality rejection ("incorrect modal ... audio ...").  Two
rejection shapes fell through and killed the whole agent turn even
though the audio file had already been delivered to the user:

1. DashScope rejects local audio serialized as raw base64 with a
   generic invalid-URL error (issue #7015, first failure mode).
2. llama.cpp ``llama-server`` (OpenAI-compatible) backed by a
   vision-only mmproj rejects ``input_audio`` with HTTP 500
   "audio input is not supported".

These tests pin the three recognized shapes and the false-positive
guards.  The URL-shape match is deliberately gated on a 400-class
status and, at the call site, on ``_last_wire_request_had_audio()``,
so genuinely malformed image/video URLs cannot be misclassified as
audio rejections.
"""
from __future__ import annotations

from qwenpaw.agents.react_agent import QwenPawAgent


class _FakeAPIError(Exception):
    """Mimics a provider SDK error carrying an HTTP status."""

    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        if status_code is not None:
            self.status_code = status_code


def test_dashscope_modality_rejection_matches() -> None:
    """Original shape: 400 + InvalidParameter + 'incorrect modal audio'."""
    exc = _FakeAPIError(
        'Error code: 400 - {"code":"InternalError.Algo.InvalidParameter",'
        '"message":"An incorrect modal `audio` was entered, which may not '
        "be supported by the model or was placed in the wrong position "
        '(e.g., in system/assistant)."}',
        status_code=400,
    )
    assert QwenPawAgent._is_audio_fallback_error(exc) is True


def test_dashscope_invalid_url_rejection_matches() -> None:
    """Issue #7015 first failure mode: local audio serialized as raw
    base64 is rejected as an invalid URL (HTTP 400)."""
    exc = _FakeAPIError(
        'data: {"error":{"code":"invalid_parameter_error","param":null,'
        '"message":"The provided URL does not appear to be valid. Ensure '
        'it is correctly formatted.","type":"invalid_request_error"}}',
        status_code=400,
    )
    assert QwenPawAgent._is_audio_fallback_error(exc) is True


def test_llama_server_audio_unsupported_matches() -> None:
    """llama.cpp llama-server with a vision-only mmproj rejects
    input_audio with HTTP 500."""
    exc = _FakeAPIError(
        'Error code: 500 - {"error":{"code":500,"message":"audio input is '
        "not supported - hint: if this is unexpected, you may need to "
        'provide the mmproj","type":"server_error"}}',
        status_code=500,
    )
    assert QwenPawAgent._is_audio_fallback_error(exc) is True


def test_llama_server_audio_unsupported_without_status_matches() -> None:
    """The llama-server message is unambiguous on its own; status
    extraction is not required for this shape."""
    exc = Exception("audio input is not supported")
    assert QwenPawAgent._is_audio_fallback_error(exc) is True


def test_invalid_url_without_bad_request_status_does_not_match() -> None:
    """The URL-shape match is gated on a 400-class status so transport
    failures (5xx) are not misread as audio rejections."""
    exc = _FakeAPIError(
        "The provided URL does not appear to be valid.",
        status_code=503,
    )
    assert QwenPawAgent._is_audio_fallback_error(exc) is False


def test_generic_server_error_does_not_match() -> None:
    exc = _FakeAPIError(
        'Error code: 500 - {"error":{"message":"internal server error"}}',
        status_code=500,
    )
    assert QwenPawAgent._is_audio_fallback_error(exc) is False


def test_image_decode_error_does_not_match() -> None:
    """A vision failure must not be misread as an audio rejection."""
    exc = _FakeAPIError(
        'Error code: 500 - {"error":{"message":"failed to decode image"}}',
        status_code=500,
    )
    assert QwenPawAgent._is_audio_fallback_error(exc) is False


def test_context_overflow_error_does_not_match() -> None:
    """Context-overflow 400s are handled by a dedicated classifier and
    must not enter the audio-strip retry."""
    exc = _FakeAPIError(
        "Error code: 400 - context length exceeded",
        status_code=400,
    )
    assert QwenPawAgent._is_audio_fallback_error(exc) is False
