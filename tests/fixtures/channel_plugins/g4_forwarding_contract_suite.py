"""G4-A3 wire contracts; no forwarding implementation is assumed."""

import pytest


PATHS = ["/voice/incoming", "/voice/ws", "/voice/status-callback"]
BRIDGE_SECRET = "bridge-secret-local-a1b2c3d4e5f6g7h8"


def binding_mapping():
    return {
        "route_query_key": "_qp_endpoint",
        "route_selector": "d6e7929c48d64249ad91b11b6d463f55",
        "host_port": 18778,
        "paths": list(PATHS),
        "bridge_token": BRIDGE_SECRET,
    }


def test_host_forwarding_binding_wire_contract():
    from qwenpaw.channel_protocol import models
    from qwenpaw.channel_protocol.errors import ProtocolValidationError

    binding_type = getattr(models, "HostForwardingBinding", None)
    assert binding_type is not None, "Missing SDK-free HostForwardingBinding"
    value = binding_mapping()
    binding = binding_type.from_mapping(value)
    assert binding.to_mapping() == value
    assert BRIDGE_SECRET not in repr(binding)
    assert BRIDGE_SECRET not in str(binding)
    invalid = [
        {**value, "unknown": "must reject"},
        {**value, "route_query_key": "workspace"},
        *({**value, "route_selector": item} for item in (None, "", 1)),
        *({**value, "host_port": item} for item in (0, 65536, True, "18778")),
        {**value, "paths": "/voice/incoming"},
        {**value, "paths": [1]},
        *({**value, "bridge_token": item} for item in (None, "", 1)),
    ]
    for malformed in invalid:
        with pytest.raises(ProtocolValidationError):
            binding_type.from_mapping(malformed)


def test_endpoint_registration_result_wire_contract():
    from qwenpaw.channel_protocol import models
    from qwenpaw.channel_protocol.errors import ProtocolValidationError

    result_type = getattr(models, "EndpointRegistrationResult", None)
    assert result_type is not None, "Missing EndpointRegistrationResult"
    base = {"status": "registered", "generation": 7, "readiness": "ready"}
    # Existing standalone ACK remains readable with absent or null forwarding.
    for legacy in (base, {**base, "forwarding": None}):
        parsed = result_type.from_mapping(legacy)
        encoded = parsed.to_mapping()
        assert {key: encoded[key] for key in base} == base
        assert encoded.get("forwarding") is None
        assert set(encoded) <= {*base, "forwarding"}
    for status in ("registered", "updated"):
        value = {**base, "status": status, "forwarding": binding_mapping()}
        result = result_type.from_mapping(value)
        assert result.to_mapping() == value
        assert BRIDGE_SECRET not in repr(result)
    invalid = [
        {**base, "unknown": "must reject"},
        {**base, "status": "unregistered"},
        *({**base, "generation": item} for item in (0, -1, True, "7")),
        {**base, "readiness": "invented"},
        {**base, "readiness": 1},
        {**base, "forwarding": []},
        {**base, "forwarding": {**binding_mapping(), "unknown": "reject"}},
    ]
    for malformed in invalid:
        with pytest.raises(ProtocolValidationError):
            result_type.from_mapping(malformed)
