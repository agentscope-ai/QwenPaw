# -*- coding: utf-8 -*-
"""External protocol author contracts through the real test host."""

# Test-only service-state observation proves management stays lazy.
# pylint: disable=protected-access

import asyncio
import json
from contextlib import suppress

import pytest
import yaml

from qwenpaw.plugins import PluginBusyError, SDKError
from qwenpaw.plugins.drivers import (
    DriverCallResult,
    DriverCredentialAccess,
    DriverContext,
)
from qwenpaw.plugins.testing import PluginTestHost

from .sdk_author_fixture import make_plugin

PLUGIN_ID = "driver-lifecycle"
PROTOCOL = "author-driver"
SOURCE = """
import asyncio
import threading
from pathlib import Path
from qwenpaw.plugins import SDKError
from qwenpaw.plugins.apps import PawApp, HttpResponse
from qwenpaw.plugins.drivers import (
    DriverProtocolSpec, DriverCapabilitySpec, DriverCallResult,
)
from qwenpaw.plugins.messages import Attachment, ContentBlock

class Plugin:
    def register(self, plugin):
        directory = Path(plugin.config.get("directory"))
        record_lock = threading.Lock()
        def record(event, context):
            # Resource callbacks may run concurrently in cleanup threads.
            with record_lock:
                rows = plugin.storage.read_json("events.json", [])
                rows.append([event, context.workspace_id, context.source_id,
                             context.source_revision, context.generation])
                plugin.storage.write_json("events.json", rows)
        async def wait(name):
            while not (directory / name).exists():
                await asyncio.sleep(.005)
        class Connection:
            def __init__(self, context, source):
                self.context, self.source = context, source
                record("create", context)
            async def open(self):
                record("open", self.context)
                self.context.resources.defer(
                    lambda: record("resource-close", self.context))
                if self.source.config.get("wait_open"):
                    await wait("release-open")
                if self.source.config.get("fail_open"):
                    raise SDKError("synthetic preparation failure")
                record("opened", self.context)
            async def discover(self, request):
                record("discover", self.context)
                if self.source.config.get("wait_discover"):
                    await wait("release-discover")
                return (
                    DriverCapabilitySpec("echo", "Echo", {"type":"object"}),
                    DriverCapabilitySpec("blocked", "Disabled", True,
                                         enabled=False),
                    DriverCapabilitySpec("impossible", "False schema", False),
                )
            async def invoke(self, name, arguments, request):
                record("invoke", self.context)
                if arguments.get("wait"):
                    await wait("release-call")
                credential = None
                if "alias" in arguments:
                    value = await self.context.credentials.resolve(
                        arguments["alias"])
                    credential = {"kind": value.kind,
                                  "revision": value.revision,
                                  "public": dict(value.public),
                                  "secrets": dict(value.secrets)}
                return DriverCallResult(
                    content=(ContentBlock(text="echo:" + name),
                             ContentBlock(type="image", attachment=Attachment(
                                 url="https://example.invalid/picture.png",
                                 mime_type="image/png", name="picture"))),
                    structured_content={
                        "workspace": request.workspace_id,
                        "instance": request.workspace_instance_id,
                        "session": request.session_id,
                        "user": request.user_id, "channel": request.channel,
                        "source": self.source.source_id,
                        "label": self.source.config.get("label", ""),
                        "arguments": dict(arguments), "credential": credential,
                    },
                    is_error=bool(arguments.get("error")),
                    metadata={"protocol": "public-sdk"},
                )
            async def close(self):
                record("close-attempt", self.context)
                if (self.source.config.get("fail_close")
                        and not (directory / "allow-close").exists()):
                    raise SDKError("synthetic close failure")
                record("closed", self.context)
        def validate(source):
            if source.endpoint.get("invalid"):
                raise SDKError("synthetic invalid endpoint")
        plugin.register_driver_protocol(DriverProtocolSpec(
            "author-driver", validate, Connection))
        app = PawApp("Driver management", app_id="driver-manage")
        saved = {}
        saved_drivers = {}
        @app.route("/source", methods=("POST",))
        async def source(ctx, request):
            data = request.json()
            try:
                async with ctx.driver_source(
                    data.get("protocol", "author-driver"),
                    data["source"],
                ) as driver:
                    if data.get("save"):
                        saved[data["save"]] = driver.credentials
                        saved_drivers[data["save"]] = driver
                    if data.get("action") == "update":
                        await driver.credentials.update(
                            data["alias"],
                            expected_revision=data["revision"],
                            public=data.get("public", {}),
                            secrets=data.get("secrets", {}),
                        )
                    result = {"enabled": driver.source.enabled,
                              "workspace": driver.workspace_id,
                              "instance": driver.workspace_instance_id,
                              "generation": driver.generation,
                              "source_revision": driver.source_revision,
                              "aliases": list(driver.credentials.aliases)}
                    if data.get("environment"):
                        environment = await driver.subprocess_environment()
                        readonly = False
                        try:
                            environment["SYNTHETIC_MUTATION"] = "forbidden"
                        except TypeError:
                            readonly = True
                        configured = environment.get("DRIVER_CONFIGURED_TEST")
                        result["environment"] = {
                            "configured": configured == "configured-value",
                            "host_secret_absent": "DRIVER_HOST_ONLY_TEST"
                                not in environment,
                            "readonly": readonly,
                            "only_configured": set(environment)
                                == {"DRIVER_CONFIGURED_TEST"},
                        }
                    if "alias" in data:
                        credential = await driver.credentials.resolve(
                            data["alias"])
                        result["credential"] = {
                            "kind": credential.kind,
                            "revision": credential.revision,
                            "public": dict(credential.public),
                            "secrets": dict(credential.secrets),
                        }
                    return result
            except SDKError as exc:
                return HttpResponse({"error": str(exc)}, status=403)
        @app.route("/saved", methods=("POST",))
        async def stale(ctx, request):
            try:
                data = request.json()
                if data.get("action") == "environment":
                    await saved_drivers[data["key"]].subprocess_environment()
                    return {"accepted": True}
                credentials = saved[data["key"]]
                if data.get("action") == "aliases":
                    return {"aliases": list(credentials.aliases)}
                await credentials.resolve("oauth")
                return {"accepted": True}
            except SDKError as exc:
                return HttpResponse({"error": str(exc)}, status=403)
        plugin.register_app(app)
plugin = Plugin()
"""


