"""Transient QR options remain separate from strict saved configuration."""
import hashlib

import pytest

from g3fd_dd_contract_suite import result_packet
from g3fd_dd_session_support import (
    g3_host_import_boundary,
    g3_qr,
    local_management_http,
    management_runtime,
)
from management_process_suite import KEY

__all__ = [
    "g3_host_import_boundary",
    "g3_qr",
    "local_management_http",
    "management_runtime",
]


def request_packet(operation="qrcode.fetch", options=None):
    value = result_packet(operation, {})
    for key in ("result", "outcome", "reason_code"):
        value.pop(key)
    value["timeout_ms"] = 3000
    parameters = {"config": {}}
    if operation == "qrcode.poll":
        parameters["continuation"] = "continuation"
    elif operation == "connection.verify":
        parameters["level"] = "reachability"
    if options is not None:
        parameters["options"] = options
    value["parameters"] = parameters
    return value


def test_options_preserve_legacy_wire_and_are_rejected_for_verify():
    from qwenpaw.channel_protocol.management import ManagementRequest
    from qwenpaw.channel_protocol.errors import ProtocolValidationError

    for operation in ("qrcode.fetch", "qrcode.poll"):
        packet = request_packet(operation)
        assert ManagementRequest.from_mapping(packet).to_mapping() == packet
        packet = request_packet(operation, {"domain": "lark"})
        assert ManagementRequest.from_mapping(packet).to_mapping() == packet
    with pytest.raises(ProtocolValidationError):
        ManagementRequest.from_mapping(request_packet("connection.verify", {}))


@pytest.mark.parametrize(
    "options",
    [
        {str(i): "value" for i in range(17)},
        {"domain": None},
        {"x" * 129: "v"},
        {"domain": "x" * 8193},
        {str(i): "x" * 8192 for i in range(16)},
    ],
)
def test_options_bounds_reject_malformed_or_oversized_packet(options):
    from qwenpaw.channel_protocol.management import ManagementRequest
    from qwenpaw.channel_protocol.errors import ProtocolValidationError

    with pytest.raises(ProtocolValidationError):
        ManagementRequest.from_mapping(request_packet(options=options))


@pytest.mark.asyncio
async def test_actual_session_freezes_options_for_fetch_and_poll(g3_qr):
    qr = g3_qr
    scope = qr.scope()
    options = {"behavior": "temporary-option-secret"}
    fetched = await qr.sessions.fetch(scope, options)
    held = qr.sessions._sessions[
        hashlib.sha256(fetched.poll_token.encode()).hexdigest()
    ]
    assert "temporary-option-secret" not in repr(held)
    options["behavior"] = "changed-after-fetch"
    await qr.sessions.poll(scope, fetched.poll_token)
    assert [row["options"] for row in qr.http.requests] == [
        {"behavior": "temporary-option-secret"},
        {"behavior": "temporary-option-secret"},
    ]
    assert all(
        row["config"]["behavior"] == "normal" for row in qr.http.requests
    )
    await qr.sessions.cancel(scope, fetched.poll_token)
    assert held.options == {}
    assert held.lease not in qr.rt.owners.leases()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "options", [{"undeclared": "x"}, {"media_dir": "/private/tmp/injected"}]
)
async def test_actual_service_refuses_undeclared_or_private_options(
    g3_qr, options
):
    from qwenpaw.app.channels.management import ManagementError

    qr = g3_qr
    with pytest.raises(ManagementError) as error:
        await qr.rt.service.execute(
            "A",
            KEY,
            "qrcode.fetch",
            {
                "config": {
                    "enabled": False,
                    "host": qr.http.host,
                    "port": qr.http.port,
                },
                "options": options,
            },
            timeout=3,
        )
    assert error.value.reason_code == "MANAGEMENT_INVALID_REQUEST"
    assert not qr.http.requests


@pytest.mark.asyncio
async def test_options_cannot_repair_invalid_saved_configuration(g3_qr):
    from qwenpaw.app.channels.management import ManagementError

    qr = g3_qr
    with pytest.raises(ManagementError) as error:
        await qr.rt.service.execute(
            "A",
            KEY,
            "qrcode.fetch",
            {
                "config": {
                    "enabled": "not-bool",
                    "host": qr.http.host,
                    "port": qr.http.port,
                },
                "options": {"enabled": "false"},
            },
            timeout=3,
        )
    assert error.value.reason_code == "MANAGEMENT_INVALID_REQUEST"
    assert not qr.http.requests
