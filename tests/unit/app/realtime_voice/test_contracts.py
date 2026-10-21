import pytest

from qwenpaw.app.realtime_voice.contracts import (
    AudioFrame,
    AudioFrameKind,
    decode_audio_frame,
    encode_audio_frame,
)


def test_audio_frame_round_trip_and_version_validation():
    frame = AudioFrame(
        kind=AudioFrameKind.INPUT_PCM16,
        sequence=19,
        sample_rate=16000,
        channels=1,
        payload=b"\x01\x02\x03\x04",
    )
    encoded = encode_audio_frame(frame)

    assert decode_audio_frame(encoded) == frame

    corrupt = bytearray(encoded)
    corrupt[2] = 99
    with pytest.raises(ValueError, match="version"):
        decode_audio_frame(bytes(corrupt))