def driver_plugin(tmp_path):
    root = make_plugin(tmp_path, SOURCE, ["drivers", "apps", "storage"])
    manifest = root / "plugin.json"
    data = json.loads(manifest.read_text())
    data["id"] = PLUGIN_ID
    data["sdk"]["version"] = "1.1"
    manifest.write_text(json.dumps(data))
    return root


def card(name="same", *, effect="allow", **kwargs):
    return {
        "name": name,
        "protocol": PROTOCOL,
        "endpoint": {},
        "policy": {"default_effect": effect},
        **kwargs,
    }


def seed_card(host_root, workspace, source):
    path = (
        host_root
        / "workspaces"
        / workspace
        / "drivers"
        / source["protocol"]
        / f'{source["name"]}.yaml'
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(source))
    return path


def events(context, event):
    return [
        row
        for row in context.storage.read_json("events.json", [])
        if row[0] == event
    ]


async def wait_until(predicate):
    async with asyncio.timeout(3):
        while not predicate():
            await asyncio.sleep(0.005)


async def management(host, source="same", *, workspace="test", **data):
    return await host.request(
        "POST",
        "/api/driver-manage/source",
        workspace_id=workspace,
        user_id="alice",
        json={"source": source, **data},
    )


async def seed_credentials(host_root, workspace="test"):
    # Test setup may use the local encrypted store; the plugin cannot.
    from qwenpaw.drivers.credentials.store import AsyncCredentialStore
    from qwenpaw.drivers.credentials.types import CredentialRecord

    path = host_root / "workspaces" / workspace / "credentials.yaml"
    store = AsyncCredentialStore(path)
    for ref, secret in (
        ("synthetic-oauth", "synthetic-access-original"),
        ("synthetic-foreign", "synthetic-foreign-secret"),
        ("synthetic-historical", "synthetic-historical-secret"),
    ):
        await store.put(
            CredentialRecord(
                ref=ref,
                kind="oauth",
                public={"issuer": "example.invalid"},
                secrets={"access_token": secret},
                meta={"historical": ref == "synthetic-historical"},
            ),
        )
    return store, path


