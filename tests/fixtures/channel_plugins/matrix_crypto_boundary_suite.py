"""Real attachment crypto/HTTP; SAS unit doubles are explicitly not olm E2EE."""
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from nio import ToDeviceEvent
from nio.crypto.attachments import encrypt_attachment
from matrix_native_support import hs, platform_factory
from matrix_pure_oracle_suite import matrix_channel


@pytest.mark.asyncio
async def test_real_attachment_decrypt_and_bad_hash_never_publish_plaintext(hs, platform_factory):
    platform = platform_factory()
    await platform.start()
    hs.download, info = encrypt_attachment(b"actual encrypted attachment bytes")
    path = await platform._download_encrypted_mxc("mxc://example.org/attachment", "native.bin", info["key"], info["hashes"], info["iv"])
    assert Path(path).read_bytes() == b"actual encrypted attachment bytes"
    assert await platform._download_encrypted_mxc("mxc://example.org/attachment", "bad.bin", info["key"], {"sha256": "wrong"}, info["iv"]) is None
    assert not list(Path(platform.config["workspace_dir"]).rglob("bad.bin"))


@pytest.mark.asyncio
async def test_unknown_done_real_nio_http_failure_retains_peer_then_success_clears(hs, platform_factory):
    platform = platform_factory()
    await platform.start()
    platform._remember_verification_peer("tx", "@user:example.com", "D1")
    event = ToDeviceEvent.parse_event({"type": "m.key.verification.done", "sender": "@user:example.com", "content": {"transaction_id": "tx"}})
    hs.to_device.append(({"errcode": "M_FORBIDDEN", "error": "try again"}, 403))
    await platform._handle_unknown_key_verification_done(event)
    assert "tx" in platform._verification_tx_peers and "tx" not in platform._sent_verification_done
    await platform._handle_unknown_key_verification_done(event)
    assert "tx" not in platform._verification_tx_peers and "tx" in platform._sent_verification_done
    requests = [r for r in hs.requests if "/sendToDevice/" in r["path"]]
    assert len(requests) == 2
    assert requests[0]["body"] == requests[1]["body"] == {"messages": {"@user:example.com": {"D1": {"transaction_id": "tx"}}}}


@pytest.mark.asyncio
async def test_unit_sas_flushes_before_confirm_and_formats_challenge(matrix_channel):
    # Missing native olm means this is only the platform's SDK orchestration contract.
    order = []
    async def flush():
        order.append("flush")
    async def confirm(transaction):
        order.append(("confirm", transaction))
    sas = SimpleNamespace(get_emoji=lambda: [("🐶", "dog")], get_decimal=lambda: [1001, 2002, 3003])
    matrix_channel._client = SimpleNamespace(key_verifications={"tx": sas}, send_to_device_messages=flush, confirm_short_auth_string=confirm)
    await matrix_channel._handle_key_verification_key(SimpleNamespace(transaction_id="tx", sender="@user:hs"))
    assert order == ["flush", ("confirm", "tx")]
    assert matrix_channel._format_sas_challenge(sas) == "emoji=🐶(dog); decimal=1001 2002 3003"


@pytest.mark.asyncio
async def test_unit_failed_ready_retains_peer_and_allows_same_request_retry(matrix_channel):
    sent = []
    async def to_device(message):
        sent.append(message)
        if len(sent) == 1:
            raise RuntimeError("network down")
    matrix_channel._client = SimpleNamespace(olm=object(), device_id="OUR", to_device=to_device)
    event = ToDeviceEvent.parse_event({"type": "m.key.verification.request", "sender": "@user:hs", "content": {"from_device": "THEIR", "transaction_id": "tx", "methods": ["m.sas.v1"]}})
    await matrix_channel._on_to_device_probe_event(event)
    assert matrix_channel._verification_tx_peers["tx"] == ("@user:hs", "THEIR")
    assert not matrix_channel._handled_verification_requests
    await matrix_channel._on_to_device_probe_event(event)
    assert len(sent) == 2
    assert sent[0].content == sent[1].content == {"from_device": "OUR", "methods": ["m.sas.v1"], "transaction_id": "tx"}
