# -*- coding: utf-8 -*-
"""Host-independent Driver values and real lifecycle registration ownership."""

import asyncio
import importlib
import inspect
import json
import subprocess
import sys
from dataclasses import FrozenInstanceError
from pathlib import Path
from types import MappingProxyType

import pytest

from .sdk_author_fixture import make_plugin

DRIVER_TYPES = (
    "DriverSource",
    "DriverCapabilitySpec",
    "DriverCallResult",
    "DriverRequestContext",
    "DriverCredential",
    "DriverCredentialAccess",
    "DriverContext",
    "DriverConnection",
    "DriverProtocolSpec",
)
EMPTY_PLUGIN = """
class Plugin:
    def register(self, ctx):
        pass
plugin = Plugin()
"""


def driver_plugin(tmp_path, plugin_id, source=EMPTY_PLUGIN, *, version="1.1"):
    parent = tmp_path / plugin_id
    parent.mkdir()
    root = make_plugin(parent, source, ["drivers"])
    manifest = root / "plugin.json"
    data = json.loads(manifest.read_text())
    data["id"] = plugin_id
    data["sdk"]["version"] = version
    manifest.write_text(json.dumps(data))
    return root


def protocol_spec(protocol="contract", calls=None):
    from qwenpaw.plugins.drivers import DriverProtocolSpec

    def validate(source):
        if calls is not None:
            calls.append(("validate", source))

    def create(context, source):
        raise AssertionError("Registration must not create a connection")

    return DriverProtocolSpec(
        protocol=protocol,
        validate=validate,
        create=create,
    )


def test_driver_public_imports_and_versioned_exports(tmp_path):
    from qwenpaw.plugins import SDK_CAPABILITIES, SDK_VERSION
    from qwenpaw.plugins.compliance import (
        API_EXPORTS,
        PUBLIC_API,
        check_plugin,
    )

    module = importlib.import_module("qwenpaw.plugins.drivers")
    assert all(getattr(module, name) is not None for name in DRIVER_TYPES)
    assert SDK_VERSION == "1.1.0"
    assert "drivers" in SDK_CAPABILITIES
    assert set(DRIVER_TYPES) <= set(PUBLIC_API[module.__name__])
    exports = {(row.module, row.symbol): row for row in API_EXPORTS}
    for name in DRIVER_TYPES:
        assert exports[(module.__name__, name)].since == "1.1.0"
    assert exports[("qwenpaw.plugins.tools", "ToolSpec")].since == "1.0.0"
    source = (
        "from qwenpaw.plugins.drivers import (" + ",".join(DRIVER_TYPES) + ")"
    )
    report = check_plugin(driver_plugin(tmp_path, "public-driver", source))
    assert report.ok, report.findings


def test_driver_defaults_and_public_schema_values():
    from qwenpaw.plugins.drivers import (
        DriverCallResult,
        DriverCapabilitySpec,
        DriverSource,
    )

    source = DriverSource(source_id="source", protocol="contract", endpoint={})
    assert source.enabled is True and source.config == {}
    capability = DriverCapabilitySpec(
        name="echo",
        description="Echo",
        input_schema={"type": "object"},
    )
    assert capability.output_schema is None
    assert capability.tool_name == "" and capability.enabled is True
    assert capability.metadata == {}
    result = DriverCallResult()
    assert isinstance(result.content, tuple) and not result.content
    assert result.is_error is False
    assert result.structured_content is None and result.metadata == {}
    assert (
        DriverCapabilitySpec(
            name="boolean",
            description="Boolean schema",
            input_schema=True,
            output_schema=False,
        ).input_schema
        is True
    )


def assert_frozen_tree(snapshot):
    assert isinstance(snapshot, MappingProxyType)
    assert isinstance(snapshot["nested"], tuple)
    assert isinstance(snapshot["nested"][0], MappingProxyType)
    assert snapshot["nested"][0]["values"] == ("original",)
    with pytest.raises(TypeError):
        snapshot["new"] = True
    with pytest.raises(TypeError):
        snapshot["nested"][0]["values"][0] = "changed"


