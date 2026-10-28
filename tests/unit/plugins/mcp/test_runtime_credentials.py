# -*- coding: utf-8 -*-
# Test-only service/auth observations; plugin fixtures import public SDK only.
# pylint: disable=protected-access
"""Finite runtime credential API preserves generic host providers."""

import inspect

import httpx
import pytest

from qwenpaw.plugins.drivers import DriverCredentialAccess
from qwenpaw.plugins.testing import PluginTestHost

from ..sdk_author_fixture import make_plugin
from .fixtures import card, mock_http, seed_card, seed_record

SOURCE = """
from qwenpaw.plugins import SDKError
from qwenpaw.plugins.apps import PawApp, HttpResponse
from qwenpaw.plugins.drivers import DriverProtocolSpec
class Plugin:
    def register(self, plugin):
        def forbidden(*_args):
            raise AssertionError("Disabled management must not connect")
        plugin.register_driver_protocol(DriverProtocolSpec(
            "mcp", lambda source: None, forbidden))
        app = PawApp(app_id="runtime-credential-test")
        saved = []
        @app.route("/resolve", methods=("POST",))
        async def resolve(ctx, request):
            data = request.json()
            try:
                if data.get("stale"):
                    await saved[0].resolve_runtime("oauth")
                    return {"accepted": True}
                async with ctx.driver_source("mcp", "same") as driver:
                    saved[:] = [driver.credentials]
                    alias = data.get("alias", "oauth")
                    if data.get("runtime_only"):
                        values = await driver.credentials.resolve_runtime(
                            alias)
                        return {"values": dict(values)}
                    raw = await driver.credentials.resolve(alias)
                    if data.get("update"):
                        await driver.credentials.update(alias,
                            expected_revision=raw.revision,
                            public=data["update"]["public"],
                            secrets=data["update"]["secrets"])
                    if data.get("raw_only"):
                        return {"raw": dict(raw.secrets)}
                    values = await driver.credentials.resolve_runtime(alias)
                    readonly = False
                    try:
                        values["mutation"] = "forbidden"
                    except TypeError:
                        readonly = True
                    return {"values": dict(values), "readonly": readonly,
                            "raw": dict(raw.secrets)}
            except SDKError as exc:
                return HttpResponse({"error": str(exc)}, status=403)
        plugin.register_app(app)
plugin = Plugin()
"""


def test_runtime_resolver_is_an_explicit_finite_public_method():
    method = DriverCredentialAccess.resolve_runtime
    assert inspect.iscoroutinefunction(method)
    assert tuple(inspect.signature(method).parameters) == ("self", "alias")


async def test_runtime_resolution_is_declared_readonly_and_scope_guarded(
    tmp_path,
    monkeypatch,
):
    root = tmp_path / "host"
    requests = []

    def token(request):
        requests.append(request)
        return httpx.Response(
            200,
            json={"access_token": "refreshed", "expires_in": 3600},
        )

    mock_http(monkeypatch, token)
    async with PluginTestHost(root) as host:
        await host.load(make_plugin(tmp_path, SOURCE, ["apps", "drivers"]))
        await seed_record(
            root,
            public={
                "expires_at": 1,
                "token_endpoint": "https://auth.invalid/token",
            },
            secrets={"access_token": "expired", "refresh_token": "refresh"},
        )
        seed_card(
            root,
            card(
                enabled=False,
                credentials={
                    "oauth": {
                        "kind": "oauth2_auth_code",
                        "ref": "synthetic-oauth",
                    },
                },
            ),
        )
        url = "/api/runtime-credential-test/resolve"
        raw = await host.request("POST", url, json={"raw_only": True})
        assert raw.status == 200, raw.text
        assert raw.json()["raw"]["access_token"] == "expired"
        assert not requests
        response = await host.request("POST", url, json={})
        assert response.status == 200, response.text
        assert response.json()["values"]["access_token"] == "refreshed"
        assert response.json()["readonly"] is True
        assert len(requests) == 1
        for alias in ("synthetic-oauth", "../foreign", "missing"):
            denied = await host.request("POST", url, json={"alias": alias})
            assert denied.status == 403, denied.text
        stale = await host.request("POST", url, json={"stale": True})
        assert stale.status == 403, stale.text
        assert len(requests) == 1
        assert all(
            "driver_manager" not in workspace._service_manager.services
            for workspace in host._workspaces.values()
        )


