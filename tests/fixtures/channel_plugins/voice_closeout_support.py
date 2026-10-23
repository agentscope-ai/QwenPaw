"""Authentic Voice ZIP, real host A3 and controlled external providers only."""

import asyncio
import base64
import hashlib
import hmac
import importlib.abc
import importlib.metadata
import json
from pathlib import Path
import shutil
import socket
import sys
from types import SimpleNamespace as NS

import aiohttp
from aiohttp import web
from fastapi import FastAPI
from packaging.markers import default_environment
from packaging.requirements import Requirement
import pytest
import pytest_asyncio
import uvicorn

from extension_process_suite import eventually, runtime
from g2_lifecycle_suite import copied_sdk
from g2_fault_runtime import fault_runtime

__all__ = ["runtime", "voice_host_guard", "fault_runtime"]
ROOT = Path(__file__).resolve().parents[3]
AUTH = "formal-local-voice-secret"
PUBLIC = "https://voice-formal.trycloudflare.com"


@pytest.fixture(autouse=True)
def voice_host_guard(monkeypatch):
    prefixes = (
        "twilio",
        "qwenpaw_channel_voice",
        "qwenpaw.app.channels.voice",
    )

    def forbidden(name):
        return any(name == p or name.startswith(p + ".") for p in prefixes)

    attempts = []
    assert not any(forbidden(n) for n in sys.modules)

    class Guard(importlib.abc.MetaPathFinder):
        def find_spec(self, fullname, path=None, target=None):
            if forbidden(fullname):
                attempts.append(fullname)
                raise AssertionError("Voice SDK/private in host: " + fullname)

    monkeypatch.setattr(sys, "meta_path", [Guard(), *sys.meta_path])
    yield
    assert not attempts and not any(forbidden(n) for n in sys.modules)


def official_voice_source(directory, key, **_ignored):
    from qwenpaw.plugins.official_channels import bundled_channel_source

    assert key == "voice"
    with bundled_channel_source(key) as source:
        destination = directory / key
        shutil.copytree(source, destination)
        assert {
            str(p.relative_to(source)): p.read_bytes()
            for p in source.rglob("*")
            if p.is_file()
        } == {
            str(p.relative_to(destination)): p.read_bytes()
            for p in destination.rglob("*")
            if p.is_file()
        }
    return destination


def signature(url, fields):
    # External Twilio wire signature. Product RequestValidator remains real
    # in the worker and independently checks this exact public URL/form.
    message = url + "".join(k + fields[k] for k in sorted(fields))
    return base64.b64encode(
        hmac.new(AUTH.encode(), message.encode(), hashlib.sha1).digest()
    ).decode()


@pytest_asyncio.fixture
async def voice_host(runtime, tmp_path):
    from qwenpaw.app.channels.ingress import ChannelIngressService
    from qwenpaw.app.routers.voice import voice_router
    from qwenpaw.plugins.registry import PluginRegistry

    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    sock.listen(128)
    sock.setblocking(False)
    port = sock.getsockname()[1]
    service = ChannelIngressService(PluginRegistry(), host_port=port)
    app = FastAPI()
    app.state.channel_ingress = service
    app.include_router(voice_router)
    server = uvicorn.Server(
        uvicorn.Config(
            app,
            host="127.0.0.1",
            port=port,
            lifespan="off",
            proxy_headers=False,
            log_level="error",
            ws="wsproto",
        )
    )
    task = asyncio.create_task(server.serve(sockets=[sock]))
    try:
        await eventually(lambda: server.started)
        async with aiohttp.ClientSession(trust_env=False) as client:
            yield NS(
                runtime=runtime,
                service=service,
                port=port,
                base=f"http://127.0.0.1:{port}",
                client=client,
                app=app,
            )
    finally:
        await service.aclose()
        server.should_exit = True
        await asyncio.wait_for(task, 8)
        sock.close()