def test_driver_snapshots_are_deeply_readonly_without_nested_aliases():
    from qwenpaw.plugins.drivers import (
        DriverCallResult,
        DriverCapabilitySpec,
        DriverCredential,
        DriverSource,
    )

    original = {"nested": [{"values": ["original"]}]}
    schema = {"type": "object", "properties": {"names": {"enum": ["old"]}}}
    source = DriverSource(
        source_id="source",
        protocol="contract",
        endpoint=original,
        config=original,
    )
    capability = DriverCapabilitySpec(
        name="echo",
        description="Echo",
        input_schema=schema,
        output_schema=schema,
        metadata=original,
    )
    result = DriverCallResult(structured_content=original, metadata=original)
    credential = DriverCredential(
        kind="oauth",
        revision=3,
        public=original,
        secrets=original,
    )
    original["nested"][0]["values"].append("external mutation")
    schema["properties"]["names"]["enum"].append("external mutation")
    for snapshot in (
        source.endpoint,
        source.config,
        capability.metadata,
        result.structured_content,
        result.metadata,
        credential.public,
        credential.secrets,
    ):
        assert_frozen_tree(snapshot)
    for snapshot in (capability.input_schema, capability.output_schema):
        assert snapshot["properties"]["names"]["enum"] == ("old",)
        with pytest.raises(TypeError):
            snapshot["properties"]["names"]["enum"] = ()
    for value, field in (
        (source, "source_id"),
        (capability, "name"),
        (result, "is_error"),
        (credential, "revision"),
    ):
        with pytest.raises(FrozenInstanceError):
            setattr(value, field, None)
    secret = DriverCredential(
        kind="token",
        revision=1,
        public={},
        secrets={"access_token": "driver-secret-test-marker"},
    )
    assert "driver-secret-test-marker" not in repr(secret)


def test_driver_result_copies_nested_content_blocks_and_output():
    from qwenpaw.plugins.drivers import DriverCallResult
    from qwenpaw.plugins.messages import ContentBlock

    metadata = {"nested": [{"values": ["original"]}]}
    leaf = ContentBlock(text="leaf", metadata=metadata, attributes=metadata)
    outer = ContentBlock(
        type="tool_result",
        output=(leaf,),
        metadata=metadata,
        attributes=metadata,
    )
    content = [outer]
    result = DriverCallResult(content=content)
    metadata["nested"][0]["values"].append("external mutation")
    content.clear()
    assert isinstance(result.content, tuple) and len(result.content) == 1
    copied = result.content[0]
    assert isinstance(copied, ContentBlock) and copied is not outer
    assert isinstance(copied.output, tuple)
    assert copied.output[0] is not leaf and copied.output[0].text == "leaf"
    for block in (copied, copied.output[0]):
        assert_frozen_tree(block.metadata)
        assert_frozen_tree(block.attributes)


@pytest.mark.parametrize(
    "target",
    [
        "endpoint",
        "config",
        "capability_metadata",
        "structured_content",
        "result_metadata",
        "public",
        "secrets",
        "content_metadata",
        "content_attributes",
    ],
)
@pytest.mark.parametrize(
    "invalid",
    [
        object(),
        Path("host-only"),
        {1: "non-string"},
        float("nan"),
        float("inf"),
        float("-inf"),
    ],
)
def test_driver_json_rejects_host_objects_keys_and_nonfinite_values(
    target,
    invalid,
):
    from qwenpaw.plugins import SDKError
    from qwenpaw.plugins.drivers import (
        DriverCallResult,
        DriverCapabilitySpec,
        DriverCredential,
        DriverSource,
    )
    from qwenpaw.plugins.messages import ContentBlock

    value = {"nested": [invalid]}
    with pytest.raises((TypeError, ValueError, SDKError)):
        if target in {"endpoint", "config"}:
            DriverSource(
                source_id="source",
                protocol="contract",
                **{"endpoint": {}, target: value},
            )
        elif target == "capability_metadata":
            DriverCapabilitySpec(
                name="echo",
                description="Echo",
                input_schema={},
                metadata=value,
            )
        elif target in {"structured_content", "result_metadata"}:
            field = "metadata" if target == "result_metadata" else target
            DriverCallResult(**{field: value})
        elif target in {"public", "secrets"}:
            DriverCredential(
                kind="token",
                revision=1,
                **{"public": {}, "secrets": {}, target: value},
            )
        else:
            field = target.removeprefix("content_")
            DriverCallResult(content=(ContentBlock(**{field: value}),))


