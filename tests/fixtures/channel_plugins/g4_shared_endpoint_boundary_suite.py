"""G4-A1 exact ownership, run/route fences and endpoint input boundaries."""

import asyncio
from dataclasses import FrozenInstanceError, replace
import json

import pytest

from extension_process_suite import eventually
from g4_shared_endpoint_suite import endpoint_source

pytest_plugins = ["extension_process_suite"]


def boundary_source(directory, key, *, capabilities=None):
    source = endpoint_source(directory, key, capabilities=capabilities)
    path = source / key / "driver.py"
    body = path.read_text()
    old = """        endpoint = EndpointParams.from_mapping({
            **self._context.identity.to_mapping(), **params["endpoint"],
        })
        result = await self._context.peer.call(
            "ingress.endpoint.register", endpoint.to_mapping(),
        )"""
    new = """        from qwenpaw.channel_protocol.models import IdentityParams
        operation = params.get("operation", "register")
        assert operation in {"register", "update", "unregister"}
        identity = {**self._context.identity.to_mapping(),
                    **params.get("identity", {})}
        endpoint = (IdentityParams.from_mapping(identity)
                    if operation == "unregister" else
                    EndpointParams.from_mapping({**identity,
                                                 **params["endpoint"]}))
        result = await self._context.peer.call(
            "ingress.endpoint." + operation, endpoint.to_mapping(),
        )"""
    assert body.count(old) == 1
    body = body.replace(old, new)
    needle = '("fixture.endpoint", self.endpoint),'
    assert body.count(needle) == 1
    body = body.replace(
        needle,
        needle
        + """
            ("fixture.platform_state", self.platform_state),
            ("fixture.crash", self.crash),""",
    )
    body += """

    async def platform_state(self, params, _request):
        await self._context.set_platform_state(params["state"])
        return {}

    async def crash(self, _params, _request):
        os._exit(23)
"""
    path.write_text(body)
    return source


def endpoint(**changes):
    return {
        "protocol": "ws",
        "host": "127.0.0.1",
        "port": 18777,
        "path": "/ws",
        "public_base_url": None,
        "readiness": "ready",
        "bound_externally": False,
        "auth_required": True,
        "quiescing": False,
        **changes,
    }


async def child_endpoint(rt, operation="register", identity=None, **changes):
    return await rt.process.call(
        "fixture.endpoint",
        {
            "operation": operation,
            "endpoint": endpoint(**changes),
            "identity": identity or {},
        },
    )


@pytest.mark.asyncio
async def test_actual_same_generation_revision_and_unregister_fence(runtime):
    rt = await runtime(source_factory=boundary_source)
    service = rt.channel.endpoint_service
    await child_endpoint(rt)
    first = service.resolve()
    assert first is not None and first.endpoint.port == 18777
    assert first.source_revision == rt.channel._launch_spec.source_revision
    assert service.is_current(first, forwarding=True)
    assert not service.is_current(replace(first), forwarding=True)
    with pytest.raises(FrozenInstanceError):
        first.revision = -1
    changed = await child_endpoint(rt, "update", port=18778)
    assert changed["registration"]["status"] == "updated"
    second = service.resolve()
    assert second.endpoint.generation == first.endpoint.generation
    assert second.revision > first.revision and second.endpoint.port == 18778
    assert not service.is_current(first) and service.is_current(second)
    for _ in range(2):
        result = await child_endpoint(rt, "unregister")
        assert result["registration"]["status"] == "unregistered"
        assert service.resolve() is None and not service.is_current(second)


@pytest.mark.asyncio
async def test_actual_connecting_registration_waits_for_connected_resolution(
    runtime,
):
    rt = await runtime(source_factory=boundary_source)
    service = rt.channel.endpoint_service
    await rt.process.call("fixture.platform_state", {"state": "connecting"})
    await eventually(
        lambda: rt.process.health_snapshot()["platform_state"] == "connecting"
    )
    starting = await child_endpoint(rt, readiness="starting", port=0)
    assert starting["registration"]["readiness"] == "starting"
    assert service.resolve() is None
    await child_endpoint(rt, "update")
    assert service.resolve() is None
    await rt.process.call("fixture.platform_state", {"state": "connected"})
    await eventually(lambda: service.resolve() is not None)
    reference = service.resolve()
    await child_endpoint(rt, "update", quiescing=True)
    assert service.resolve() is None and not service.is_current(reference)