async def test_discovery_call_identity_and_public_result_round_trip(tmp_path):
    async with PluginTestHost(tmp_path / "host") as host:
        context = await host.load(
            driver_plugin(tmp_path),
            config={"directory": str(tmp_path)},
        )
        assert not events(context, "create")
        await host.open_driver(card())
        capabilities = await host.list_driver_capabilities("same")
        echo = next(row for row in capabilities if row["name"] == "echo")
        assert echo["capability_id"] == (
            "driver://author-driver/same/tools/echo#invoke"
        )
        assert echo["protocol"] == PROTOCOL
        assert echo["driver_name"] == "same"
        assert echo["input_schema"] == {"type": "object"}
        with pytest.raises(TypeError):
            echo["input_schema"]["type"] = "string"
        impossible = next(
            row for row in capabilities if row["name"] == "impossible"
        )
        assert impossible["input_schema"] is False
        for error in (False, True):
            result = await host.call_driver(
                "same",
                "echo",
                {"value": 42, "error": error},
                session_id="real-session",
                user_id="alice",
                channel="web",
            )
            assert isinstance(result, DriverCallResult)
            assert result.is_error is error
            assert result.content[0].text == "echo:echo"
            assert result.content[1].attachment.mime_type == "image/png"
            assert result.metadata == {"protocol": "public-sdk"}
            data = result.structured_content
            assert data["workspace"] == "test" and data["instance"]
            assert data["session"] == "real-session"
            assert data["user"] == "alice" and data["channel"] == "web"
        before = len(events(context, "invoke"))
        for name in ("blocked", "impossible", "missing"):
            with pytest.raises(SDKError):
                await host.call_driver("same", name, {})
        assert len(events(context, "invoke")) == before
        await host.close_driver("same")
        assert len(events(context, "closed")) == 1
        assert len(events(context, "resource-close")) == 1


async def test_denied_policy_never_enters_plugin_invoke(tmp_path):
    async with PluginTestHost(tmp_path / "host") as host:
        context = await host.load(
            driver_plugin(tmp_path),
            config={"directory": str(tmp_path)},
        )
        await host.open_driver(card(effect="deny"))
        with pytest.raises(SDKError, match="(?i)denied|permission|policy"):
            await host.call_driver("same", "echo", {})
        assert not events(context, "invoke")


@pytest.mark.parametrize("approved", [False, True])
async def test_ask_uses_host_approval_before_plugin_invoke(tmp_path, approved):
    async with PluginTestHost(tmp_path / "host") as host:
        context = await host.load(
            driver_plugin(tmp_path),
            config={"directory": str(tmp_path)},
        )
        await host.open_driver(card(effect="ask"))
        pending = asyncio.create_task(
            host.call_driver(
                "same",
                "echo",
                {},
                session_id="driver-approval",
                user_id="alice",
                channel="web",
            ),
        )
        try:
            async with asyncio.timeout(3):
                while not (
                    requests := await host.approval_requests(
                        "driver-approval",
                    )
                ):
                    await asyncio.sleep(0.005)
            assert len(requests) == 1 and not pending.done()
            assert requests[0].workspace_id == "test"
            assert not events(context, "invoke")
            assert await host.resolve_approval(
                requests[0].request_id,
                approved=approved,
            )
            if approved:
                assert isinstance(await pending, DriverCallResult)
                assert len(events(context, "invoke")) == 1
            else:
                with pytest.raises(SDKError):
                    await pending
                assert not events(context, "invoke")
        finally:
            if not pending.done():
                pending.cancel()
                with suppress(asyncio.CancelledError):
                    await pending


async def test_same_source_ids_are_isolated_by_workspace(tmp_path):
    async with PluginTestHost(tmp_path / "host") as host:
        context = await host.load(
            driver_plugin(tmp_path),
            config={"directory": str(tmp_path)},
        )
        for workspace in ("one", "two"):
            await host.open_driver(
                card(config={"label": workspace}),
                workspace_id=workspace,
            )
        results = [
            await host.call_driver("same", "echo", {}, workspace_id=workspace)
            for workspace in ("one", "two")
        ]
        assert [r.structured_content["label"] for r in results] == [
            "one",
            "two",
        ]
        assert len({r.structured_content["instance"] for r in results}) == 2
        await host.close_driver("same", workspace_id="one")
        assert [row[1] for row in events(context, "closed")] == ["one"]
        assert (
            await host.call_driver(
                "same",
                "echo",
                {},
                workspace_id="two",
            )
        ).structured_content["label"] == "two"


