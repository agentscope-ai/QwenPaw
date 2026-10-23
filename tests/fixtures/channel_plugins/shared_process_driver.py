# -*- coding: utf-8 -*-
"""Small external-platform boundary; production IPC and lifecycle stay real."""

import asyncio
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import threading

MODE = globals().get("MODE", "normal")
MARKER = globals().get("MARKER", "")


def descendant():
    """Use a real inherited process group, including ignored TERM."""
    ready = Path(MARKER + ".child-ready")
    ready.unlink(missing_ok=True)
    terminated = Path(MARKER + ".child-term")
    terminated.unlink(missing_ok=True)
    child = subprocess.Popen(  # pylint: disable=consider-using-with
        [
            sys.executable,
            "-I",
            "-c",
            "import pathlib,signal,sys,threading; "
            "signal.signal(signal.SIGTERM,"
            "lambda *_: pathlib.Path(sys.argv[2]).touch()); "
            "pathlib.Path(sys.argv[1]).touch(); "
            "threading.Event().wait()",
            str(ready),
            str(terminated),
        ],
    )
    for _ in range(400):
        if ready.exists():
            return child
        threading.Event().wait(0.005)
    raise RuntimeError("External fixture child did not initialize")


# The harness prefixes MODE and MARKER before copying this fixture.
if MODE == "import_hang":
    _child = descendant()
    Path(MARKER + ".child").write_text(str(_child.pid), encoding="utf-8")
    Path(MARKER).write_text(str(os.getpid()), encoding="utf-8")
    threading.Event().wait()


class Driver:
    """Represent only controllable external platform behavior."""

    def __init__(self):
        self.context = None
        self.config = {}
        self.child = None
        self.started = asyncio.Event()

    def bind(self, context):
        """Register generic RPC probes through the public Driver context."""
        self.context = context
        for name in ("probe", "crash", "commit", "stale", "slow", "reverse"):
            context.peer.register_method(
                f"fixture.{name}",
                getattr(self, name),
            )
        if MODE in {"descendant", "stop_hang"}:
            self.child = descendant()
            Path(MARKER + ".child").write_text(
                str(self.child.pid),
                encoding="utf-8",
            )
            Path(MARKER).write_text(str(self.child.pid), encoding="utf-8")
        if MODE == "stop_hang":
            signal.signal(signal.SIGTERM, signal.SIG_IGN)
        if MODE == "flood":
            chunk = b"external-platform-log " * 4096
            for _ in range(40):
                os.write(1, chunk)
                os.write(2, chunk)

    async def start(self, config):
        """Connection state belongs to the fake external platform."""
        self.config = config
        self.started.set()
        if MODE == "connect_hang":
            self.child = descendant()
            Path(MARKER + ".child").write_text(
                str(self.child.pid),
                encoding="utf-8",
            )
            Path(MARKER).write_text(str(os.getpid()), encoding="utf-8")
            threading.Event().wait()
        if MODE == "secret_failure":
            print(config["credential"], file=sys.stderr, flush=True)
            raise RuntimeError(config["credential"])
        await self.context.set_platform_state("connected")

    async def stop(self):
        """A stalled external shutdown requires real escalation."""
        if MODE == "stop_hang":
            threading.Event().wait()

    async def probe(self, _params, request):
        """Observe child interpreter and identity without leaking config."""
        await self.started.wait()
        site = None
        if MODE == "shared_site":
            import b2_shared_sdk

            site = b2_shared_sdk.VALUE
        credential = self.config.get("credential", "")
        return {
            "pid": os.getpid(),
            "identity": self.context.identity.to_mapping(),
            "request_id": request.id,
            "isolated": sys.flags.isolated,
            "site": site,
            "credential_received": bool(credential),
            "credential_in_argv": bool(credential)
            and any(credential in arg for arg in sys.argv),
            "credential_in_env": bool(credential)
            and any(credential in value for value in os.environ.values()),
        }

    async def crash(self, _params, _request):
        """Abrupt platform failure drops a real IPC response."""
        os._exit(23)

    async def commit(self, _params, request):
        """Commit once before losing the reply; automatic replay is unsafe."""
        with Path(MARKER).open("a", encoding="utf-8") as ledger:
            ledger.write(json.dumps({"request_id": request.id}) + "\n")
        await asyncio.Event().wait()

    async def slow(self, _params, _request):
        """Keep a request admitted long enough to cancel it."""
        await asyncio.Event().wait()

    async def reverse(self, _params, _request):
        """Call a parent handler through real bidirectional IPC."""
        return await self.context.peer.call(
            "fixture.host",
            self.context.identity.to_mapping(),
        )

    async def stale(self, _params, _request):
        """A late control notification cannot change a newer generation."""
        identity = self.context.identity.to_mapping()
        identity["generation"] += 10
        await self.context.peer.notify(
            "shared.state",
            {**identity, "platform_state": "failed"},
        )
        return {"sent": True}
