# -*- coding: utf-8 -*-
"""Only the external component is a fixture; IPC and processes remain real."""

import asyncio
import importlib.abc
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import threading

MODE = globals().get("MODE", "normal")
MARKER = globals().get("MARKER", "")

BLOCKED = (
    "qwenpaw.app",
    "qwenpaw.channel_protocol",
    "qwenpaw.plugins.loader",
    "qwenpaw.plugins.api",
    "qwenpaw.plugins.registry",
    "lark_oapi",
    "dingtalk_stream",
    "alibabacloud_dingtalk",
)
ATTEMPTS = []


def blocked(name):
    return any(
        name == prefix or name.startswith(prefix + ".") for prefix in BLOCKED
    )


class ImportGuard(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, _path=None, _target=None):
        if blocked(fullname):
            ATTEMPTS.append(fullname)
            raise AssertionError(f"Generic worker imported {fullname}")


assert not any(
    blocked(name) for name in sys.modules
), "Worker boot loaded channel/framework code"
sys.meta_path.insert(0, ImportGuard())

if MODE == "import_hang":
    Path(MARKER).write_text(str(os.getpid()))
    threading.Event().wait()


class Worker:
    def __init__(self):
        self.config = {}
        self.started = asyncio.Event()

    def bind(self, context):
        self.context = context
        for name in ("probe", "reverse", "commit", "slow", "crash", "stale"):
            context.peer.register_method(
                f"fixture.{name}",
                getattr(self, name),
            )
        if MODE == "descendant":
            ready = Path(MARKER + ".ready")
            ready.unlink(missing_ok=True)
            child = subprocess.Popen(  # pylint: disable=consider-using-with
                [
                    sys.executable,
                    "-I",
                    "-c",
                    "import pathlib,signal,sys,threading; "
                    "signal.signal(signal.SIGTERM,signal.SIG_IGN); "
                    "pathlib.Path(sys.argv[1]).touch(); "
                    "threading.Event().wait()",
                    str(ready),
                ],
            )
            for _ in range(400):
                if ready.exists():
                    break
                threading.Event().wait(0.005)
            assert ready.exists(), "Descendant failed to initialize"
            Path(MARKER).write_text(str(child.pid))
        if MODE == "stop_hang":
            signal.signal(signal.SIGTERM, signal.SIG_IGN)
        if MODE == "flood":
            for _ in range(64):
                os.write(1, b"untrusted-log " * 4096)
                os.write(2, b"untrusted-log " * 4096)

    async def start(self, config):
        self.config = config
        self.started.set()
        if MODE == "start_hang":
            Path(MARKER).write_text(str(os.getpid()))
            threading.Event().wait()
        if MODE == "secret_failure":
            print(config["credential"], file=sys.stderr, flush=True)
            raise RuntimeError(config["credential"])
        await self.context.set_state("ready")

    async def stop(self):
        if MODE == "stop_hang":
            Path(MARKER).write_text(str(os.getpid()))
            threading.Event().wait()

    async def probe(self, _params, request):
        await self.started.wait()
        secret = self.config.get("credential", "")
        sdk = None
        if MODE == "shared_site":
            import generic_fixture_sdk

            sdk = generic_fixture_sdk.VALUE
        return {
            "pid": os.getpid(),
            "identity": self.context.identity.to_mapping(),
            "request_id": request.id,
            "isolated": sys.flags.isolated,
            "blocked_modules": [name for name in sys.modules if blocked(name)],
            "blocked_imports": list(ATTEMPTS),
            "sdk": sdk,
            "credential_received": bool(secret),
            "credential_in_argv": bool(secret)
            and any(secret in value for value in sys.argv),
            "credential_in_env": bool(secret)
            and any(secret in value for value in os.environ.values()),
        }

    async def reverse(self, params, _request):
        await self.context.peer.notify("fixture.notice", params)
        return await self.context.peer.call(
            "fixture.host",
            self.context.identity.to_mapping(),
        )

    async def commit(self, _params, request):
        with Path(MARKER).open("a") as ledger:
            ledger.write(json.dumps({"request_id": request.id}) + "\n")
        await asyncio.Event().wait()

    async def slow(self, _params, request):
        Path(MARKER + ".slow").write_text(str(request.id))
        await asyncio.Event().wait()

    async def crash(self, _params, _request):
        os._exit(23)

    async def stale(self, _params, _request):
        identity = self.context.identity.to_mapping()
        identity["generation"] += 10
        await self.context.peer.notify(
            "execution.state",
            {**identity, "component_state": "failed"},
        )
        return {"sent": True}
