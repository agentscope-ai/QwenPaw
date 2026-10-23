"""Admission units use real RuntimeOwners slots; no extra workers are faked."""

import pytest

from qwenpaw.app.channels.management import ManagementError
from qwenpaw.plugins.ownership import RuntimeKey, RuntimeStopReceipt
from wechat_w2_session_suite import qr, narrow_legacy_test_guard
from management_process_suite import management_runtime, local_management_http


@pytest.mark.asyncio
async def test_128_real_reserved_qr_slots_reject_next_before_external_effect(
    qr,
):
    held = [
        qr.rt.owners.reserve(
            qr.rt.record.manifest.id,
            RuntimeKey(
                "qrcode_session", "capacity-unit", str(qr.paths["A"] / str(i))
            ),
            qr.rt.record.source_path,
            instance_id="capacity-" + str(i),
        )
        for i in range(128)
    ]
    try:
        with pytest.raises(ManagementError) as denied:
            await qr.sessions.fetch(qr.scope, {})
        assert denied.value.reason_code == "MANAGEMENT_BUSY"
        assert not qr.http.requests
        assert set(held).issubset(qr.rt.owners.leases())
    finally:
        for lease in held:
            qr.rt.owners.release(
                lease, RuntimeStopReceipt(True, "unit no resource")
            )


@pytest.mark.asyncio
async def test_reserved_runtime_constructor_blocks_qr_without_stopping_owner(
    qr,
):
    lease = qr.rt.owners.reserve(
        qr.rt.record.manifest.id,
        RuntimeKey(
            "channel", qr.scope.channel_key, str(qr.scope.workspace_dir)
        ),
        qr.rt.record.source_path,
        instance_id="runtime-constructor-not-started",
    )
    try:
        with pytest.raises(ManagementError) as denied:
            await qr.sessions.fetch(qr.scope, {})
        assert denied.value.reason_code == "ACCOUNT_IN_USE"
        assert lease in qr.rt.owners.leases()
        assert not qr.http.requests
    finally:
        qr.rt.owners.release(
            lease, RuntimeStopReceipt(True, "unit no resource")
        )
