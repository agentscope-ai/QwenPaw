# -*- coding: utf-8 -*-
import asyncio
from qwenpaw.browser.errors import BrowserError, ErrorCategory


class FakeCdpTransport:
    def __init__(self, results=None, hang=False):
        self.results = results or {}
        self.hang = hang
        self.calls = []
        self.sinks = []

    async def connect(self, url):
        self.url = url
        self.connected_url = url

    async def close(self):
        pass

    async def send(self, method, params, *, session_id=None, timeout=None):
        self.calls.append((method, dict(params), session_id))
        if self.hang:
            await asyncio.sleep(timeout or 0.01)
            raise BrowserError(
                category=ErrorCategory.RETRYABLE,
                suggested_action="retry",
                reason="timeout",
            )
        return self.results.get(method, {})

    def subscribe(self, sink):
        self.sinks.append(sink)
        return lambda: self.sinks.remove(sink)

    def emit(self, msg):
        for sink in self.sinks:
            sink(msg)
