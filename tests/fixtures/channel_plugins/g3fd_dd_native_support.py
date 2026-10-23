"""Actual installed official payload, with child-only external HTTP boundary."""
import asyncio
import base64
import os
import hashlib
from importlib import import_module
import json
from pathlib import Path
import shutil
import sys
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

import pytest_asyncio

from g3fd_dd_session_support import g3_host_import_boundary
from wechat_w2_config_support import write_profiles
from wechat_w2_scope_suite import request

ROOT = Path(__file__).resolve().parents[3]
__all__ = ["g3_host_import_boundary", "native_qr"]


@pytest_asyncio.fixture
async def native_qr(tmp_path, monkeypatch):
    from qwenpaw.plugins.channel_adapter import ChannelRuntimeSettings
    from qwenpaw.plugins.loader import PluginLoader
    from qwenpaw.plugins.registry import PluginRegistry
    from qwenpaw.app.channels.management import ChannelManagementService

    monkeypatch.setattr(
        "qwenpaw.config.utils.get_config_path",
        lambda: tmp_path / "host/config.json",
    )
    monkeypatch.setattr(
        "qwenpaw.config.utils.get_plugins_dir", lambda: tmp_path / "installed"
    )
    old_registry = PluginRegistry._instance
    PluginRegistry._instance = None
    owned = []

    async def make(channel, domain="feishu", *, responses=None):
        requests = []
        tasks = set()
        state = SimpleNamespace(
            poll=None, requests=requests, responses=dict(responses or {})
        )

        async def respond(reader, writer):
            tasks.add(asyncio.current_task())
            try:
                header = await reader.readuntil(b"\r\n\r\n")
                headers = dict(
                    line.split(": ", 1)
                    for line in header.decode().split("\r\n")[1:]
                    if ": " in line
                )
                row = json.loads(
                    await reader.readexactly(int(headers["Content-Length"]))
                )
                if channel == "wechat":
                    row["action"] = urlsplit(row["url"]).path.rsplit("/", 1)[1]
                    row["fields"] = {
                        k: v[0]
                        for k, v in parse_qs(
                            urlsplit(row["url"]).query
                        ).items()
                    }
                elif channel in {"dingtalk", "qq"}:
                    row["action"] = urlsplit(row["url"]).path.rsplit("/", 1)[1]
                    row["fields"] = json.loads(row["body"])
                else:
                    row["fields"] = {
                        k: v[0] for k, v in parse_qs(row["body"]).items()
                    }
                    row["action"] = row["fields"]["action"]
                requests.append(row)
                (tmp_path / "actual-http-ledger.json").write_text(
                    json.dumps(requests, indent=2)
                )
                action = row["action"]
                response_headers = {}
                if channel == "qq":
                    if action == "create_bind_task":
                        state.bind_key = base64.b64decode(
                            row["fields"]["key"], validate=True
                        )
                        assert len(state.bind_key) == 32
                        body = {
                            "retcode": 0,
                            "data": {"task_id": "native-task"},
                        }
                    else:
                        from cryptography.hazmat.primitives.ciphers.aead import (
                            AESGCM,
                        )

                        nonce = os.urandom(12)
                        encrypted = nonce + AESGCM(state.bind_key).encrypt(
                            nonce, b"native-secret", None
                        )
                        data = {
                            "status": 2,
                            "bot_appid": "native-app",
                            "bot_encrypt_secret": base64.b64encode(
                                encrypted
                            ).decode(),
                        }
                        if (
                            getattr(make, "qq_openid", "native-user")
                            is not None
                        ):
                            data["user_openid"] = getattr(
                                make, "qq_openid", "native-user"
                            )
                        body = {"retcode": 0, "data": data}
                elif channel == "wechat":
                    body = (
                        {
                            "qrcode": "wechat-code",
                            "qrcode_img_content": "https://fixture.invalid/qr",
                        }
                        if action == "get_bot_qrcode"
                        else {
                            "status": "confirmed",
                            "bot_token": "wechat-issued-token",
                            "baseurl": "",
                        }
                    )
                elif action == "init":
                    body = (
                        {"errcode": 0, "nonce": "nonce"}
                        if channel == "dingtalk"
                        else {"supported_auth_methods": ["client_secret"]}
                    )
                    response_headers[
                        "set-cookie"
                    ] = "device_flow=fixture-cookie; Path=/; Secure"
                elif action == "begin":
                    body = {
                        "errcode": 0,
                        "device_code": "device-123",
                        "verification_uri_complete": "https://fixture.invalid/scan?code=abc",
                    }
                else:
                    body = state.poll or (
                        {
                            "status": "APPROVING",
                            "client_id": "client-123",
                            "client_secret": "secret-456",
                        }
                        if channel == "dingtalk"
                        else {
                            "client_id": "app-123",
                            "client_secret": "secret-456",
                            "user_info": {
                                "open_id": "open-789",
                                "tenant_brand": domain,
                            },
                        }
                    )
                envelope = {"body": body, "headers": response_headers}
                envelope.update(state.responses.get(action, {}))
                payload = json.dumps(envelope).encode()
                writer.write(
                    b"HTTP/1.1 200 OK\r\nConnection: close\r\n"
                    + f"Content-Length: {len(payload)}\r\n\r\n".encode()
                    + payload
                )
                await writer.drain()
            finally:
                writer.close()
                await writer.wait_closed()
                tasks.discard(asyncio.current_task())

        server = await asyncio.start_server(respond, "127.0.0.1", 0)
        host, port = server.sockets[0].getsockname()[:2]
        source = tmp_path / "source" / channel
        shutil.copytree(
            ROOT / "plugins/channel" / channel,
            source,
            ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
        )
        descriptor = json.loads((source / "channel.json").read_text())
        namespace = descriptor["entrypoint"]["module"].split(".")[0]
        package = source / namespace
        for filename in ("driver.py", "management.py"):
            assert (package / filename).read_bytes() == (
                ROOT / "plugins/channel" / channel / namespace / filename
            ).read_bytes()
        shutil.copyfile(
            Path(__file__).with_name("g3fd_dd_http_boundary.py"),
            package / "_g3fd_dd_http_boundary.py",
        )
        with (package / "__init__.py").open("a") as file:
            if getattr(make, "probe_trace", False):
                file.write(
                    "\nimport faulthandler as _probe_fh\n"
                    + "_probe_stack = open("
                    + repr(str(tmp_path / "probe-stack.log"))
                    + ", 'a')\n"
                    + "_probe_fh.dump_traceback_later(2, file=_probe_stack)\n"
                )
            file.write(
                f"\nfrom ._g3fd_dd_http_boundary import install\ninstall({host!r}, {port!r}, forbid_lark={getattr(make, 'forbid_lark', False)!r})\n"
            )
        state.namespace = namespace
        state.instrumented_source = source
        state.original_functions_sha = {
            name: hashlib.sha256((package / name).read_bytes()).hexdigest()
            for name in ("driver.py", "management.py")
        }
        loader = PluginLoader(
            [tmp_path / "installed"],
            channel_runtime=ChannelRuntimeSettings(
                python_executable=sys.executable,
                support_root=ROOT / "src",
                qwenpaw_version="2.2.2b4",
                selected_channels=None,
                startup_timeout=5,
                shutdown_timeout=2,
            ),
        )
        service = ChannelManagementService(loader)
        api = import_module("qwenpaw.app.channels.qrcode_sessions")
        sessions = api.ChannelQRCodeSessions(loader, service)
        owned.append((channel, loader, service, sessions, server, tasks))
        record = await loader.load_plugin_from_path(source)
        assert record.status in {"active", "registered"}, record.diagnostics
        config = {"enabled": False}
        if channel == "feishu":
            config["domain"] = domain
        elif channel == "wechat":
            config["base_url"] = domain
        write_profiles(tmp_path, monkeypatch, channel, config)
        scope = api.resolve_channel_management_scope(
            request(header="A"), channel
        )
        state.scope, state.sessions, state.service = scope, sessions, service
        state.loader = loader
        return state

    try:
        yield make
    finally:
        try:
            for channel, loader, service, sessions, server, tasks in reversed(
                owned
            ):
                await sessions.aclose()
                await service.aclose()
                if loader.get_loaded_plugin(channel) is not None:
                    report = await loader.unload_plugin(channel)
                    assert (
                        report.quiescent and not report.needs_restart
                    ), report.errors
                server.close()
                await server.wait_closed()
                if tasks:
                    await asyncio.gather(*tasks)
        finally:
            PluginRegistry._instance = old_registry