@pytest_asyncio.fixture
async def voice_external(tmp_path, fault_runtime):
    root = tmp_path / "external"
    (root / "work/bin").mkdir(parents=True)
    calls = []
    current = {
        "sid": "PN-formal",
        "account_sid": "AC-formal",
        "voice_url": "https://old.example/incoming",
        "voice_method": "GET",
        "status_callback": "https://old.example/status",
        "status_callback_method": "GET",
    }

    phones = {
        sid: {**current, "sid": sid} for sid in ("PN-formal", "PN-A", "PN-B")
    }
    phones["PN-formal"] = current

    async def rest(request):
        prefix = "/2010-04-01/Accounts/AC-formal/IncomingPhoneNumbers/"
        assert request.path.startswith(prefix) and request.path.endswith(
            ".json"
        )
        sid = request.path.rsplit("/", 1)[-1].removesuffix(".json")
        assert sid in phones
        phone = phones[sid]
        data = dict(await request.post()) if request.method == "POST" else {}
        calls.append(
            {
                "method": request.method,
                "path": request.path,
                "auth": request.headers.get("Authorization"),
                "data": data,
            }
        )
        if data:
            for wire, field in (
                ("VoiceUrl", "voice_url"),
                ("VoiceMethod", "voice_method"),
                ("StatusCallback", "status_callback"),
                ("StatusCallbackMethod", "status_callback_method"),
            ):
                if wire in data:
                    phone[field] = data[wire]
        return web.json_response(phone)

    app = web.Application()
    app.router.add_route("*", "/{tail:.*}", rest)
    runner = web.AppRunner(app, shutdown_timeout=0.1)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    rest_url = "http://127.0.0.1:" + str(
        site._server.sockets[0].getsockname()[1]
    )
    config = root / "boundary.json"
    config.write_text(json.dumps({"root": str(root), "rest": rest_url}))
    # Existing offline fixture provides a unique interpreter/site. Preserve
    # real installed distributions/RECORDs; duplicate SDK origins stay strict.
    pending = ["twilio", "aiohttp", "python-dotenv"]
    copied = set(fault_runtime.packages)
    environment = {**default_environment(), "extra": ""}
    while pending:
        distribution = importlib.metadata.distribution(pending.pop())
        name = distribution.metadata["Name"].lower().replace("_", "-")
        if name in copied:
            continue
        copied.add(name)
        for value in distribution.requires or ():
            requirement = Requirement(value)
            if requirement.marker is None or requirement.marker.evaluate(
                environment
            ):
                pending.append(requirement.name)
        for relative in distribution.files or ():
            if (
                relative.is_absolute()
                or ".." in relative.parts
                or "__pycache__" in relative.parts
            ):
                continue
            source = Path(distribution.locate_file(relative))
            if source.is_file():
                target = fault_runtime.site / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, target)
    sdk = copied_sdk(
        tmp_path,
        "twilio",
        "twilio",
        "twilio/__init__.py",
        "\nfrom voice_formal_network_boundary import install as _install\n"
        f"_install({str(config)!r})\n",
        site=fault_runtime.site,
    )
    shutil.copy2(
        Path(__file__).with_name("voice_formal_network_boundary.py"), sdk
    )
    tunnel_log = root / "tunnel.jsonl"
    binary = root / "work/bin/cloudflared"
    binary.write_text(
        f"#!{sys.executable}\n"
        "import json,os,signal,sys,time\n"
        f"with open({str(tunnel_log)!r}, 'a') as f:\n"
        "    row = {'pid': os.getpid(), 'args': sys.argv[1:]}\n"
        "    f.write(json.dumps(row)+'\\n')\n"
        f"sys.stderr.write({PUBLIC!r}+'\\n'); sys.stderr.flush()\n"
        "signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))\n"
        "while True: time.sleep(0.1)\n"
    )
    binary.chmod(0o700)
    try:
        yield NS(
            sdk=sdk,
            python=fault_runtime.python,
            identity=fault_runtime.identity,
            calls=calls,
            current=current,
            phones=phones,
            tunnel_log=tunnel_log,
            root=root,
        )
    finally:
        await runner.cleanup()
