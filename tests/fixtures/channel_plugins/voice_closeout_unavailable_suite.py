"""Original disabled/unconfigured Voice public HTTP response contracts."""

from xml.etree import ElementTree

import pytest

from voice_closeout_support import runtime, voice_host, voice_host_guard

__all__ = ["runtime", "voice_host", "voice_host_guard"]


@pytest.mark.asyncio
async def test_empty_registry_incoming_preserves_original_error_twiml(
    voice_host,
):
    assert not voice_host.service.registry.runtime_owners.leases("voice")
    for fields in (
        None,
        {"CallSid": "CAintegtest0001", "From": "+15550001111"},
    ):
        async with voice_host.client.post(
            voice_host.base + "/voice/incoming", data=fields
        ) as response:
            assert response.status == 200
            assert "xml" in response.headers.get("Content-Type", "").lower()
            body = await response.text()
            assert "Voice channel is not available" in body
            assert "<Response" in body and "</Response>" in body
            assert ElementTree.fromstring(body).tag == "Response"


@pytest.mark.asyncio
async def test_empty_registry_status_preserves_original_empty_204(voice_host):
    assert not voice_host.service.registry.runtime_owners.leases("voice")
    for fields in (
        None,
        {"CallSid": "CAintegtest0002", "CallStatus": "completed"},
    ):
        async with voice_host.client.post(
            voice_host.base + "/voice/status-callback", data=fields
        ) as response:
            assert response.status == 204
            assert await response.read() == b""
