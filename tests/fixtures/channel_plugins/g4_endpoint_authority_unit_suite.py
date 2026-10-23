"""Unit-only observation combinations; these are not real-process proofs."""

import copy
from types import SimpleNamespace

import pytest


def endpoint(**changes):
    return {
        "channel_key": "external",
        "instance_id": "instance",
        "generation": 7,
        "protocol": "http+ws",
        "host": "127.0.0.1",
        "port": 18777,
        "path": "/hook",
        "public_base_url": None,
        "readiness": "ready",
        "bound_externally": False,
        "auth_required": True,
        "quiescing": False,
        **changes,
    }


class ObservationSource:
    """Unit input for authority decisions, never a real process."""

    def __init__(self):
        self.value = {
            "generation": 7,
            "pid": 12345,
            "run_id": 77,
            "mode": "run",
            "run_requested": True,
            "process_alive": True,
            "transport_open": True,
            "ready_confirmed": True,
            "enabled": True,
            "state": "ready",
            "platform_state": "connected",
            "channel_key": "external",
            "instance_id": "instance",
            "source_revision": "revision",
            "hello": {
                "channel_key": "external",
                "instance_id": "instance",
                "generation": 7,
                "source_revision": "revision",
                "capabilities": ["ingress_endpoint"],
            },
        }

    def endpoint_observation(self):
        return copy.deepcopy(self.value)


@pytest.fixture
def unit_service():
    from qwenpaw.channel_protocol.host import (
        SharedEndpointAuthority,
        SharedEndpointService,
    )

    process = ObservationSource()
    gates = SimpleNamespace(enabled=True, ingress=True)
    authority = SharedEndpointAuthority(
        channel_key="external",
        instance_id="instance",
        source_revision="revision",
        capabilities=["ingress_endpoint"],
        process=process,
        enabled=lambda: gates.enabled,
        ingress_open=lambda: gates.ingress,
    )
    return (
        SharedEndpointService(
            authority=authority, plugin_id="owner", workspace_id="workspace"
        ),
        process,
        gates,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "changes",
    [
        {"mode": "probe"},
        {"mode": "manage"},
        {"mode": "audit"},
        {"run_requested": False},
        {"process_alive": False},
        {"transport_open": False},
        {"ready_confirmed": False},
        {"enabled": False},
        {"state": "stopped"},
        {"state": "residual"},
        {"state": "failed"},
        {"state": "backoff"},
        {"hello": None},
        {"channel_key": "other"},
        {"instance_id": "other"},
        {"source_revision": "other"},
    ],
)
async def test_unit_invalid_run_observations_reject_registration(
    unit_service, changes
):
    from qwenpaw.channel_protocol.errors import RPC_FENCING_ERROR, RpcError

    service, process, _ = unit_service
    process.value.update(changes)
    with pytest.raises(RpcError) as caught:
        await service.register(endpoint())
    assert caught.value.code == RPC_FENCING_ERROR
    assert service.resolve() is None
    assert service.registry.snapshot() == {}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "changes",
    [
        {"generation": 6},
        {"channel_key": "other"},
        {"instance_id": "other"},
        {"source_revision": "other"},
        {"capabilities": []},
    ],
)
async def test_unit_hello_identity_must_match_current_launch(
    unit_service, changes
):
    from qwenpaw.channel_protocol.errors import RPC_FENCING_ERROR, RpcError

    service, process, _ = unit_service
    process.value["hello"].update(changes)
    with pytest.raises(RpcError) as caught:
        await service.register(endpoint())
    assert caught.value.code == RPC_FENCING_ERROR
    assert service.resolve() is None


@pytest.mark.asyncio
async def test_unit_settled_ready_future_health_starting_can_register_not_resolve(  # noqa: E501
    unit_service,
):
    service, process, _ = unit_service
    process.value.update(state="starting", platform_state="connecting")
    assert (await service.register(endpoint()))["status"] == "registered"
    assert service.resolve() is None
    process.value["state"] = "ready"
    assert service.resolve() is None
    process.value["platform_state"] = "connected"
    reference = service.resolve()
    assert reference is not None and service.is_current(reference)
    slot = service.authority.endpoint_snapshot(7)
    assert slot.lease_token is None and slot.lease_expires_at_ms is None


@pytest.mark.asyncio
@pytest.mark.parametrize("key,new", [("run_id", 78), ("pid", 12346)])
async def test_unit_same_generation_new_run_cannot_reuse_previous_endpoint(
    unit_service, key, new
):
    from qwenpaw.channel_protocol.errors import RpcError

    service, process, _ = unit_service
    await service.register(endpoint())
    reference = service.resolve()
    process.value[key] = new
    assert service.resolve() is None and not service.is_current(reference)
    with pytest.raises(RpcError) as caught:
        await service.register(endpoint())
    assert caught.value.data["reason_code"] == "GENERATION_REVOKED"