@pytest.mark.parametrize("field", ["input_schema", "output_schema"])
@pytest.mark.parametrize(
    "invalid",
    [
        [],
        {"type": "not-a-json-schema-type"},
        {"type": 42},
        {"required": "name"},
        {"properties": {"nested": {"type": "not-a-json-schema-type"}}},
        {"enum": [float("nan")]},
        {1: {"type": "string"}},
        {"default": object()},
    ],
)
def test_driver_capability_rejects_malformed_json_schema(field, invalid):
    from qwenpaw.plugins import SDKError
    from qwenpaw.plugins.drivers import DriverCapabilitySpec

    with pytest.raises((TypeError, ValueError, SDKError)):
        DriverCapabilitySpec(
            name="echo",
            description="Echo",
            **{"input_schema": {}, field: invalid},
        )


def test_driver_request_identity_and_cancellation_are_immutable():
    from qwenpaw.plugins.drivers import DriverRequestContext

    identity = {
        "workspace_id": "workspace",
        "workspace_instance_id": "instance",
        "session_id": "session",
        "user_id": "user",
        "channel": "web",
    }
    request = DriverRequestContext(**identity)
    assert request.deadline is None and request.cancelled is False
    request.check_cancelled()
    for field, expected in identity.items():
        assert getattr(request, field) == expected
        with pytest.raises(FrozenInstanceError):
            setattr(request, field, "forged")
    cancelled = False
    request = DriverRequestContext(
        **identity,
        deadline=123.0,
        _is_cancelled=lambda: cancelled,
    )
    assert request.deadline == 123.0 and request.cancelled is False
    cancelled = True
    assert request.cancelled is True
    with pytest.raises(asyncio.CancelledError):
        request.check_cancelled()
    assert not hasattr(request, "approval_result")


def test_driver_app_management_scope_has_explicit_public_signature():
    from qwenpaw.plugins.apps import AppContext

    signature = inspect.signature(AppContext.driver_source)
    assert tuple(signature.parameters) == ("self", "protocol", "source_id")


async def test_driver_context_identity_and_source_snapshot_are_frozen(
    tmp_path,
):
    from qwenpaw.plugins.drivers import (
        DriverContext,
        DriverCredential,
        DriverSource,
    )
    from qwenpaw.plugins.testing import PluginTestHost

    class Credentials:
        async def resolve(self, alias):
            del alias
            return DriverCredential(
                kind="token",
                revision=1,
                public={},
                secrets={},
            )

        async def update(self, alias, *, expected_revision, public, secrets):
            raise AssertionError(
                "Constructing a context must not write credentials",
            )

    endpoint = {"nested": [{"values": ["original"]}]}
    source = DriverSource(
        source_id="source",
        protocol="contract",
        endpoint=endpoint,
        enabled=False,
    )
    async with PluginTestHost(tmp_path / "host") as host:
        plugin = await host.load(driver_plugin(tmp_path, "driver-context"))
        context = DriverContext(
            plugin_id=plugin.plugin_id,
            generation=plugin.generation,
            workspace_id="workspace",
            workspace_instance_id="instance",
            source_id="source",
            source_revision=7,
            source=source,
            resources=plugin.resources,
            logger=plugin.logger,
            credentials=Credentials(),
        )
        endpoint["nested"][0]["values"].append("external mutation")
        assert_frozen_tree(context.source.endpoint)
        assert context.source.enabled is False
        assert context.session_scope == ""
        assert context.source_revision == 7
        for field in (
            "plugin_id",
            "generation",
            "workspace_id",
            "workspace_instance_id",
            "source_id",
            "source_revision",
            "source",
            "session_scope",
        ):
            with pytest.raises(FrozenInstanceError):
                setattr(context, field, "forged")
        assert callable(context.invalidate_capabilities)


