# -*- coding: utf-8 -*-
"""Small external component used by the real generic worker supervisor."""

import asyncio
import os
from pathlib import Path
import signal
import subprocess
import sys
import threading


class Worker:
    def bind(self, context):
        self.context = context
        self.started = asyncio.Event()
        for name in ("probe", "echo", "reverse", "slow", "crash", "logs"):
            context.peer.register_method("sample." + name, getattr(self, name))

    async def start(self, config):
        self.config = config
        mode = config.get("mode")
        marker = Path(config["marker"])
        if mode == "blocked":
            marker.write_text(str(os.getpid()))
            threading.Event().wait()
        if mode == "tree":
            signal.signal(signal.SIGTERM, signal.SIG_IGN)
            ready = str(marker) + ".ready"
            child = subprocess.Popen(
                [
                    sys.executable,
                    "-I",
                    "-c",
                    "import pathlib,signal,sys,threading; "
                    "signal.signal(signal.SIGTERM,signal.SIG_IGN); "
                    "pathlib.Path(sys.argv[1]).touch(); "
                    "threading.Event().wait()",
                    ready,
                ],
            )
            while not Path(ready).exists():
                await asyncio.sleep(0.005)
            marker.write_text(str(child.pid))
        print("sample SDK connected", flush=True)
        print("sample SDK diagnostic", file=sys.stderr, flush=True)
        self.started.set()
        await self.context.set_state("ready")

    async def stop(self):
        if self.config.get("mode") == "tree":
            threading.Event().wait()

    async def probe(self, _params, _request):
        await self.started.wait()
        sdk = None
        if self.config.get("sdk"):
            import sample_shared_sdk

            sdk = sample_shared_sdk.VALUE
        return {
            "pid": os.getpid(),
            "identity": self.context.identity.to_mapping(),
            "isolated": sys.flags.isolated,
            "executable": sys.executable,
            "sdk": sdk,
            "source": __file__,
            "dependency_state": os.environ["QWENPAW_DEPENDENCY_STATE_DIR"],
        }

    async def echo(self, params, _request):
        return params

    async def logs(self, params, _request):
        data = params["text"].encode("utf-8")
        sys.stderr.buffer.write(data)
        sys.stderr.buffer.flush()
        return len(data)

    async def reverse(self, params, _request):
        await self.context.peer.notify("sample.notice", params)
        return await self.context.peer.call(
            "sample.host",
            self.context.identity.to_mapping(),
        )

    async def slow(self, _params, _request):
        Path(self.config["marker"] + ".pending").touch()
        await asyncio.Event().wait()

    async def crash(self, _params, _request):
        os._exit(23)
