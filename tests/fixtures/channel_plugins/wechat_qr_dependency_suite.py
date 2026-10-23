"""A waiting native QR session must not invent an executing interpreter."""

from dataclasses import asdict
import json

import pytest

from wechat_g3_native_suite import assert_native_clients_closed
from wechat_g3_native_support import g3_host_import_boundary, wechat_g3

__all__ = ["g3_host_import_boundary", "wechat_g3"]


@pytest.mark.asyncio
async def test_waiting_native_qr_session_does_not_block_unrelated_admission(
    wechat_g3, monkeypatch, tmp_path
):
    from qwenpaw.app.channels.process_supervisor import ChannelProcess
    from qwenpaw.plugins.dependency_gate import evaluate_shared_dependencies

    qr = wechat_g3
    observations = []
    original = ChannelProcess.start_management

    async def observe_actual_start(process, spec):
        result = await original(process, spec)
        observations.append(process.dependency_snapshot)
        return result

    monkeypatch.setattr(
        ChannelProcess, "start_management", observe_actual_start
    )
    fetched = await qr.sessions.fetch(qr.scope, {})
    result = await qr.sessions.poll(qr.scope, fetched.poll_token)
    assert result.status == "waiting" and result.credentials == {}
    assert_native_clients_closed(qr)
    assert len(observations) == 2
    snapshot = observations[-1]
    assert snapshot is not None and snapshot.dependency_sites is not None
    owners = qr.loader.registry.runtime_owners
    (session,) = (
        lease
        for lease in owners.leases()
        if lease.key.kind == "qrcode_session"
    )
    assert {lease.key.kind for lease in owners.leases()} <= {
        "qrcode_session",
        "wechat_auth",
    }
    assert session not in owners.dependency_leases()
    assert session.plugin_id == "wechat"
    usage = qr.loader.registry.dependency_usage
    uses = usage.snapshot().uses
    before = evaluate_shared_dependencies(
        None, snapshot, plugin_id="unrelated-descriptor", uses=uses
    )
    # Real cancellation and worker cleanup must restore the same Gate without
    # changing environment evidence, requirements, or dependency declarations.
    await qr.sessions.cancel(qr.scope, fetched.poll_token)
    assert owners.leases() == ()
    after = evaluate_shared_dependencies(
        None,
        snapshot,
        plugin_id="unrelated-descriptor",
        uses=usage.snapshot().uses,
    )
    (tmp_path / "waiting-qr-dependency-observation.json").write_text(
        json.dumps(
            {
                "owner_kind": session.key.kind,
                "owner_plugin": session.plugin_id,
                "management_requests": len(qr.requests),
                "actual_worker_audit_count": len(observations),
                "runtime_uses": [
                    {
                        "plugin_id": use.plugin_id,
                        "origin": use.origin,
                        "environment_known": use.environment is not None,
                        "generation": use.generation,
                    }
                    for use in uses
                ],
                "waiting_decision": asdict(before),
                "after_real_cancel_decision": asdict(after),
            },
            indent=2,
        )
    )
    assert after.already_satisfied, after.reason
    assert before.already_satisfied, (
        "A waiting QR session blocked an unrelated descriptor's admission: "
        + before.reason
    )