@pytest.mark.asyncio
@pytest.mark.parametrize("gate", ["enabled", "ingress"])
async def test_actual_host_gate_closes_synchronously_with_distinct_resume_rules(  # noqa: E501
    runtime, gate
):
    from qwenpaw.channel_protocol.errors import RpcError

    rt = await runtime(source_factory=boundary_source)
    await child_endpoint(rt)
    service, channel = rt.channel.endpoint_service, rt.channel
    reference = service.resolve()
    assert reference is not None
    if gate == "enabled":
        channel.enabled = False
    else:
        channel.set_enqueue_async(None)
    # No await between host gate mutation and exact-reference invalidation.
    assert service.resolve() is None and not service.is_current(reference)
    if gate == "enabled":
        channel.enabled = True
    else:
        channel._ingress_open = True
        assert service.resolve() is reference
        assert service.is_current(reference, forwarding=True)
        return
    assert service.resolve() is None
    with pytest.raises(RpcError) as caught:
        await child_endpoint(rt)
    assert caught.value.data["reason_code"] == "GENERATION_REVOKED"


@pytest.mark.asyncio
async def test_actual_stop_fences_before_awaiting_process_shutdown(
    runtime, monkeypatch
):
    rt = await runtime(source_factory=boundary_source)
    await child_endpoint(rt)
    service = rt.channel.endpoint_service
    reference = service.resolve()
    actual = rt.process.stop
    entered, release = asyncio.Event(), asyncio.Event()

    async def gated_actual_stop(*args, **kwargs):
        entered.set()
        await release.wait()
        return await actual(*args, **kwargs)

    monkeypatch.setattr(rt.process, "stop", gated_actual_stop)
    stopping = asyncio.create_task(rt.channel.stop())
    try:
        async with asyncio.timeout(3):
            await entered.wait()
        assert not stopping.done()
        assert rt.process.endpoint_observation()["process_alive"]
        assert service.resolve() is None and not service.is_current(reference)
    finally:
        release.set()
        result = await stopping
    assert (
        result.exited
        and not rt.process.endpoint_observation()["process_alive"]
    )


@pytest.mark.asyncio
async def test_actual_crash_restart_and_old_unregister_preserve_new_generation(
    runtime,
):
    from qwenpaw.app.channels.process_supervisor import ChannelCallUnknown

    rt = await runtime(source_factory=boundary_source)
    await child_endpoint(rt)
    service = rt.channel.endpoint_service
    old = service.resolve()
    old_identity = rt.channel._identity().to_mapping()
    with pytest.raises(ChannelCallUnknown):
        await rt.process.call("fixture.crash", {})
    assert service.resolve() is None and not service.is_current(old)
    # This registered manager uses restart_limit=0. Obtain a new owned
    # generation through its real lifecycle rather than forging a lease for
    # an independently auto-restarted child.
    await rt.loader.lifecycle.set_enabled(rt.key, False)
    assert service.resolve() is None and not service.is_current(old)
    await rt.loader.lifecycle.set_enabled(rt.key, True)
    rt.channel = await rt.manager.get_channel(rt.key)
    rt.process = rt.channel.channel_process
    await eventually(
        lambda: rt.process.health_snapshot()["state"] == "ready"
        and rt.process.health_snapshot()["platform_state"] == "connected"
    )
    assert rt.channel._identity().instance_id == old_identity["instance_id"]
    assert rt.channel._runtime_lease.generation > old.endpoint.generation
    service = rt.channel.endpoint_service
    await child_endpoint(rt, port=18779)
    current = service.resolve()
    assert current.endpoint.generation > old.endpoint.generation
    assert not service.is_current(old) and service.is_current(current)
    await child_endpoint(rt, "unregister", identity=old_identity)
    assert service.resolve() is current and service.is_current(current)
    assert set(service.registry._entries) == {current.endpoint.generation}