@pytest.mark.asyncio
@pytest.mark.parametrize("retirement", ["disabled", "failed", "new_run"])
async def test_unit_pause_cannot_restore_retired_endpoint_authority(
    unit_service, retirement
):
    from qwenpaw.channel_protocol.errors import RpcError

    service, process, gates = unit_service
    await service.register(endpoint())
    reference = service.resolve()
    gates.ingress = False
    assert service.resolve() is None
    if retirement == "disabled":
        gates.enabled = False
    elif retirement == "failed":
        process.value["state"] = "failed"
    else:
        process.value["run_id"] += 1
    assert service.resolve() is None
    gates.enabled = True
    gates.ingress = True
    process.value["state"] = "ready"
    assert service.resolve() is None
    assert not service.is_current(reference)
    with pytest.raises(RpcError) as caught:
        await service.register(endpoint())
    assert caught.value.data["reason_code"] == "GENERATION_REVOKED"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "changes",
    [
        {"protocol": "tcp"},
        {"protocol": "https"},
        {"port": 0},
        {"port": 65536},
        {"port": -1},
        {"port": True},
        {"path": "relative"},
        {"path": "/hook?query=1"},
        {"path": "/hook#fragment"},
        {"path": "/a/../hook"},
        {"path": "/%2e%2e/hook"},
        {"path": "/%252e%252e/hook"},
        {"path": "//external/hook"},
        {"path": "/./hook"},
        {"path": "/a\\b"},
        {"path": "/a%3fb"},
        {"path": "/a\nb"},
        {"host": "127.0.0.1/path"},
        {"host": "http://127.0.0.1"},
        {"host": "127.0.0.1@evil"},
        {"host": "127.0.0.1?evil"},
        {"host": " 127.0.0.1"},
        {"host": "[::1]evil"},
        {"host": "fe80::1%en0"},
    ],
)
async def test_unit_target_validation_rejects_ambiguous_or_invalid_values(
    unit_service, changes
):
    from qwenpaw.channel_protocol.errors import RpcError

    service, _, _ = unit_service
    with pytest.raises(RpcError):
        await service.register(endpoint(**changes))
    assert service.resolve() is None and service.registry.snapshot() == {}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "host,fixed",
    [
        ("127.0.0.1", "127.0.0.1"),
        ("127.9.8.7", "127.9.8.7"),
        ("::1", "::1"),
        ("[::1]", "::1"),
        ("localhost", "127.0.0.1"),
    ],
)
async def test_unit_forwarding_loopback_is_fixed_without_dns(
    unit_service, host, fixed, monkeypatch
):
    import socket

    service, _, _ = unit_service

    def forbidden_dns(*_args, **_kwargs):
        pytest.fail("A1 must not resolve DNS or connect upstream")

    monkeypatch.setattr(socket, "getaddrinfo", forbidden_dns)
    await service.register(endpoint(host=host))
    reference = service.resolve(forwarding=True)
    assert reference.loopback_host == fixed
    assert service.is_current(reference, forwarding=True)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "host", ["192.0.2.1", "0.0.0.0", "::", "external.invalid"]
)
async def test_unit_external_standalone_requires_auth_and_never_forwards(
    unit_service, host
):
    from qwenpaw.channel_protocol.errors import RPC_AUTH_ERROR, RpcError

    service, _, _ = unit_service
    with pytest.raises(RpcError) as caught:
        await service.register(
            endpoint(host=host, bound_externally=False, auth_required=False)
        )
    assert caught.value.code == RPC_AUTH_ERROR
    await service.register(
        endpoint(
            host=host,
            bound_externally=False,
            auth_required=True,
            public_base_url="https://127.0.0.1:18777/",
        )
    )
    reference = service.resolve()
    assert reference.endpoint.bound_externally is True
    assert reference.loopback_host is None
    assert service.resolve(forwarding=True) is None
    assert not service.is_current(reference, forwarding=True)


@pytest.mark.asyncio
@pytest.mark.parametrize("protocol", ["http", "ws", "http+ws"])
async def test_unit_protocol_and_port_limits_and_starting_zero(
    unit_service, protocol
):
    from qwenpaw.channel_protocol.models import EndpointParams

    service, _, _ = unit_service
    await service.register(
        EndpointParams.from_mapping(endpoint(protocol=protocol, port=1))
    )
    assert service.resolve().endpoint.port == 1
    await service.update(endpoint(protocol=protocol, port=65535))
    assert service.resolve().endpoint.port == 65535
    await service.update(
        endpoint(protocol=protocol, port=0, readiness="starting")
    )
    assert service.resolve() is None


@pytest.mark.asyncio
async def test_unit_descriptor_without_ingress_capability_is_rejected(
    unit_service,
):
    from qwenpaw.channel_protocol.errors import RPC_CAPABILITY_ERROR, RpcError

    service, process, _ = unit_service
    service.authority.capabilities = frozenset()
    process.value["hello"]["capabilities"] = []
    with pytest.raises(RpcError) as caught:
        await service.register(endpoint())
    assert caught.value.code == RPC_CAPABILITY_ERROR