async def test_runtime_cache_tracks_sdk_cas_and_external_record_writes(
    tmp_path,
    monkeypatch,
):
    from qwenpaw.drivers.credentials.types import CredentialRecord

    root = tmp_path / "host"
    requests = []

    def token(request):
        requests.append(request)
        return httpx.Response(
            200,
            json={"access_token": "first-runtime", "expires_in": 3600},
        )

    mock_http(monkeypatch, token)
    async with PluginTestHost(root) as host:
        await host.load(make_plugin(tmp_path, SOURCE, ["apps", "drivers"]))
        store = await seed_record(
            root,
            kind="oauth2_cc",
            public={
                "token_endpoint": "https://auth.invalid/token",
                "client_id": "client",
            },
            secrets={"client_secret": "original-secret"},
        )
        seed_card(
            root,
            card(
                enabled=False,
                credentials={
                    "oauth": {
                        "kind": "oauth2_cc",
                        "ref": "synthetic-oauth",
                    },
                },
            ),
        )
        url = "/api/runtime-credential-test/resolve"
        initial = await host.request("POST", url, json={})
        assert initial.status == 200, initial.text
        assert initial.json()["values"]["access_token"] == "first-runtime"
        assert len(requests) == 1
        # An SDK write with the raw current revision must invalidate its
        # previously cached provider, even when this source is disabled.
        updated = await host.request(
            "POST",
            url,
            json={
                "update": {
                    "public": {
                        "token_endpoint": "https://auth.invalid/token",
                        "client_id": "new-client",
                    },
                    "secrets": {"client_secret": "updated-secret"},
                },
            },
        )
        assert updated.status == 200, updated.text
        assert len(requests) == 2
        assert b"client_secret=updated-secret" in requests[-1].content
        await store.put(
            CredentialRecord(
                ref="synthetic-oauth",
                kind="oauth2_cc",
                public={
                    "token_endpoint": "https://auth.invalid/token",
                    "client_id": "external",
                },
                secrets={"client_secret": "external-secret"},
            ),
        )
        external = await host.request("POST", url, json={})
        assert external.status == 200, external.text
        assert len(requests) == 3
        assert b"client_secret=external-secret" in requests[-1].content


async def test_runtime_refresh_does_not_clobber_concurrent_external_writer(
    tmp_path,
    monkeypatch,
):
    import asyncio
    import time
    from qwenpaw.drivers.credentials.types import CredentialRecord

    root = tmp_path / "host"
    entered, release = asyncio.Event(), asyncio.Event()

    async def token(_request):
        entered.set()
        await release.wait()
        return httpx.Response(
            200,
            json={"access_token": "stale-network", "expires_in": 3600},
        )

    mock_http(monkeypatch, token)
    async with PluginTestHost(root) as host:
        await host.load(make_plugin(tmp_path, SOURCE, ["apps", "drivers"]))
        store = await seed_record(
            root,
            public={
                "expires_at": 1,
                "token_endpoint": "https://auth.invalid/token",
            },
            secrets={"access_token": "expired", "refresh_token": "old"},
        )
        seed_card(
            root,
            card(
                enabled=False,
                credentials={
                    "oauth": {
                        "kind": "oauth2_auth_code",
                        "ref": "synthetic-oauth",
                    },
                },
            ),
        )
        task = asyncio.create_task(
            host.request(
                "POST",
                "/api/runtime-credential-test/resolve",
                json={},
            ),
        )
        try:
            await asyncio.wait_for(entered.wait(), 2)
            await store.put(
                CredentialRecord(
                    ref="synthetic-oauth",
                    kind="oauth2_auth_code",
                    public={
                        "expires_at": time.time() + 3600,
                        "writer": "external",
                    },
                    secrets={
                        "access_token": "newer",
                        "refresh_token": "new-refresh",
                    },
                ),
            )
            release.set()
            response = await asyncio.wait_for(task, 2)
            assert response.status in (200, 403), response.text
            if response.status == 200:
                assert response.json()["values"]["access_token"] == "newer"
            current = await store.get("synthetic-oauth")
            assert current.secrets == {
                "access_token": "newer",
                "refresh_token": "new-refresh",
            }
            assert current.public["writer"] == "external"
        finally:
            release.set()
            if not task.done():
                task.cancel()
            await asyncio.wait_for(
                asyncio.gather(task, return_exceptions=True),
                2,
            )


