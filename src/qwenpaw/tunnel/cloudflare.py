# -*- coding: utf-8 -*-
"""Cloudflare Quick Tunnel driver.

Runs ``cloudflared tunnel --url http://localhost:<port>`` and exposes
the generated ``*.trycloudflare.com`` URL.
"""
from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from .binary_manager import BinaryManager

logger = logging.getLogger(__name__)

# Pattern to extract the public URL from cloudflared output.
_URL_RE = re.compile(r"https://[a-zA-Z0-9\-]+\.trycloudflare\.com")


@dataclass
class TunnelInfo:
    """Information about a running Cloudflare Quick Tunnel."""

    public_url: str  # "https://abc123.trycloudflare.com"
    public_wss_url: str  # "wss://abc123.trycloudflare.com"
    started_at: datetime
    pid: Optional[int] = None


class CloudflareTunnelDriver:
    """Manage a Cloudflare Quick Tunnel subprocess.

    Usage::

        driver = CloudflareTunnelDriver()
        info = await driver.start(8088)
        print(info.public_url)
        ...
        await driver.stop()
    """

    def __init__(self, binary_manager: BinaryManager | None = None) -> None:
        self._binary_mgr = binary_manager or BinaryManager()
        self._process: Optional[asyncio.subprocess.Process] = None
        self._info: Optional[TunnelInfo] = None
        self._monitor_task: Optional[asyncio.Task] = None

    async def start(self, local_port: int) -> TunnelInfo:
        """Start the tunnel and return connection info.

        Blocks until the public URL is detected in cloudflared output
        (typically 2-5 seconds).
        """
        if self._process and self._process.returncode is None:
            await self.stop()

        binary = await self._binary_mgr.get_binary_path()

        logger.info(
            "Starting cloudflared tunnel -> http://localhost:%d",
            local_port,
        )

        self._process = await asyncio.create_subprocess_exec(
            binary,
            "tunnel",
            "--url",
            f"http://localhost:{local_port}",
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
        )

        url = await self._wait_for_url(timeout=30)
        if not url:
            await self.stop()
            raise RuntimeError(
                "cloudflared did not produce a tunnel URL within 30 seconds",
            )

        self._info = TunnelInfo(
            public_url=url,
            public_wss_url=url.replace("https://", "wss://"),
            started_at=datetime.now(timezone.utc),
            pid=self._process.pid,
        )
        logger.info("Tunnel ready: %s (pid=%s)", url, self._process.pid)

        self._monitor_task = asyncio.create_task(
            self._monitor(),
            name="tunnel_monitor",
        )

        return self._info

    async def stop(self) -> None:
        """Terminate the tunnel subprocess."""
        if self._monitor_task and not self._monitor_task.done():
            self._monitor_task.cancel()
            try:
                await self._monitor_task
            except asyncio.CancelledError:
                pass
            self._monitor_task = None

        if self._process and self._process.returncode is None:
            logger.info("Stopping cloudflared (pid=%s)", self._process.pid)
            self._process.terminate()
            try:
                await asyncio.wait_for(self._process.wait(), timeout=5)
            except asyncio.TimeoutError:
                self._process.kill()
                await self._process.wait()
        self._process = None
        self._info = None

    async def health_check(self) -> bool:
        """Return True if the tunnel process is running."""
        return self._process is not None and self._process.returncode is None

    def get_public_url(self) -> str | None:
        """Return the current public URL, or None if not running."""
        return self._info.public_url if self._info else None

    def get_info(self) -> TunnelInfo | None:
        """Return the current TunnelInfo, or None if not running."""
        return self._info

    async def _wait_for_url(self, timeout: float = 30) -> str | None:
        """Read cloudflared stderr until the public URL appears."""
        if not self._process or not self._process.stderr:
            return None

        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout
        while loop.time() < deadline:
            try:
                line = await asyncio.wait_for(
                    self._process.stderr.readline(),
                    timeout=max(0.1, deadline - loop.time()),
                )
            except asyncio.TimeoutError:
                if loop.time() >= deadline:
                    break
                continue
            if not line:
                if self._process.returncode is not None:
                    break
                continue
            text = line.decode("utf-8", errors="replace").strip()
            logger.debug("cloudflared: %s", text)
            match = _URL_RE.search(text)
            if match:
                return match.group(0)
        return None

    async def _drain_stderr(self) -> None:
        """Read and discard stderr to prevent pipe buffer from filling."""
        if not self._process or not self._process.stderr:
            return
        while True:
            line = await self._process.stderr.readline()
            if not line:
                break
            logger.debug(
                "cloudflared: %s",
                line.decode("utf-8", errors="replace").strip(),
            )

    async def _monitor(self) -> None:
        """Drain stderr and log unexpected exit without auto-restart."""
        # Keep reading stderr so the pipe buffer doesn't fill and
        # block cloudflared.  _drain_stderr returns when the process
        # closes its stderr (i.e. exits).
        await self._drain_stderr()

        if not self._process:
            return

        try:
            await self._process.wait()
        except asyncio.CancelledError:
            return

        rc = self._process.returncode
        logger.warning(
            "cloudflared exited with code %s; not restarting Quick Tunnel "
            "automatically because a new public URL would be issued.",
            rc,
        )

        # Clear tunnel info so callers know the tunnel is no longer available.
        self._info = None
        return
