# -*- coding: utf-8 -*-
"""Registry routing authorized by the current shared worker observation."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from qwenpaw.channel_protocol import (
    CoreEndpointRegistry,
    EndpointParams,
    RpcError,
)
from qwenpaw.channel_protocol.host import SharedEndpointAuthority
from tests.unit.channel_isolation._ch_0_004_support import _endpoint, _identity


@pytest.fixture
def shared_registry():
    """Supply real authority decisions with an explicit process observation."""
    identity = {**_identity(), "source_revision": "revision"}
    observation = {
        **identity,
        "pid": 12345,
        "run_id": 77,
        "mode": "run",
        "run_requested": True,
        "enabled": True,
        "process_alive": True,
        "transport_open": True,
        "ready_confirmed": True,
        "state": "ready",
        "platform_state": "connected",
        "hello": {**identity, "capabilities": ["ingress_endpoint"]},
    }
    authority = SharedEndpointAuthority(
        channel_key="voice",
        instance_id="instance-1",
        source_revision="revision",
        capabilities=["ingress_endpoint"],
        process=SimpleNamespace(endpoint_observation=lambda: observation),
        enabled=lambda: True,
        ingress_open=lambda: True,
    )
    registry = CoreEndpointRegistry(
        channel_key="voice",
        instance_id="instance-1",
        authority=authority,
    )
    return registry, observation


def test_endpoint_registry_must_match_authority_identity(
    shared_registry,
) -> None:
    """Endpoint storage cannot diverge from its shared authority identity."""
    registry, _ = shared_registry
    with pytest.raises(ValueError, match="identity must match"):
        CoreEndpointRegistry(
            channel_key="other",
            instance_id="instance-1",
            authority=registry.authority,
        )


@pytest.mark.parametrize(
    "field,value,reason",
    [
        ("channel_key", "other", "CHANNEL_KEY_MISMATCH"),
        ("instance_id", "other-instance", "INSTANCE_ID_MISMATCH"),
    ],
)
def test_endpoint_identity_must_match_current_run(
    shared_registry,
    field,
    value,
    reason,
) -> None:
    """An endpoint cannot register under another channel or instance."""
    registry, _ = shared_registry
    endpoint = EndpointParams.from_mapping(
        {**_endpoint().to_mapping(), field: value},
    )
    with pytest.raises(RpcError) as caught:
        registry.register(endpoint)
    assert caught.value.data["reason_code"] == reason
    assert registry.snapshot() == {}


@pytest.mark.parametrize(
    ("readiness", "quiescing", "expected"),
    [
        ("starting", False, False),
        ("ready", False, True),
        ("degraded", False, False),
        ("stopped", False, False),
        ("ready", True, False),
    ],
)
def test_endpoint_readiness_controls_formal_routing(
    shared_registry,
    readiness: str,
    quiescing: bool,
    expected: bool,
) -> None:
    """Only ready, non-quiescing endpoints accept formal traffic."""
    registry, _ = shared_registry
    endpoint = EndpointParams.from_mapping(
        {
            **_endpoint().to_mapping(),
            "readiness": readiness,
            "quiescing": quiescing,
        },
    )
    registry.register(endpoint)
    assert (registry.resolve(7) is not None) is expected


def test_ready_update_recovers_only_before_lifecycle_revoke(
    shared_registry,
) -> None:
    """Health updates recover a route; a fence requires a fresh generation."""
    registry, observation = shared_registry
    degraded = EndpointParams.from_mapping(
        {**_endpoint().to_mapping(), "readiness": "degraded"},
    )
    registry.register(degraded)
    assert registry.resolve(7) is None
    registry.register(_endpoint())
    assert registry.resolve(7) == _endpoint()
    registry.authority.fence()
    assert registry.resolve(7) is None
    with pytest.raises(RpcError) as update_error:
        registry.register(_endpoint())
    assert update_error.value.data["reason_code"] == "GENERATION_REVOKED"

    observation.update(generation=8, pid=12346, run_id=78)
    observation["hello"] = {**observation["hello"], "generation": 8}
    next_endpoint = EndpointParams.from_mapping(
        {**_endpoint().to_mapping(), **_identity(generation=8)},
    )
    registry.register(next_endpoint)
    assert registry.resolve(8) == next_endpoint
    assert registry.resolve(7) is None


def test_new_generation_fences_late_old_updates(shared_registry) -> None:
    """A newer shared run prevents old generation traffic from returning."""
    registry, observation = shared_registry
    registry.register(_endpoint())
    assert registry.resolve(7) == _endpoint()
    observation.update(generation=8, pid=12346, run_id=78)
    observation["hello"] = {**observation["hello"], "generation": 8}
    next_endpoint = EndpointParams.from_mapping(
        {**_endpoint().to_mapping(), **_identity(generation=8)},
    )
    # A fresh run never inherits the old endpoint, even before registration.
    assert registry.resolve(7) is None
    assert registry.resolve(8) is None
    registry.register(next_endpoint)
    registry.prune()
    assert registry.snapshot() == {8: next_endpoint}
    with pytest.raises(RpcError) as old_update:
        registry.register(_endpoint())
    assert old_update.value.data["reason_code"] == "GENERATION_REVOKED"
    assert registry.resolve(8) == next_endpoint


@pytest.mark.parametrize("field,value", [("pid", 12346), ("run_id", 78)])
def test_restarted_run_cannot_reuse_old_endpoint(
    shared_registry,
    field,
    value,
) -> None:
    """Reusing a generation cannot transfer an endpoint to another process."""
    registry, observation = shared_registry
    registry.register(_endpoint())
    assert registry.resolve(7) == _endpoint()
    observation[field] = value
    assert registry.resolve(7) is None
    with pytest.raises(RpcError) as caught:
        registry.register(_endpoint())
    assert caught.value.data["reason_code"] == "GENERATION_REVOKED"
    assert registry.snapshot() == {}