@pytest.mark.asyncio
async def test_actual_child_wrong_identity_and_extra_owner_fields_are_rejected(
    runtime,
):
    from qwenpaw.channel_protocol.errors import RpcError

    rt = await runtime(source_factory=boundary_source)
    await child_endpoint(rt)
    current = rt.channel.endpoint_service.resolve()
    for change, reason in (
        ({"channel_key": "other"}, "CHANNEL_KEY_MISMATCH"),
        ({"instance_id": "other"}, "INSTANCE_ID_MISMATCH"),
        (
            {"generation": current.endpoint.generation + 1},
            "GENERATION_UNKNOWN",
        ),
    ):
        with pytest.raises(RpcError) as caught:
            await child_endpoint(rt, identity=change)
        assert caught.value.data["reason_code"] == reason
        assert rt.channel.endpoint_service.resolve() is current
    with pytest.raises(RpcError):
        await rt.channel.endpoint_service.register(
            {**current.endpoint.to_mapping(), "plugin_id": "spoofed"}
        )
    assert rt.channel.endpoint_service.resolve() is current


@pytest.mark.asyncio
async def test_actual_runtime_reference_contains_trusted_host_owner(runtime):
    rt = await runtime(source_factory=boundary_source)
    await child_endpoint(rt)
    reference = rt.channel.endpoint_service.resolve()
    lease = rt.channel._runtime_lease
    assert (
        reference.plugin_id
        == lease.plugin_id
        == rt.channel._registration.plugin_id
    )
    assert reference.workspace_id == lease.key.scope_id


def no_endpoint_capability_source(directory, key, *, capabilities=None):
    source = boundary_source(directory, key, capabilities=capabilities)
    path = source / "channel.json"
    value = json.loads(path.read_text())
    value["capabilities"].remove("ingress_endpoint")
    path.write_text(json.dumps(value))
    return source


@pytest.mark.asyncio
async def test_actual_descriptor_without_ingress_capability_cannot_register(
    runtime,
):
    from qwenpaw.channel_protocol.errors import RPC_CAPABILITY_ERROR, RpcError

    rt = await runtime(source_factory=no_endpoint_capability_source)
    with pytest.raises(RpcError) as caught:
        await child_endpoint(rt)
    assert caught.value.code == RPC_CAPABILITY_ERROR
    assert rt.channel.endpoint_service.resolve() is None


def test_client_owner_config_cannot_override_trusted_launch_identity(tmp_path):
    import sys
    from qwenpaw.plugins.architecture import PluginManifest
    from qwenpaw.plugins.channel_adapter import describe_channel
    from qwenpaw.runtime.runtime import Runtime
    from extension_sample import ROOT

    source = endpoint_source(tmp_path / "incoming", "external_endpoint")
    descriptor_path = source / "channel.json"
    descriptor = json.loads(descriptor_path.read_text())
    # An open client schema still cannot grant ownership/control of a launch.
    descriptor["config_schema"]["additionalProperties"] = True
    descriptor_path.write_text(json.dumps(descriptor))
    manifest = PluginManifest.from_dict(
        json.loads((source / "plugin.json").read_text())
    )
    description = describe_channel(source, manifest)
    workspace = tmp_path / "host" / ".." / "trusted-workspace"
    proxy = description.create_proxy(
        Runtime.run,
        {
            "enabled": False,
            "plugin_id": "forged-plugin",
            "workspace_id": "forged-workspace",
            "ordinary_extra": "retained",
        },
        python_executable=sys.executable,
        support_root=ROOT / "src",
        instance_id="trusted-instance",
        generation=1,
        qwenpaw_version="2.2.2b4",
        workspace_dir=workspace,
    )
    spec = proxy._launch_spec
    assert spec.plugin_id == description.plugin_id == "external_endpoint"
    assert spec.workspace_id == str(workspace.resolve())
    assert "plugin_id" not in spec.config and "workspace_id" not in spec.config
    assert spec.config["ordinary_extra"] == "retained"
    assert proxy.endpoint_service.plugin_id == spec.plugin_id
    assert proxy.endpoint_service.workspace_id == spec.workspace_id
    assert proxy.channel_process.health_snapshot()["pid"] is None
