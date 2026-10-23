# -*- coding: utf-8 -*-
"""Probe the production protocol handle and ordinary output routing."""

from __future__ import annotations

import asyncio
import importlib
import json
import os

from qwenpaw.plugins.execution.framing import FramedTransport
from qwenpaw.plugins.execution.bootstrap import (
    _capture_protocol_output,
    _open_protocol_transport,
    _redirect_ordinary_output,
)


async def _run() -> None:
    """Send one frame after production-order stdout isolation."""
    protocol_handle = _capture_protocol_output()
    _redirect_ordinary_output()
    importlib.import_module("fake_feishu_sdk")
    print("probe-print")
    os.write(1, b"probe-fd1\n")
    transport = await _open_protocol_transport(
        FramedTransport,
        protocol_handle,
    )
    try:
        message = json.dumps(
            {"probe": "ready"},
            separators=(",", ":"),
        )
        await transport.send(message)
    finally:
        await transport.aclose()


if __name__ == "__main__":
    asyncio.run(_run())