async def test_disabled_management_uses_no_manager_or_connection(tmp_path):
    root = tmp_path / "host"
    seed_card(root, "test", card(enabled=False))
    async with PluginTestHost(root) as host:
        context = await host.load(
            driver_plugin(tmp_path),
            config={"directory": str(tmp_path)},
        )
        response = await management(host)
        assert response.status == 200, response.text
        assert response.json()["enabled"] is False
        assert not events(context, "create")
        # Service state is a test-only observation, never a plugin import.
        assert all(
            "driver_manager" not in workspace._service_manager.services
            for workspace in host._workspaces.values()
        )


async def test_management_rejects_foreign_protocol_and_transient_source(
    tmp_path,
):
    root = tmp_path / "host"
    seed_card(root, "test", card("foreign", protocol="foreign-protocol"))
    async with PluginTestHost(root) as host:
        await host.load(
            driver_plugin(tmp_path),
            config={"directory": str(tmp_path)},
        )
        await host.open_driver(card("ephemeral"), session_scope="session-a")
        for source, protocol in (
            ("foreign", "foreign-protocol"),
            ("ephemeral", PROTOCOL),
        ):
            denied = await management(host, source, protocol=protocol)
            assert denied.status == 403, denied.text
        with pytest.raises(SDKError):
            await host.call_driver(
                "ephemeral",
                "echo",
                {},
                session_scope="session-b",
            )
        assert (
            await host.call_driver(
                "ephemeral",
                "echo",
                {},
                session_scope="session-a",
            )
        ).structured_content["source"] == "ephemeral"
        assert not list(
            (root / "workspaces" / "test" / "drivers").rglob(
                "ephemeral.yaml",
            ),
        )


async def test_credentials_declared_aliases_atomic_update_and_encryption(
    tmp_path,
):
    root = tmp_path / "host"
    async with PluginTestHost(root) as host:
        await host.load(
            driver_plugin(tmp_path),
            config={"directory": str(tmp_path)},
        )
        store, path = await seed_credentials(root)
        seed_card(
            root,
            "test",
            card(
                enabled=False,
                credentials={
                    "oauth": {"kind": "oauth", "ref": "synthetic-oauth"},
                },
            ),
        )
        first = await management(host, alias="oauth")
        assert first.status == 200, first.text
        assert first.json()["aliases"] == ["oauth"]
        credential = first.json()["credential"]
        assert credential["secrets"] == {
            "access_token": "synthetic-access-original",
        }
        for alias in ("synthetic-oauth", "synthetic-foreign", "../secrets"):
            denied = await management(host, alias=alias)
            assert denied.status == 403, denied.text
        updates = await asyncio.gather(
            *(
                management(
                    host,
                    action="update",
                    alias="oauth",
                    revision=credential["revision"],
                    public={"writer": writer},
                    secrets={"access_token": f"synthetic-new-{writer}"},
                )
                for writer in ("a", "b")
            ),
        )
        assert sorted(row.status for row in updates) == [200, 403]
        current = (await management(host, alias="oauth")).json()["credential"]
        assert current["revision"] != credential["revision"]
        assert (await store.get("synthetic-historical")).meta == {
            "historical": True,
        }
        persisted = path.read_text()
        assert "synthetic-access-original" not in persisted
        assert "synthetic-new-a" not in persisted
        assert "synthetic-new-b" not in persisted
        assert "synthetic-historical-secret" not in persisted
        # Existing writers must invalidate the SDK's optimistic revision.
        from qwenpaw.drivers.credentials.types import CredentialRecord

        await store.put(
            CredentialRecord(
                ref="synthetic-oauth",
                kind="oauth",
                secrets={"access_token": "synthetic-legacy-writer"},
            ),
        )
        stale = await management(
            host,
            action="update",
            alias="oauth",
            revision=current["revision"],
            secrets={"access_token": "synthetic-stale-overwrite"},
        )
        assert stale.status == 403, stale.text
        assert (await store.get("synthetic-oauth")).secrets == {
            "access_token": "synthetic-legacy-writer",
        }


