"""Real installed WeChat management and Session; external HTTP only."""

import asyncio
import hashlib
from importlib import import_module
import json
from pathlib import Path
import shutil
import sys
from types import SimpleNamespace
from urllib.parse import urlsplit

import pytest_asyncio

from g3fd_dd_session_support import g3_host_import_boundary
from management_process_suite import GUARD
from wechat_w2_config_support import write_profiles
from wechat_w2_scope_suite import request

ROOT = Path(__file__).resolve().parents[3]
__all__ = ["g3_host_import_boundary", "wechat_g3"]


@pytest_asyncio.fixture
async def wechat_g3(tmp_path, monkeypatch, g3_host_import_boundary):
    from qwenpaw.app.channels.management import ChannelManagementService
    from qwenpaw.plugins.channel_adapter import ChannelRuntimeSettings
    from qwenpaw.plugins.loader import PluginLoader
    from qwenpaw.plugins.registry import PluginRegistry

    previous = GUARD.blocks
    monkeypatch.setattr(
        GUARD,
        "blocks",
        lambda name: name == "qwenpaw_channel_wechat"
        or name.startswith("qwenpaw_channel_wechat.")
        or previous(name),
    )
    monkeypatch.setattr(
        "qwenpaw.config.utils.get_config_path",
        lambda: tmp_path / "host/config.json",
    )
    monkeypatch.setattr(
        "qwenpaw.config.utils.get_plugins_dir", lambda: tmp_path / "installed"
    )
    old_registry = PluginRegistry._instance
    PluginRegistry._instance = None
    ledger = tmp_path / "native-client-lifecycle.jsonl"
    state = SimpleNamespace(
        requests=[],
        ledger=ledger,
        fetch={
            "qrcode": "native-code",
            "qrcode_img_content": "https://scan.invalid/native",
        },
        poll={"status": "waiting"},
        fault=None,
    )
    tasks = set()

    async def respond(reader, writer):
        task = asyncio.current_task()
        tasks.add(task)
        try:
            raw = await reader.readuntil(b"\r\n\r\n")
            headers = dict(
                line.split(": ", 1)
                for line in raw.decode().split("\r\n")[1:]
                if ": " in line
            )
            row = json.loads(
                await reader.readexactly(int(headers["Content-Length"]))
            )
            state.requests.append(row)
            path = urlsplit(row["url"]).path
            assert urlsplit(row["url"]).netloc == "ilinkai.weixin.qq.com"
            assert path in {
                "/ilink/bot/get_bot_qrcode",
                "/ilink/bot/get_qrcode_status",
            }
            operation = "fetch" if path.endswith("get_bot_qrcode") else "poll"
            response = (
                {"fault": "transport"}
                if state.fault == operation
                else {"body": getattr(state, operation)}
            )
            payload = json.dumps(response).encode()
            writer.write(
                b"HTTP/1.1 200 OK\r\nConnection: close\r\n"
                + f"Content-Length: {len(payload)}\r\n\r\n".encode()
                + payload
            )
            await writer.drain()
        finally:
            writer.close()
            await writer.wait_closed()
            tasks.discard(task)

    server = await asyncio.start_server(respond, "127.0.0.1", 0)
    host, port = server.sockets[0].getsockname()[:2]
    source = tmp_path / "source/wechat"
    shutil.copytree(
        ROOT / "plugins/channel/wechat",
        source,
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
    )
    package = source / "qwenpaw_channel_wechat"
    expected = {
        name: (package / name).read_bytes()
        for name in ("driver.py", "management.py", "client.py")
    }
    shutil.copyfile(
        Path(__file__).with_name("wechat_g3_http_boundary.py"),
        package / "_wechat_g3_http_boundary.py",
    )
    with (package / "__init__.py").open("a") as stream:
        stream.write(
            "\nfrom ._wechat_g3_http_boundary import install\n"
            + f"install({host!r}, {port!r}, {str(ledger)!r})\n"
        )
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
    state.loader, state.service, state.sessions = loader, service, sessions
    try:
        record = await loader.load_plugin_from_path(source)
        assert record.status in {"active", "registered"}, record.diagnostics
        for name, content in expected.items():
            assert (
                Path(record.source_path) / "qwenpaw_channel_wechat" / name
            ).read_bytes() == content
        write_profiles(
            tmp_path, monkeypatch, "wechat", {"enabled": False, "base_url": ""}
        )
        state.scope = api.resolve_channel_management_scope(
            request(header="A"), "wechat"
        )
        state.original_functions_sha = {
            name: hashlib.sha256(content).hexdigest()
            for name, content in expected.items()
        }
        yield state
    finally:
        try:
            await sessions.aclose()
            await service.aclose()
            if loader.get_loaded_plugin("wechat") is not None:
                report = await loader.unload_plugin("wechat")
                assert report.quiescent and not report.needs_restart
        finally:
            server.close()
            for task in tuple(tasks):
                task.cancel()
            await asyncio.gather(*tuple(tasks), return_exceptions=True)
            await server.wait_closed()
            PluginRegistry._instance = old_registry
