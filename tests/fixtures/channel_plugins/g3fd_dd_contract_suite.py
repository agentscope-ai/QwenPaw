"""Bounded public QR contract controls, independent of native platform SDKs."""

import hashlib
from time import monotonic

from fastapi import HTTPException
import pytest

from g3fd_dd_session_support import (
    g3_host_import_boundary,
    g3_qr,
    local_management_http,
    management_runtime,
)

__all__ = [
    "g3_host_import_boundary",
    "g3_qr",
    "local_management_http",
    "management_runtime",
]


def result_packet(operation, result):
    return {
        "request_id": "d095974b-e2f1-4e78-81e2-47767df96632",
        "plugin_id": "management_sample",
        "workspace_id": "A",
        "channel_key": "management_sample",
        "instance_id": "contract-fixture",
        "generation": 1,
        "source_revision": "a" * 64,
        "operation": operation,
        "outcome": "ok",
        "reason_code": None,
        "result": result,
    }


def fetch_result(**extra):
    return {
        "scan_url": "https://fixture.invalid/scan",
        "continuation": "fixture-continuation",
        **extra,
    }


def poll_result(**extra):
    return {
        "status": "success",
        "credentials": {"api_token": "issued"},
        **extra,
    }


def test_optional_dto_fields_preserve_legacy_wire_and_closed_shape():
    from qwenpaw.channel_protocol.errors import ProtocolValidationError
    from qwenpaw.channel_protocol.management import ManagementResult

    for operation, result in (
        ("qrcode.fetch", fetch_result()),
        ("qrcode.poll", poll_result()),
    ):
        packet = result_packet(operation, result)
        assert ManagementResult.from_mapping(packet).to_mapping() == packet
        with pytest.raises(ProtocolValidationError):
            ManagementResult.from_mapping(
                result_packet(operation, {**result, "untrusted_option": 1})
            )


@pytest.mark.parametrize("ttl", [True, 0, 7201, "300"])
def test_fetch_ttl_rejects_invalid_hint(ttl):
    from qwenpaw.channel_protocol.errors import ProtocolValidationError
    from qwenpaw.channel_protocol.management import ManagementResult

    with pytest.raises(ProtocolValidationError):
        ManagementResult.from_mapping(
            result_packet("qrcode.fetch", fetch_result(expires_in_seconds=ttl))
        )


def test_metadata_is_bounded_string_map_and_cannot_shadow_credentials():
    from qwenpaw.channel_protocol.errors import ProtocolValidationError
    from qwenpaw.channel_protocol.management import ManagementResult

    for metadata in (
        {"api_token": "shadow"},
        {str(i): "value" for i in range(17)},
        {"open_id": 1},
        {"x" * 129: "value"},
        {"open_id": "x" * 8193},
    ):
        with pytest.raises(ProtocolValidationError):
            ManagementResult.from_mapping(
                result_packet("qrcode.poll", poll_result(metadata=metadata))
            )
    packet = result_packet(
        "qrcode.poll", poll_result(metadata={"open_id": "", "brand": "lark"})
    )
    assert ManagementResult.from_mapping(packet).to_mapping() == packet


def session(qr, token):
    return qr.sessions._sessions[hashlib.sha256(token.encode()).hexdigest()]


@pytest.mark.asyncio
@pytest.mark.parametrize("hint", [None, 7200])
async def test_actual_fetch_lifetime_and_terminal_custody_are_bounded(
    g3_qr, hint
):
    qr = g3_qr
    scope = qr.scope()
    qr.http.response = fetch_result(
        **({"expires_in_seconds": hint} if hint is not None else {})
    )
    before = monotonic()
    fetched = await qr.sessions.fetch(scope, {})
    after = monotonic()
    held = session(qr, fetched.poll_token)
    expected = 300 if hint is None else hint
    assert before + expected <= held.expires <= after + expected
    qr.http.response = poll_result()
    await qr.sessions.poll(scope, fetched.poll_token)
    assert 0 < held.expires - monotonic() <= 60
    await qr.sessions.cancel(scope, fetched.poll_token)
    assert held.lease not in qr.rt.owners.leases()
    assert not held.credentials and not held.metadata and not held.continuation


@pytest.mark.asyncio
async def test_actual_metadata_is_returned_but_not_required_for_save(g3_qr):
    qr = g3_qr
    scope = qr.scope()
    fetched = await qr.sessions.fetch(scope, {})
    metadata = {"open_id": "identity-only", "tenant_brand": "lark"}
    qr.http.response = poll_result(metadata=metadata)
    result = await qr.sessions.poll(scope, fetched.poll_token)
    assert result.status == "success"
    assert result.credentials == {"api_token": "issued", **metadata}
    with pytest.raises(HTTPException) as mismatch:
        async with qr.sessions.authorize_save(scope, fetched.poll_token, {}):
            pytest.fail("missing real credential was accepted")
    assert mismatch.value.status_code == 403
    async with qr.sessions.authorize_save(
        scope, fetched.poll_token, {"api_token": "issued"}
    ):
        pass


@pytest.mark.asyncio
async def test_actual_host_rejects_metadata_named_as_persisted_config(g3_qr):
    from qwenpaw.app.channels.management import ManagementError

    qr = g3_qr
    scope = qr.scope()
    fetched = await qr.sessions.fetch(scope, {})
    # A different schema field, so this passes the DTO's credential-disjoint
    # check and must be rejected by the host's trusted schema check.
    qr.http.response = poll_result(
        metadata={"behavior": "configuration-shadow"}
    )
    with pytest.raises(ManagementError) as rejected:
        await qr.sessions.poll(scope, fetched.poll_token)
    assert rejected.value.reason_code == "MANAGEMENT_INVALID_RESULT"
    assert len(qr.http.requests) == 2


@pytest.mark.asyncio
async def test_actual_empty_credentials_cannot_become_success(g3_qr):
    from qwenpaw.app.channels.management import ManagementError

    qr = g3_qr
    scope = qr.scope()
    fetched = await qr.sessions.fetch(scope, {})
    qr.http.response = poll_result(
        credentials={}, metadata={"open_id": "user"}
    )
    with pytest.raises(ManagementError) as rejected:
        await qr.sessions.poll(scope, fetched.poll_token)
    assert rejected.value.reason_code == "MANAGEMENT_INVALID_RESULT"
    assert session(qr, fetched.poll_token).lease not in qr.rt.owners.leases()


@pytest.mark.asyncio
async def test_direct_service_path_injection_remains_rejected(g3_qr):
    from qwenpaw.app.channels.management import ManagementError
    from management_process_suite import KEY

    qr = g3_qr
    with pytest.raises(ManagementError) as rejected:
        await qr.rt.service.execute(
            "A",
            KEY,
            "qrcode.fetch",
            {
                "config": {
                    "enabled": False,
                    "host": qr.http.host,
                    "port": qr.http.port,
                    "media_dir": "/private/tmp/injected",
                }
            },
            timeout=3,
        )
    assert rejected.value.reason_code == "MANAGEMENT_INVALID_REQUEST"
    assert qr.http.requests == []