@pytest.mark.parametrize(
    "action",
    ["resolve", "aliases", "environment"],
)
async def test_management_credentials_revoke_when_scope_exits(
    tmp_path,
    action,
):
    root = tmp_path / "host"
    async with PluginTestHost(root) as host:
        await host.load(
            driver_plugin(tmp_path),
            config={"directory": str(tmp_path)},
        )
        await seed_credentials(root)
        seed_card(
            root,
            "test",
            card(
                enabled=False,
                credentials={
                    "oauth": {"kind": "oauth", "ref": "synthetic-oauth"},
                },
            ),
        )
        assert (
            await management(host, save="old", alias="oauth")
        ).status == 200
        stale = await host.request(
            "POST",
            "/api/driver-manage/saved",
            user_id="alice",
            json={"key": "old", "action": action},
        )
        assert stale.status == 403, stale.text


async def test_driver_calls_block_plugin_reload(tmp_path):
    async with PluginTestHost(tmp_path / "host") as host:
        context = await host.load(
            driver_plugin(tmp_path),
            config={"directory": str(tmp_path)},
        )
        await host.open_driver(card())
        pending = asyncio.create_task(
            host.call_driver(
                "same",
                "echo",
                {"wait": True},
            ),
        )
        try:
            await wait_until(lambda: events(context, "invoke"))
            with pytest.raises(PluginBusyError):
                await host.reload(PLUGIN_ID)
            assert not pending.done()
        finally:
            (tmp_path / "release-call").touch()
            await pending
        assert (await host.reload(PLUGIN_ID)).ok
        assert len(events(host.context(PLUGIN_ID), "closed")) == 1


async def test_partial_open_cancel_closes_every_created_connection(tmp_path):
    async with PluginTestHost(tmp_path / "host") as host:
        context = await host.load(
            driver_plugin(tmp_path),
            config={"directory": str(tmp_path)},
        )
        pending = asyncio.create_task(
            host.open_driver(
                card(config={"wait_open": True}),
            ),
        )
        await wait_until(lambda: events(context, "open"))
        pending.cancel()
        with pytest.raises(asyncio.CancelledError):
            await pending
        assert len(events(context, "closed")) == 1
        assert len(events(context, "resource-close")) == 1
        await host.close_driver("same")
        assert len(events(context, "closed")) == 1


async def test_failed_close_retains_owner_and_blocks_replacement(tmp_path):
    async with PluginTestHost(tmp_path / "host") as host:
        context = await host.load(
            driver_plugin(tmp_path),
            config={"directory": str(tmp_path)},
        )
        await host.open_driver(card(config={"fail_close": True}))
        try:
            with pytest.raises(SDKError, match="(?i)close|stop|cleanup"):
                await host.close_driver("same")
            before = len(events(context, "create"))
            with pytest.raises(SDKError):
                await host.open_driver(card(config={"label": "replacement"}))
            assert len(events(context, "create")) == before
            assert not events(context, "closed")
            assert host.resource_snapshot(PLUGIN_ID)["resources"]
        finally:
            (tmp_path / "allow-close").touch()
            await host.close_driver("same")
        assert len(events(context, "closed")) == 1
        await host.open_driver(card(config={"label": "replacement"}))
        assert (
            await host.call_driver(
                "same",
                "echo",
                {},
            )
        ).structured_content["label"] == "replacement"


async def test_old_generation_discovery_cannot_publish_after_reload(tmp_path):
    async with PluginTestHost(tmp_path / "host") as host:
        context = await host.load(
            driver_plugin(tmp_path),
            config={"directory": str(tmp_path)},
        )
        await host.open_driver(card(config={"wait_discover": True}))
        pending = asyncio.create_task(host.list_driver_capabilities("same"))
        try:
            await wait_until(lambda: events(context, "discover"))
            assert (await host.reload(PLUGIN_ID, interrupt_tasks=True)).ok
            with pytest.raises((asyncio.CancelledError, SDKError)):
                await pending
            assert len(events(host.context(PLUGIN_ID), "closed")) == 1
            await host.open_driver(card(config={"label": "new-generation"}))
            result = await host.call_driver("same", "echo", {})
            assert result.structured_content["label"] == "new-generation"
        finally:
            (tmp_path / "release-discover").touch()
            if not pending.done():
                pending.cancel()
                with suppress(asyncio.CancelledError, SDKError):
                    await pending


