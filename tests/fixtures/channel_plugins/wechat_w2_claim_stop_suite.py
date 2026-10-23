"""Unit of actual QR cleanup reached through a real auth-claim stop adapter.

Builds the production session state directly; real Loader/Service exist but no
platform operation is requested. This is an ownership unit, not QR integration.
"""

import asyncio
from importlib import import_module

import pytest

from qwenpaw.plugins.ownership import RuntimeKey, RuntimeStopReceipt
from management_process_suite import KEY, management_runtime
from wechat_w2_session_suite import narrow_legacy_test_guard


@pytest.mark.asyncio
async def test_claim_stop_recursion_settles_qr_owner_without_abandoning_claim(
    management_runtime,
    tmp_path,
):
    rt = await management_runtime()
    api = import_module("qwenpaw.app.channels.qrcode_sessions")
    auth = import_module("qwenpaw.app.channels.wechat_auth_custody")
    sessions = api.ChannelQRCodeSessions(rt.loader, rt.service)
    scope = api.ChannelManagementScope(
        "A",
        tmp_path / "A",
        "wechat",
        {"bot_token_file": str(tmp_path / "A" / "token")},
    )
    other = rt.owners.reserve(
        KEY,
        RuntimeKey("management", KEY, "unrelated-B"),
        rt.record.source_path,
        instance_id="other-owner",
    )
    async with rt.loader.execution_source(KEY):
        lease = rt.owners.reserve(
            KEY,
            RuntimeKey("qrcode_session", "wechat", str(scope.workspace_dir)),
            rt.record.source_path,
            instance_id="qr-owner-A",
        )
        session = api._Session(
            scope,
            lease,
            "unit-revision-not-used-by-stop",
            {},
            api.monotonic() + 300,
        )
        rt.owners.attach(
            lease, lambda: sessions._stop(session), resource=session
        )
        session.claims = auth.reserve_wechat_auth(
            rt.loader.registry,
            owner=lease,
            workspace_id="A",
            workspace_dir=scope.workspace_dir,
            config=scope.config,
        )
    claims = session.claims
    try:
        assert claims
        async with asyncio.timeout(2):
            receipt = await rt.owners.stop(claims[0])
        assert receipt.stopped
        assert lease not in rt.owners.leases()
        assert set(claims).isdisjoint(rt.owners.leases())
        assert other in rt.owners.leases()
        assert session.claims == () and session.config == {}
    finally:
        for claim in claims:
            await rt.owners.stop(claim)
        await rt.owners.stop(lease)
        rt.owners.release(
            other, RuntimeStopReceipt(True, "unit never spawned")
        )
        await sessions.aclose()