async def test_driver_registration_duplicate_conflict_and_exact_owned_release(
    tmp_path,
):
    from qwenpaw.plugins import SDKError, StaleContextError
    from qwenpaw.plugins.resources import Registration
    from qwenpaw.plugins.testing import PluginTestHost

    calls = []
    spec = protocol_spec(calls=calls)
    async with PluginTestHost(tmp_path / "host") as host:
        first = await host.load(driver_plugin(tmp_path, "driver-first"))
        second = await host.load(driver_plugin(tmp_path, "driver-second"))
        registration = first.register_driver_protocol(spec)
        assert isinstance(registration, Registration)
        assert registration.owner.plugin_id == first.plugin_id
        assert registration.owner.generation == first.generation
        with pytest.raises(SDKError):
            first.register_driver_protocol(spec)
        with pytest.raises(SDKError):
            second.register_driver_protocol(spec)
        assert not calls, "Registration must not validate or connect sources"
        await registration.close()
        assert registration.closed
        replacement = second.register_driver_protocol(spec)
        await registration.close()
        assert (await host.unload(first.plugin_id)).quiescent
        with pytest.raises(StaleContextError):
            first.register_driver_protocol(protocol_spec("stale"))
        third = await host.load(driver_plugin(tmp_path, "driver-third"))
        with pytest.raises(SDKError):
            third.register_driver_protocol(spec)
        await replacement.close()
        assert (await host.unload(second.plugin_id)).quiescent
        assert isinstance(third.register_driver_protocol(spec), Registration)
        assert not calls


async def test_driver_registration_from_register_releases_on_reload_and_unload(
    tmp_path,
):
    from qwenpaw.plugins import SDKError
    from qwenpaw.plugins.testing import PluginTestHost

    source = """
from qwenpaw.plugins.drivers import DriverProtocolSpec
class Plugin:
    def register(self, ctx):
        def unexpected(*args):
            raise AssertionError("registration invoked a source callback")
        ctx.register_driver_protocol(DriverProtocolSpec(
            protocol="contract", validate=unexpected, create=unexpected))
plugin = Plugin()
"""
    async with PluginTestHost(tmp_path / "host") as host:
        await host.load(driver_plugin(tmp_path, "driver-owner", source))
        assert (await host.reload("driver-owner")).ok
        other = await host.load(driver_plugin(tmp_path, "driver-other"))
        with pytest.raises(SDKError):
            other.register_driver_protocol(protocol_spec())
        assert (await host.unload("driver-owner")).quiescent
        registration = other.register_driver_protocol(protocol_spec())
        assert not registration.closed
        assert (await host.unload("driver-other")).quiescent
        final = await host.load(driver_plugin(tmp_path, "driver-final"))
        final.register_driver_protocol(protocol_spec())


async def test_sdk_1_0_plugin_still_loads_and_executes_after_driver_extension(
    tmp_path,
):
    from qwenpaw.plugins.testing import PluginTestHost

    source = """
from qwenpaw.plugins.tools import ToolSpec, ToolResult
class Plugin:
    def register(self, ctx):
        async def echo(call, arguments):
            return ToolResult.text("sdk-1.0-still-works")
        ctx.register_tool(ToolSpec("legacy_echo", "Echo", {}, echo))
plugin = Plugin()
"""
    root = make_plugin(tmp_path, source, ["tools"])
    async with PluginTestHost(tmp_path / "host") as host:
        await host.load(root)
        result = await host.call_tool("legacy_echo", {})
        assert result.content[0].text == "sdk-1.0-still-works"
        assert (await host.reload("extension-contract")).ok


@pytest.mark.parametrize(
    "code",
    [
        "from qwenpaw.drivers.manager import DriverManager",
        "from qwenpaw.drivers.registry import DriverRegistry",
        "from qwenpaw.app.driver_manager import DriverManager",
        "from qwenpaw.plugins import PluginRegistry",
    ],
)
def test_driver_plugin_rejects_internal_imports(tmp_path, code):
    from qwenpaw.plugins.compliance import check_plugin

    report = check_plugin(driver_plugin(tmp_path, "qwenpaw-mcp", code))
    assert not report.ok
    assert any(row.code.startswith("private-") for row in report.findings)


def test_driver_public_import_does_not_load_own_mcp_runtime():
    code = """
import importlib
import json
import sys
import qwenpaw.plugins
before = set(sys.modules)
module = importlib.import_module("qwenpaw.plugins.drivers")
assert module.DriverProtocolSpec is not None
forbidden = sorted(name for name in sys.modules if (
    name == "qwenpaw.drivers" or name.startswith("qwenpaw.drivers.")
    or name.startswith("qwenpaw.plugins._drivers")
    or (name not in before and (
        name == "qwenpaw.app" or name.startswith("qwenpaw.app.")
        or name == "qwenpaw.agents" or name.startswith("qwenpaw.agents.")
    ))
))
print(json.dumps(forbidden))
"""
    result = subprocess.run(
        [sys.executable, "-B", "-c", code],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == []
