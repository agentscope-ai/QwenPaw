# -*- coding: utf-8 -*-
"""Exercise the protocol through production adapters in a fresh process."""

# pylint: disable=protected-access
import asyncio
import hashlib
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time

import httpx
import psutil
import yaml

from qwenpaw.app.mcp_plugin_migration import inventory_mcp_usage
from qwenpaw.app.mcp_plugin_upgrade import prepare_startup_plugins
from qwenpaw.plugins.testing import PluginTestHost

PLUGIN_ID = "qwenpaw-mcp"
REPO = Path(__file__).resolve().parents[3]
PLUGIN = REPO / "plugins/protocol/mcp"
PEER = Path(__file__).with_name("optional_runtime_peer.py")
MODE, ROOT_VALUE = sys.argv[1:3]
ROOT = Path(ROOT_VALUE)


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value))


def fingerprint(path):
    return {
        str(file.relative_to(path)): hashlib.sha256(
            file.read_bytes(),
        ).hexdigest()
        for file in path.rglob("*")
        if file.is_file()
    }


def source(name, transport, port=0, *, enabled=True):
    endpoint = {"transport": transport}
    if transport == "stdio":
        endpoint.update(
            command=sys.executable,
            args=[str(PEER), "stdio", "0", "unused"],
            cwd=str(ROOT),
            env={"MCP_CONTROLLED_ENV": "present"},
        )
    else:
        endpoint.update(
            url=f"http://127.0.0.1:{port}/"
            + ("sse" if transport == "sse" else "mcp"),
            headers={"X-Controlled": "present"},
            http_timeout=5,
        )
    return {
        "name": name,
        "protocol": "mcp",
        "enabled": enabled,
        "endpoint": endpoint,
        "config": {"display_name": "Controlled name"},
        "policy": {"default_effect": "allow"},
    }


def seed(cards=(), legacy=None, workspaces=("test",)):
    if not (ROOT / "config.json").exists():
        write(
            ROOT / "config.json",
            {
                "agents": {
                    "profiles": {
                        name: {
                            "id": name,
                            "workspace_dir": str(ROOT / "workspaces" / name),
                        }
                        for name in workspaces
                    },
                },
            },
        )
        for name in workspaces:
            write(
                ROOT / "workspaces" / name / "agent.json",
                {"id": name, "name": name, **(legacy or {})},
            )
        for workspace, card in cards:
            path = (
                ROOT
                / "workspaces"
                / workspace
                / "drivers/mcp"
                / (card["name"] + ".yaml")
            )
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(yaml.safe_dump(card))
        write(
            ROOT / "fixture-before.json",
            {
                "config": json.loads((ROOT / "config.json").read_text()),
                "workspace_sha256": fingerprint(ROOT / "workspaces"),
            },
        )


class LocalPeer:
    def __init__(self, transport):
        self.transport = transport
        self.process = None
        with socket.socket() as connection:
            connection.bind(("127.0.0.1", 0))
            self.port = connection.getsockname()[1]
        self.log = open(  # pylint: disable=consider-using-with
            ROOT / (transport + ".peer.log"),
            "a",
            encoding="utf-8",
        )

    async def start(self):
        self.process = subprocess.Popen(  # pylint: disable=consider-using-with
            [
                sys.executable,
                "-B",
                str(PEER),
                self.transport,
                str(self.port),
                str(ROOT / "oauth-evidence.json"),
            ],
            env=dict(os.environ),
            stdout=self.log,
            stderr=self.log,
        )
        for _ in range(100):
            assert self.process.poll() is None, "Local peer exited"
            try:
                async with httpx.AsyncClient() as client:
                    await client.get(
                        f"http://127.0.0.1:{self.port}/health",
                        timeout=0.2,
                    )
                return
            except httpx.TransportError:
                await asyncio.sleep(0.05)
        raise AssertionError("Local peer not ready")

    def stop(self):
        if self.process and self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=10)

    def close(self):
        try:
            self.stop()
        finally:
            self.log.close()


async def prepare(host):
    return await prepare_startup_plugins(
        host._loader,
        host._workspace_manager,
        app=host._http_app,
        snapshot=inventory_mcp_usage(
            config_path=ROOT / "config.json",
            plugins_dir=ROOT / "plugins",
        ),
    )


async def runtime(host, workspace_id="test"):
    workspace = await host._workspace(workspace_id)
    manager = workspace._service_manager
    descriptor = manager.descriptors["driver_manager"]
    await manager._start_service(descriptor)
    assert workspace.driver_manager is not None
    return workspace.driver_manager


async def unused():
    from qwenpaw.drivers.manager import DriverManager
    from qwenpaw.drivers.storage import AsyncDriverCardStore
    from qwenpaw.plugins.loader import PluginLoader

    data = None
    if MODE != "unused-none":
        version = MODE.removeprefix("unused-v")
        data = json.loads(
            (
                REPO
                / f"tests/fixtures/mcp_plugin_upgrade/default-v{version}.json"
            ).read_text(),
        )
    seed(
        cards=[("test", row) for row in (data or {}).get("cards", [])],
        legacy=(data or {}).get("config"),
    )
    before = fingerprint(ROOT / "workspaces")
    observations = {"manager_constructions": 0, "snapshots": 0}
    original = DriverManager.__init__

    def observe(self, *args, **kwargs):
        observations["manager_constructions"] += 1
        original(self, *args, **kwargs)

    async def snapshot(*_args, **_kwargs):
        observations["snapshots"] += 1
        raise AssertionError("Unused runtime scanned cards")

    async def forbidden(*_args, **_kwargs):
        raise AssertionError(
            "Unused startup reached installer or dependency gate",
        )

    def forbidden_network(*_args, **_kwargs):
        raise AssertionError("Unused startup attempted a network connection")

    class ForbiddenProcess(subprocess.Popen):
        def __init__(self, *_args, **_kwargs):
            raise AssertionError("Unused startup attempted a subprocess")

    socket.socket.connect = forbidden_network
    subprocess.Popen = ForbiddenProcess
    DriverManager.__init__ = observe
    AsyncDriverCardStore.snapshot = snapshot
    PluginLoader.install_plugin_files = forbidden
    PluginLoader._ensure_dependencies_installed = forbidden
    async with PluginTestHost(ROOT) as host:
        result = await prepare(host)
        assert result.decision.status == "unused"
        assert not host._loader.get_loaded_plugin(PLUGIN_ID)
        discovered = host._loader.discover_plugins()
        assert PLUGIN_ID not in [manifest.id for manifest, _path in discovered]
        service = await runtime(host)
        try:
            assert service.manager is None and service.watcher is None
            assert await service.list_capabilities() == []
            await asyncio.sleep(2.15)
            assert observations == {"manager_constructions": 0, "snapshots": 0}
            assert fingerprint(ROOT / "workspaces") == before
            assert not (ROOT / "plugins" / PLUGIN_ID).exists()
        finally:
            await service.shutdown_all()
    project = [
        name
        for name in sys.modules
        if name.startswith(
            (
                "qwenpaw.drivers.handlers.mcp",
                "qwenpaw.drivers.transports.mcp",
                "qwenpaw.app.mcp.manager",
                "qwenpaw_plugin_qwenpaw_mcp",
            ),
        )
    ]
    assert not project, project
    observations.update(
        project_mcp_imports=project,
        upstream_mcp_imports=[
            name for name in sys.modules if name.startswith("mcp.")
        ],
    )
    return observations


async def transport_probe():
    kind = MODE.removeprefix("transport-")
    peer = None
    ROOT.mkdir(parents=True, exist_ok=True)
    try:
        if kind != "stdio":
            peer = LocalPeer(
                "streamable-http" if kind == "streamable_http" else "sse",
            )
            await peer.start()
        card = source("same", kind, peer.port if peer else 0)
        seed(
            cards=[("test", card), ("other", {**card, "enabled": False})],
            workspaces=("test", "other"),
        )
        async with PluginTestHost(
            ROOT,
            workspace_dirs={"test": "test", "other": "other"},
        ) as host:
            assert (await prepare(host)).status in {"installed", "unchanged"}
            service = await runtime(host)
            other = await runtime(host, "other")
            try:
                assert other.manager is None and other.watcher is not None
                assert await other.list_capabilities() == []
                capabilities = await service.list_capabilities()
                assert {row.name for row in capabilities} == {
                    "echo",
                    "process_info",
                }
                from qwenpaw.drivers.capabilities import DriverInvocation

                result = await service.invoke_capability(
                    DriverInvocation(
                        capability_id="driver://mcp/same/tools/echo#invoke",
                        payload={"text": "cold-real-peer"},
                    ),
                )
                assert result.ok and "cold-real-peer" in str(result.value)
                info = await service.invoke_capability(
                    DriverInvocation(
                        capability_id=(
                            "driver://mcp/same/tools/process_info#invoke"
                        ),
                        payload={},
                    ),
                )
                assert info.ok, info
                if peer:
                    peer.stop()
                    await peer.start()
                else:
                    details = info.value.structured_content or json.loads(
                        info.value.content[0].text,
                    )
                    assert (
                        details["cwd"] == str(ROOT)
                        and details["has_controlled_env"]
                    )
                    os.kill(details["pid"], 15)
                # A failed in-flight call may not be replayed automatically.
                # Retry only this deliberately idempotent echo after reconnect.
                deadline = time.monotonic() + 15
                while True:
                    result = await service.invoke_capability(
                        DriverInvocation(
                            capability_id=(
                                "driver://mcp/same/tools/echo#invoke"
                            ),
                            payload={"text": "reconnected"},
                        ),
                    )
                    if result.ok:
                        break
                    assert time.monotonic() < deadline, result
                    await asyncio.sleep(0.2)
                assert "reconnected" in str(result.value), result
                saved = yaml.safe_load(
                    (
                        ROOT / "workspaces/test/drivers/mcp/same.yaml"
                    ).read_text(),
                )
                assert saved == card
            finally:
                await service.shutdown_all()
                await other.shutdown_all()
        return {
            "transport": kind,
            "real_rpc": True,
            "reconnected": True,
            "cross_workspace_disabled": True,
        }
    finally:
        if peer:
            peer.close()


async def legacy_probe():
    live = source("legacy", "stdio")
    legacy_config = {
        "mcp": {
            "migration_version": 0,
            "clients": {
                "legacy": {
                    "name": "Controlled display",
                    "enabled": True,
                    **live["endpoint"],
                    "tools": ["echo", "process_info"],
                },
                "disabled": {
                    "name": "Retained disabled",
                    "enabled": False,
                    **live["endpoint"],
                    "tools": [],
                },
            },
        },
    }
    existed = (ROOT / "config.json").exists()
    seed(legacy=legacy_config)
    async with PluginTestHost(ROOT) as host:
        assert (await prepare(host)).status in {"installed", "unchanged"}
        service = await runtime(host)
        try:
            raw = json.loads((ROOT / "workspaces/test/agent.json").read_text())
            assert raw["mcp"]["migration_version"] == 2
            retained = await service.card_store.load(
                "disabled",
                protocol="mcp",
            )
            assert retained.enabled is False
            assert retained.config["tools"] == []
            assert retained.config["display_name"] == "Retained disabled"
            assert retained.endpoint["cwd"] == str(ROOT)
            assert retained.endpoint["command"] == sys.executable
            assert retained.endpoint["args"] == live["endpoint"]["args"]
            if existed:
                assert not (
                    ROOT / "workspaces/test/drivers/mcp/legacy.yaml"
                ).exists()
                assert service.manager is None
            else:
                rows = await service.list_capabilities()
                assert {row.name for row in rows} == {"echo", "process_info"}
                from qwenpaw.drivers.capabilities import DriverInvocation

                result = await service.invoke_capability(
                    DriverInvocation(
                        capability_id="driver://mcp/legacy/tools/echo#invoke",
                        payload={"text": "migrated-real-peer"},
                        request_context={
                            "agent_id": "test",
                            "approval_level": "off",
                        },
                    ),
                )
                assert result.ok and "migrated-real-peer" in str(
                    result.value,
                ), result
        finally:
            await service.shutdown_all()
    return {
        "migration_version": 2,
        "retained_tools": [],
        "deleted_not_resurrected": existed,
        "real_rpc": not existed,
    }


async def auth_oauth():  # pylint: disable=too-many-statements
    from qwenpaw.app import auth
    from qwenpaw.config import load_config, save_config
    from qwenpaw.drivers.manager import DriverManager
    from qwenpaw.drivers.credentials.store import AsyncCredentialStore
    from qwenpaw.drivers.credentials.types import CredentialRecord

    ROOT.mkdir(parents=True, exist_ok=True)
    peer = LocalPeer("sse")
    try:
        await peer.start()
        oauth_source = source("oauth", "sse", peer.port, enabled=False)
        oauth_source["credentials"] = {
            "oauth": {"kind": "oauth2_auth_code", "ref": "controlled-oauth"},
        }
        seed(cards=[("test", oauth_source)], workspaces=("test", "other"))
        os.environ["QWENPAW_AUTH_ENABLED"] = "1"
        original_init = DriverManager.__init__
        constructions = []

        def observe(self, *args, **kwargs):
            constructions.append(self)
            original_init(self, *args, **kwargs)

        DriverManager.__init__ = observe
        async with PluginTestHost(
            ROOT,
            workspace_dirs={"test": "test", "other": "other"},
        ) as host:
            assert (await prepare(host)).status == "installed"
            config = load_config()
            config.security.allow_no_auth_hosts = []
            save_config(config)
            assert auth.register_user("alice", "controlled-test-password")
            await host._workspace("test")
            await host._workspace("other")
            await host._loader.activate_all_loaded()
            host._http_app.add_middleware(auth.AuthMiddleware)
            path = "/api/qwenpaw-mcp/management"
            denied = await host.request("GET", path, user_id=None)
            assert denied.status == 401
            token = auth.create_token("alice")
            headers = {"Authorization": "Bearer " + token}
            for workspace in ("test", "other"):
                allowed = await host.request(
                    "GET",
                    path,
                    user_id=None,
                    headers=headers,
                    workspace_id=workspace,
                )
                assert allowed.status == 200, allowed.text
                assert allowed.json()["workspace_id"] == workspace
            assert not constructions
            store = AsyncCredentialStore(
                ROOT / "workspaces/test/credentials.yaml",
            )
            await store.put(
                CredentialRecord(
                    ref="controlled-oauth",
                    kind="oauth2_auth_code",
                    public={
                        "client_id": "controlled-client",
                        "retained": "public",
                    },
                    secrets={"retained": "controlled-private"},
                ),
            )
            base = f"http://127.0.0.1:{peer.port}"
            started = await host.request(
                "POST",
                "/api/qwenpaw-mcp/oauth/start/oauth",
                user_id=None,
                headers=headers,
                json={
                    "client_id": "controlled-client",
                    "auth_endpoint": base + "/oauth/authorize",
                    "token_endpoint": base + "/oauth/token",
                    "scope": "read",
                    "redirect_uri": "http://127.0.0.1/controlled-callback",
                },
            )
            assert started.status == 200, started.text
            state = started.json()["session_id"]
            wrong = await host.request(
                "POST",
                "/api/qwenpaw-mcp/oauth/callback",
                user_id=None,
                headers=headers,
                workspace_id="other",
                json={"state": state, "code": "controlled-code"},
            )
            assert wrong.status == 403
            # A cross-workspace attempt claims the one-use state; start again.
            started = await host.request(
                "POST",
                "/api/qwenpaw-mcp/oauth/start/oauth",
                user_id=None,
                headers=headers,
                json={
                    "client_id": "controlled-client",
                    "auth_endpoint": base + "/oauth/authorize",
                    "token_endpoint": base + "/oauth/token",
                    "scope": "read",
                    "redirect_uri": "http://127.0.0.1/controlled-callback",
                },
            )
            assert started.status == 200, started.text
            completed = await host.request(
                "POST",
                "/api/qwenpaw-mcp/oauth/callback",
                user_id=None,
                headers=headers,
                json={
                    "state": started.json()["session_id"],
                    "code": "controlled-code",
                },
            )
            assert completed.status == 200, completed.text
            record = await store.get("controlled-oauth")
            assert record.secrets["access_token"] == "controlled-access-token"
            assert (
                record.secrets["refresh_token"] == "controlled-refresh-token"
            )
            assert record.secrets["retained"] == "controlled-private"
            assert record.public["retained"] == "public"
            assert json.loads((ROOT / "oauth-evidence.json").read_text()) == {
                "token_requests": 1,
                "pkce": True,
            }
            assert not constructions
        return {
            "unauthenticated": 401,
            "authenticated_workspaces": ["test", "other"],
            "manager_constructions": len(constructions),
            "local_oauth_exchange": True,
            "cross_workspace_rejected": True,
        }
    finally:
        peer.close()


async def mixed():
    from qwenpaw.drivers.capabilities import DriverInvocation

    ROOT.mkdir(parents=True, exist_ok=True)
    peers = [LocalPeer("sse"), LocalPeer("streamable-http")]
    try:
        for peer in peers:
            await peer.start()
        cards = [
            ("test", source("shared", "sse", peers[0].port)),
            ("test", source("local", "stdio")),
            ("test", source("http", "streamable_http", peers[1].port)),
            ("other", source("shared", "streamable_http", peers[1].port)),
            ("other", source("local", "stdio")),
        ]
        seed(cards=cards, workspaces=("test", "other"))
        before = fingerprint(ROOT / "workspaces")
        async with PluginTestHost(
            ROOT,
            workspace_dirs={"test": "test", "other": "other"},
        ) as host:
            assert (await prepare(host)).status == "installed"
            services = [
                await runtime(host, workspace)
                for workspace in ("test", "other")
            ]
            try:
                for service, expected_peer in zip(services, peers):
                    rows = await service.list_capabilities()
                    assert any(row.driver_name == "shared" for row in rows)
                    info = await service.invoke_capability(
                        DriverInvocation(
                            capability_id=(
                                "driver://mcp/shared/tools/process_info#invoke"
                            ),
                            payload={},
                        ),
                    )
                    assert info.ok, info
                    details = info.value.structured_content or json.loads(
                        info.value.content[0].text,
                    )
                    assert details["pid"] == expected_peer.process.pid
                assert fingerprint(ROOT / "workspaces") == before
            finally:
                for service in services:
                    await service.shutdown_all()
        return {
            "mixed_transports": ["stdio", "sse", "streamable_http"],
            "same_name_workspace_isolation": True,
            "config_bytes_preserved": True,
        }
    finally:
        for peer in peers:
            peer.close()


async def late_install():
    from qwenpaw.drivers.capabilities import DriverInvocation
    from qwenpaw.drivers.contracts import DriverCard

    seed()
    async with PluginTestHost(ROOT) as host:
        assert (await prepare(host)).decision.status == "unused"
        service = await runtime(host)
        assert service.manager is None and service.watcher is None
        try:
            assert (await host.install(PLUGIN)).ok
            await service.upsert_driver(DriverCard(**source("late", "stdio")))
            result = await service.invoke_capability(
                DriverInvocation(
                    capability_id="driver://mcp/late/tools/echo#invoke",
                    payload={"text": "installed-later"},
                ),
            )
            assert result.ok and "installed-later" in str(result.value), result
            path = ROOT / "workspaces/test/drivers/mcp/late.yaml"
            before = path.read_bytes()
            assert (await host.set_enabled(PLUGIN_ID, False)).ok
            assert path.read_bytes() == before
            assert service.manager is None and service.watcher is None
            assert (await host.set_enabled(PLUGIN_ID, True)).ok
            result = await service.invoke_capability(
                DriverInvocation(
                    capability_id="driver://mcp/late/tools/echo#invoke",
                    payload={"text": "reenabled"},
                ),
            )
            assert result.ok and "reenabled" in str(result.value), result
            assert (await host.reload(PLUGIN_ID)).ok
            result = await service.invoke_capability(
                DriverInvocation(
                    capability_id="driver://mcp/late/tools/echo#invoke",
                    payload={"text": "updated"},
                ),
            )
            assert result.ok and "updated" in str(result.value), result
            assert path.read_bytes() == before
            assert (await host.uninstall(PLUGIN_ID)).quiescent
            assert path.read_bytes() == before
            assert service.manager is None and service.watcher is None
        finally:
            await service.shutdown_all()
    async with PluginTestHost(ROOT) as host:
        assert (await prepare(host)).decision.status == "explicit_off"
        assert not (ROOT / "plugins" / PLUGIN_ID).exists()
    return {
        "same_workspace_late_install": True,
        "disable_enable_update": True,
        "uninstall_restart_preserves_intent_and_data": True,
    }


async def main():
    baseline = asyncio.all_tasks()
    handler = (
        unused
        if MODE.startswith("unused-")
        else {
            "legacy": legacy_probe,
            "auth-oauth": auth_oauth,
            "mixed": mixed,
            "late-install": late_install,
        }.get(MODE, transport_probe)
    )
    result = await handler()
    await asyncio.sleep(0.1)
    leaked = [
        task.get_name()
        for task in asyncio.all_tasks() - baseline
        if not task.done()
    ]
    assert not leaked, leaked
    children = psutil.Process().children(recursive=True)
    assert not children, [process.pid for process in children]
    from qwenpaw.app.mcp_plugin_upgrade import get_optional_mcp_plugin_dir
    import qwenpaw

    result["qwenpaw_file"] = qwenpaw.__file__
    result["optional_resource"] = str(get_optional_mcp_plugin_dir())
    result["tasks_after_stop"] = leaked
    result["children_after_stop"] = []
    write(ROOT / "observations.json", result)
    print(json.dumps(result))


if __name__ == "__main__":
    asyncio.run(main())
