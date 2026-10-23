# -*- coding: utf-8 -*-
"""Deterministic platform boundary for real C5 worker transactions."""

import asyncio
import json
import os
from pathlib import Path
import time

NETWORK = globals().get("NETWORK", "")
VERSION = globals().get("VERSION", "")


def record(kind, **values):
    """Persist child evidence outside the mutable plugin directory."""
    with Path(NETWORK).open("a", encoding="utf-8") as stream:
        stream.write(
            json.dumps(
                {
                    "kind": kind,
                    "pid": os.getpid(),
                    "version": VERSION,
                    "time": time.monotonic_ns(),
                    **values,
                },
            )
            + "\n",
        )


record("imported", source=__file__)
if VERSION == "2.0.0":
    while Path(NETWORK + ".probe-block").exists():
        time.sleep(0.01)


class Driver:
    """Only the external connection is fake; worker and RPC remain real."""

    def __init__(self):
        self.context = None
        self.config = {}
        record("constructed")

    def bind(self, context):
        self.context = context
        context.peer.register_method("fixture.identity", self.identity)

    async def start(self, config):
        self.config = config
        record("connecting", config=config)
        if (
            VERSION == "2.0.0"
            and config.get("app_id", config.get("client_id")) == "fail-new"
        ):
            record("failed-start")
            raise RuntimeError("controlled second-workspace startup failure")
        record("connected", config=config)
        await self.context.set_platform_state("connected")

    async def stop(self):
        record("stopped")
        while Path(NETWORK + ".hold-all").exists() or (
            VERSION == "2.0.0" and Path(NETWORK + ".hold-new").exists()
        ):
            # A blocking vendor close survives cancellation on peer shutdown.
            time.sleep(0.01)

    async def identity(self, _params, _request):
        await asyncio.sleep(0)
        return {
            "pid": os.getpid(),
            "version": VERSION,
            "source": __file__,
            "config": self.config,
            "identity": self.context.identity.to_mapping(),
        }
