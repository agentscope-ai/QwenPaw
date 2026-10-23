"""Actual official WeCom Loader/worker; external HTTP transport only."""

import asyncio
import hashlib
from importlib import import_module
import json
from pathlib import Path
import shutil
import sys
from types import SimpleNamespace
from urllib.parse import urlsplit

from fastapi import FastAPI
import httpx
import pytest_asyncio

from g3fd_dd_session_support import g3_host_import_boundary
from management_process_suite import GUARD
from wechat_w2_config_support import write_profiles
from wechat_w2_scope_suite import request

ROOT = Path(__file__).resolve().parents[3]
__all__ = ["g3_host_import_boundary", "wecom_qr"]


@pytest_asyncio.fixture
async def wecom_qr(tmp_path, monkeypatch, g3_host_import_boundary):
    from qwenpaw.app.channels.management import ChannelManagementService
    from qwenpaw.app.multi_agent_manager import MultiAgentManager
    from qwenpaw.app.workspace import Workspace
    from qwenpaw.plugins.channel_adapter import ChannelRuntimeSettings
    from qwenpaw.plugins.loader import PluginLoader
    from qwenpaw.plugins.registry import PluginRegistry

    previous = GUARD.blocks
    monkeypatch.setattr(
        GUARD,
        "blocks",
        lambda name: name == "qwenpaw_channel_wecom"
        or name.startswith("qwenpaw_channel_wecom.")
        or previous(name),
    )
    monkeypatch.setattr(
        "qwenpaw.config.utils.get_config_path",
        lambda: tmp_path / "host/config.json",
    )
    monkeypatch.setattr(
        "qwenpaw.config.utils.get_plugins_dir", lambda: tmp_path / "installed"
    )
    prior_registry = PluginRegistry._instance
    PluginRegistry._instance = None
    tasks = set()
    state = SimpleNamespace(
        requests=[],
        fetch_text=None,
        fetch_redirect=False,
        poll={"data": {"status": "waiting"}},
        poll_status=200,
        scode="wecom code/+?=%",
    )

    async def respond(reader, writer):
        task = asyncio.current_task()
        tasks.add(task)
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
            state.requests.append(row)
            path = urlsplit(row["url"]).path
            assert urlsplit(row["url"]).netloc == "work.weixin.qq.com"
            if path == "/ai/qc/gen" and state.fetch_redirect:
                response = {
                    "status_code": 302,
                    "headers": {"location": "/ai/qc/final"},
                    "text": "",
                }
            elif path in {"/ai/qc/gen", "/ai/qc/final"}:
                settings = {
                    "scode": state.scode,
                    "auth_url": "https://work.weixin.qq.com/scan/test-only",
                }
                response = {
                    "text": (
                        state.fetch_text
                        if state.fetch_text is not None
                        else "<script>window.settings = "
                        + json.dumps(settings)
                        + "</script>"
                    )
                }
            else:
                assert path == "/ai/qc/query_result"
                response = {
                    "status_code": state.poll_status,
                    "headers": {"location": "https://must-not-follow.invalid"},
                    "body": state.poll,
                }
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
    source = tmp_path / "source/wecom"
    shutil.copytree(
        ROOT / "plugins/channel/wecom",
        source,
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
    )
    package = source / "qwenpaw_channel_wecom"
    original_functions = {
        name: hashlib.sha256((package / name).read_bytes()).hexdigest()
        for name in ("driver.py", "management.py")
    }
    shutil.copyfile(
        Path(__file__).with_name("g3wecom_http_boundary.py"),
        package / "_g3wecom_http_boundary.py",
    )
    with (package / "__init__.py").open("a") as file:
        file.write(
            "\nfrom ._g3wecom_http_boundary import install\n"
            + f"install({host!r}, {port!r})\n"
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
    qr_api = import_module("qwenpaw.app.channels.qrcode_sessions")
    sessions = qr_api.ChannelQRCodeSessions(loader, service)
    state.loader, state.service, state.sessions = loader, service, sessions
    try:
        record = await loader.load_plugin_from_path(source)
        assert record.status in {"active", "registered"}, record.diagnostics
        _, paths = write_profiles(
            tmp_path,
            monkeypatch,
            "wecom",
            {
                "enabled": False,
                "bot_id": "previous-test-bot",
                "secret": "previous-test-secret",
                "welcome_text": "preserve existing setting",
                "media_dir": str(tmp_path / "saved-wecom-media"),
            },
        )
        state.paths = paths
        state.scope = qr_api.resolve_channel_management_scope(
            request(header="A"), "wecom"
        )
        manager = MultiAgentManager()
        for name in ("A", "B"):
            manager.agents[name] = Workspace(name, str(paths[name]))
        manager.channel_qrcode_sessions = sessions
        app = FastAPI()
        routes = import_module("qwenpaw.app.routers.config")
        app.include_router(routes.router)
        app.state.plugin_loader = loader
        app.state.channel_management = service
        app.state.channel_qrcode_sessions = sessions
        app.state.multi_agent_manager = manager
        state.reloads = []
        monkeypatch.setattr(
            routes,
            "schedule_agent_reload",
            lambda _request, agent_id: state.reloads.append(agent_id),
        )
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://testserver",
        ) as client:
            state.client = client
            yield state
        assert all(
            hashlib.sha256((package / name).read_bytes()).hexdigest() == digest
            for name, digest in original_functions.items()
        )
    finally:
        try:
            await sessions.aclose()
            await service.aclose()
            if loader.get_loaded_plugin("wecom") is not None:
                report = await loader.unload_plugin("wecom")
                assert report.quiescent and not report.needs_restart
        finally:
            server.close()
            for task in tuple(tasks):
                task.cancel()
            await asyncio.gather(*tuple(tasks), return_exceptions=True)
            await server.wait_closed()
            PluginRegistry._instance = prior_registry