async def test_environment_credential_alias_is_readonly(tmp_path, monkeypatch):
    root = tmp_path / "host"
    monkeypatch.setenv(
        "QWENPAW_DRIVER_SYNTHETIC_TOKEN",
        "synthetic-env-secret",
    )
    seed_card(
        root,
        "test",
        card(
            enabled=False,
            credentials={
                "environment": {
                    "kind": "env",
                    "ref": "env:QWENPAW_DRIVER_SYNTHETIC_TOKEN",
                },
            },
        ),
    )
    async with PluginTestHost(root) as host:
        await host.load(
            driver_plugin(tmp_path),
            config={"directory": str(tmp_path)},
        )
        response = await management(host, alias="environment")
        assert response.status == 200, response.text
        credential = response.json()["credential"]
        assert credential["secrets"] == {"value": "synthetic-env-secret"}
        denied = await management(
            host,
            action="update",
            alias="environment",
            revision=credential["revision"],
            secrets={"value": "synthetic-forbidden-write"},
        )
        assert denied.status == 403, denied.text
        assert not (root / "workspaces" / "test" / "credentials.yaml").exists()


def test_driver_credential_alias_inventory_is_public_readonly_property():
    attribute = DriverCredentialAccess.aliases
    assert isinstance(attribute, property)
    assert getattr(attribute, "fset") is None


def test_driver_subprocess_environment_is_explicit_public_method():
    assert callable(DriverContext.subprocess_environment)


async def test_subprocess_environment_is_configured_readonly_and_scoped(
    tmp_path,
    monkeypatch,
):
    from qwenpaw.envs import save_envs
    from qwenpaw.envs.store import get_envs_json_path

    root = tmp_path / "host"
    monkeypatch.setenv("DRIVER_HOST_ONLY_TEST", "host-only-secret")
    monkeypatch.delenv("DRIVER_CONFIGURED_TEST", raising=False)
    seed_card(root, "test", card(enabled=False))
    async with PluginTestHost(root) as host:
        await host.load(
            driver_plugin(tmp_path),
            config={"directory": str(tmp_path)},
        )
        assert get_envs_json_path().is_relative_to(root)
        save_envs({"DRIVER_CONFIGURED_TEST": "configured-value"})
        # A supported plaintext legacy fixture is rewritten by load_envs.
        # Entering a source context must leave it untouched until the
        # protocol explicitly requests its subprocess environment.
        configured = json.dumps({"DRIVER_CONFIGURED_TEST": "configured-value"})
        get_envs_json_path().write_text(configured)
        assert (await management(host)).status == 200
        assert get_envs_json_path().read_text() == configured
        response = await management(host, environment=True, save="old-env")
        assert response.status == 200, response.text
        assert response.json()["environment"] == {
            "configured": True,
            "host_secret_absent": True,
            "readonly": True,
            "only_configured": True,
        }
        stale = await host.request(
            "POST",
            "/api/driver-manage/saved",
            user_id="alice",
            json={"key": "old-env", "action": "environment"},
        )
        assert stale.status == 403, stale.text


async def test_source_empty_tool_whitelist_blocks_plugin_invoke(tmp_path):
    async with PluginTestHost(tmp_path / "host") as host:
        context = await host.load(
            driver_plugin(tmp_path),
            config={"directory": str(tmp_path)},
        )
        await host.open_driver(card(config={"tools": []}))
        capabilities = await host.list_driver_capabilities("same")
        echo = next(row for row in capabilities if row["name"] == "echo")
        assert echo["enabled"] is False
        with pytest.raises(SDKError, match="(?i)disabled|whitelist"):
            await host.call_driver("same", "echo", {})
        assert not events(context, "invoke")
        await host.open_driver(card(config={"tools": ["echo"]}))
        capabilities = await host.list_driver_capabilities("same")
        echo = next(row for row in capabilities if row["name"] == "echo")
        assert echo["enabled"] is True
        assert isinstance(
            await host.call_driver("same", "echo", {}),
            DriverCallResult,
        )
        assert len(events(context, "invoke")) == 1
