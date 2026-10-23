# -*- coding: utf-8 -*-
"""Expose actual worker state through real IPC, with no resident helpers."""

import importlib.abc
import os
from pathlib import Path
import sys

BLOCKED = (
    "qwenpaw.app",
    "qwenpaw.agents",
    "agentscope",
    "agentscope_runtime",
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
    return any(name == part or name.startswith(part + ".") for part in BLOCKED)


class ImportGuard(importlib.abc.MetaPathFinder):
    # Match importlib's callback signature; both optional inputs are unused.
    # pylint: disable-next=unused-argument
    def find_spec(self, fullname, path=None, target=None):
        if blocked(fullname):
            ATTEMPTS.append(fullname)
            raise AssertionError(f"Worker imported {fullname}")


assert not any(blocked(name) for name in sys.modules)
sys.meta_path.insert(0, ImportGuard())
frame = sys._getframe()  # pylint: disable=protected-access
while frame is not None:
    packet = frame.f_locals.get("packet")
    if isinstance(packet, dict) and "dependency_versions" in packet:
        VERSIONS = dict(packet["dependency_versions"])
        break
    frame = frame.f_back
else:
    raise AssertionError("Runtime dependency versions unavailable")
del frame, packet


class Worker:
    def bind(self, context):
        self.context = context
        context.peer.register_method("fixture.report", self.report)

    # pylint: disable-next=unused-argument
    async def start(self, config):
        await self.context.set_state("ready")

    async def stop(self):
        pass

    # pylint: disable-next=unused-argument
    async def report(self, params, request):
        if params.get("sdk"):
            import shared_fixture_sdk

            sdk = shared_fixture_sdk.VALUE
        else:
            sdk = None
        if params.get("stdlib"):
            import colorsys

            standard = str(Path(colorsys.__file__).resolve())
        else:
            standard = None
        return {
            "pid": os.getpid(),
            "isolated": sys.flags.isolated,
            "versions": VERSIONS,
            "modules": sorted(sys.modules),
            "paths": list(sys.path),
            "sdk": sdk,
            "stdlib": standard,
            "blocked": ATTEMPTS,
        }
