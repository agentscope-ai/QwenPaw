"""G4-A1 endpoint registration through the normal shared child and host."""

import json
import os

import pytest

from extension_sample import sample_source

pytest_plugins = ["extension_process_suite"]


def endpoint_source(directory, key, *, capabilities=None):
    """Expose a test trigger using the production endpoint DTO in the child."""
    source = sample_source(directory, key, capabilities=capabilities)
    descriptor_path = source / "channel.json"
    descriptor = json.loads(descriptor_path.read_text())
    descriptor["capabilities"] = sorted(
        {*descriptor["capabilities"], "ingress_endpoint"}
    )
    descriptor_path.write_text(json.dumps(descriptor))
    path = source / key / "driver.py"
    body = path.read_text()
    needle = '("fixture.fault", self.set_fault),'
    assert body.count(needle) == 1
    body = body.replace(
        needle, needle + '\n            ("fixture.endpoint", self.endpoint),'
    )
    body += """

    async def endpoint(self, params, _request):
        from qwenpaw.channel_protocol.models import EndpointParams

        endpoint = EndpointParams.from_mapping({
            **self._context.identity.to_mapping(), **params["endpoint"],
        })
        result = await self._context.peer.call(
            "ingress.endpoint.register", endpoint.to_mapping(),
        )
        return {"pid": os.getpid(), "endpoint": endpoint.to_mapping(),
                "registration": result}
"""
    path.write_text(body)
    return source


@pytest.mark.asyncio
async def test_shared_child_registers_endpoint_with_current_host(runtime):
    rt = await runtime(source_factory=endpoint_source)
    health = rt.process.health_snapshot()
    assert health["state"] == "ready"
    assert health["platform_state"] == "connected"
    assert health["pid"] != os.getpid()
    assert rt.process.observed_hello is not None
    assert "ingress_endpoint" in rt.channel.descriptor.capabilities
    result = await rt.process.call(
        "fixture.endpoint",
        {
            "endpoint": {
                "protocol": "ws",
                "host": "127.0.0.1",
                "port": 18777,
                "path": "/ws",
                "public_base_url": None,
                "readiness": "ready",
                "bound_externally": False,
                "auth_required": True,
                "quiescing": False,
            }
        },
    )
    assert result["pid"] == health["pid"]
    assert result["endpoint"]["generation"] == health["generation"]
    registration = result["registration"]
    # Existing CoreLifecycleAdapter wire semantics; A3 forwarding is optional.
    assert {
        key: registration[key] for key in ("status", "generation", "readiness")
    } == {
        "status": "registered",
        "generation": health["generation"],
        "readiness": "ready",
    }
    assert registration.get("forwarding") is None
