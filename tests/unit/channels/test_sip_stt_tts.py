from unittest.mock import AsyncMock, Mock

import pytest

from qwenpaw.app.channels.sip import stt_tts


@pytest.mark.asyncio
async def test_minimax_tts_request_and_audio_response(monkeypatch):
    response = Mock()
    response.json.return_value = {
        "data": {"audio": "000102ff"},
        "base_resp": {"status_code": 0},
    }
    client = AsyncMock()
    client.post.return_value = response
    client.__aenter__.return_value = client
    client.__aexit__.return_value = None
    monkeypatch.setattr(stt_tts.httpx, "AsyncClient", lambda: client)

    chunks = [
        chunk
        async for chunk in stt_tts.synthesize_tts_stream(
            "minimax",
            "Hello",
            "English_Graceful_Lady",
            "test-key",
            sample_rate=24000,
            model="speech-2.8-turbo",
            endpoint="https://api.minimaxi.com/v1/t2a_v2",
        )
    ]

    assert chunks == [b"\x00\x01\x02\xff"]
    client.post.assert_awaited_once_with(
        "https://api.minimaxi.com/v1/t2a_v2",
        headers={"Authorization": "Bearer test-key"},
        json={
            "model": "speech-2.8-turbo",
            "text": "Hello",
            "stream": False,
            "output_format": "hex",
            "voice_setting": {"voice_id": "English_Graceful_Lady"},
            "audio_setting": {"format": "pcm", "sample_rate": 24000},
        },
    )