async def test_concurrent_runtime_refresh_for_same_source_is_single_exchange(
    tmp_path,
    monkeypatch,
):
    import asyncio

    root = tmp_path / "host"
    entered, release = asyncio.Event(), asyncio.Event()
    requests = []

    async def token(request):
        requests.append(request)
        entered.set()
        await release.wait()
        return httpx.Response(
            200,
            json={"access_token": "one-shared-refresh", "expires_in": 3600},
        )

    mock_http(monkeypatch, token)
    async with PluginTestHost(root) as host:
        await host.load(make_plugin(tmp_path, SOURCE, ["apps", "drivers"]))
        await seed_record(
            root,
            public={
                "expires_at": 1,
                "token_endpoint": "https://auth.invalid/token",
            },
            secrets={"access_token": "expired", "refresh_token": "refresh"},
        )
        seed_card(
            root,
            card(
                enabled=False,
                credentials={
                    "oauth": {
                        "kind": "oauth2_auth_code",
                        "ref": "synthetic-oauth",
                    },
                },
            ),
        )
        url = "/api/runtime-credential-test/resolve"
        first = asyncio.create_task(host.request("POST", url, json={}))
        second = None
        try:
            await asyncio.wait_for(entered.wait(), 2)
            second = asyncio.create_task(host.request("POST", url, json={}))
            await asyncio.sleep(0.02)
            assert len(requests) == 1
            release.set()
            responses = await asyncio.wait_for(
                asyncio.gather(first, second),
                2,
            )
            assert [r.status for r in responses] == [200, 200]
            assert all(
                r.json()["values"]["access_token"] == "one-shared-refresh"
                for r in responses
            )
            assert len(requests) == 1
        finally:
            release.set()
            tasks = [task for task in (first, second) if task is not None]
            for task in tasks:
                if not task.done():
                    task.cancel()
            await asyncio.wait_for(
                asyncio.gather(*tasks, return_exceptions=True),
                2,
            )


@pytest.mark.parametrize(
    "failure,runtime_only",
    [
        ("expired-auth-code", True),
        ("missing-record", True),
        ("missing-record", False),
    ],
)
async def test_credential_errors_do_not_expose_private_storage_reference(
    tmp_path,
    failure,
    runtime_only,
):
    root = tmp_path / "host"
    opaque_ref = "opaque-internal-storage-ref-5818b60e-synthetic"
    async with PluginTestHost(root) as host:
        await host.load(make_plugin(tmp_path, SOURCE, ["apps", "drivers"]))
        if failure == "expired-auth-code":
            await seed_record(
                root,
                ref=opaque_ref,
                public={"expires_at": 1},
                secrets={"access_token": "expired-synthetic"},
            )
        seed_card(
            root,
            card(
                enabled=False,
                credentials={
                    "oauth": {
                        "kind": "oauth2_auth_code",
                        "ref": opaque_ref,
                    },
                },
            ),
        )
        response = await host.request(
            "POST",
            "/api/runtime-credential-test/resolve",
            json={"runtime_only": runtime_only},
        )
        assert response.status == 403, response.text
        assert response.json()["error"]
        assert opaque_ref not in response.text
        assert "expired-synthetic" not in response.text
        assert all(
            "driver_manager" not in workspace._service_manager.services
            for workspace in host._workspaces.values()
        )
