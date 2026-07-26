# -*- coding: utf-8 -*-
"""Built-in SIP registrar for zero-config Dev mode.

A minimal SIP registrar + proxy (pure Python, zero dependencies)
that lets softphones register and call each other without an
external SIP server like Asterisk or FreeSWITCH.

Usage (embedded)::

    registrar = MiniRegistrar(bind="127.0.0.1", port=5060)
    await registrar.start()   # non-blocking
    ...
    await registrar.stop()

Adapted from ``tests/mini_sip_server.py``.
"""
from __future__ import annotations

import asyncio
import logging
import re
import time
from typing import Optional, cast

logger = logging.getLogger(__name__)

_DEFAULT_REGISTER_EXPIRES_S = 3600
_MAX_REGISTER_EXPIRES_S = 24 * 60 * 60
_TRANSACTION_TTL_S = 5 * 60


def _user(uri: str) -> str:
    m = re.search(r"sip:([^@]+)@", uri)
    return m.group(1) if m else ""


def _hdr(msg: str, name: str) -> str:
    for line in msg.split("\r\n"):
        if line.lower().startswith(name.lower() + ":"):
            return line.split(":", 1)[1].strip()
    return ""


def _method_and_uri(msg: str) -> tuple[str, str]:
    first = msg.split("\r\n", 1)[0]
    parts = first.split()
    if len(parts) >= 2 and not first.startswith("SIP/"):
        return parts[0], parts[1]
    return "", ""


def _register_expires(msg: str) -> int:
    """Return a safe REGISTER lifetime; malformed values use the default."""
    contact = _hdr(msg, "Contact")
    contact_match = re.search(
        r"(?:^|;)\s*expires\s*=\s*\"?(\d+)\"?",
        contact,
        flags=re.IGNORECASE,
    )
    raw = contact_match.group(1) if contact_match else _hdr(msg, "Expires")
    try:
        expires = int(raw) if raw else _DEFAULT_REGISTER_EXPIRES_S
    except ValueError:
        return _DEFAULT_REGISTER_EXPIRES_S
    return max(0, min(expires, _MAX_REGISTER_EXPIRES_S))


def _is_final_response(msg: str) -> bool:
    """Whether *msg* is a SIP response that terminates a transaction."""
    first_line = msg.split("\r\n", 1)[0]
    parts = first_line.split()
    if len(parts) < 2 or not first_line.startswith("SIP/"):
        return False
    try:
        return int(parts[1]) >= 200
    except ValueError:
        return False


def _build_200(msg: str) -> str:
    lines = ["SIP/2.0 200 OK"]
    for h in ("Via", "From", "To", "Call-ID", "CSeq"):
        v = _hdr(msg, h)
        if v:
            lines.append(f"{h}: {v}")
    lines += ["Content-Length: 0", "", ""]
    return "\r\n".join(lines)


class _SIPProxy(asyncio.DatagramProtocol):
    def __init__(self) -> None:
        self.transport: Optional[asyncio.DatagramTransport] = None
        self.registry: dict[str, tuple[tuple[str, int], float]] = {}
        self.transactions: dict[str, tuple[tuple[str, int], float]] = {}

    def connection_made(self, transport: asyncio.BaseTransport) -> None:
        self.transport = cast(asyncio.DatagramTransport, transport)

    def datagram_received(
        self,
        data: bytes,
        addr: tuple[str, int],
    ) -> None:
        try:
            msg = data.decode("utf-8", errors="replace")
        except Exception:
            return

        self._prune_expired()
        method, req_uri = _method_and_uri(msg)
        if method == "REGISTER":
            self._register(msg, addr)
        elif method:
            self._forward_request(method, req_uri, msg, addr)
        elif msg.startswith("SIP/2.0"):
            self._forward_response(msg, addr)

    def _register(self, msg: str, addr: tuple[str, int]) -> None:
        user = _user(_hdr(msg, "To"))
        expires = _register_expires(msg)
        if not user:
            return
        if expires == 0:
            registration = self.registry.get(user)
            if registration and registration[0] == addr:
                self.registry.pop(user, None)
                logger.debug("SIP unregistered %s", user)
            elif registration:
                logger.debug(
                    "Ignoring stale SIP unregister for %s from %s",
                    user,
                    addr,
                )
        else:
            self.registry[user] = (addr, time.monotonic() + expires)
        logger.debug("SIP REG %s -> %s", user, addr)
        self.transport.sendto(_build_200(msg).encode(), addr)

    def _forward_request(
        self,
        method: str,
        uri: str,
        msg: str,
        addr: tuple[str, int],
    ) -> None:
        target = _user(uri)
        registration = self.registry.get(target)
        if not registration:
            if method == "INVITE":
                resp = msg.replace(
                    msg.split("\r\n", 1)[0],
                    "SIP/2.0 404 Not Found",
                    1,
                )
                self.transport.sendto(resp.encode(), addr)
            return
        dest, _expires_at = registration

        call_id = _hdr(msg, "Call-ID")
        if call_id and (
            method == "INVITE" or call_id not in self.transactions
        ):
            self.transactions[call_id] = (
                addr,
                time.monotonic() + _TRANSACTION_TTL_S,
            )

        self.transport.sendto(msg.encode(), dest)

    def _forward_response(
        self,
        msg: str,
        addr: tuple[str, int],
    ) -> None:
        call_id = _hdr(msg, "Call-ID")
        transaction = self.transactions.get(call_id)
        dest = transaction[0] if transaction else None
        if dest and dest != addr:
            self.transport.sendto(msg.encode(), dest)
            return
        for _user_name, (uaddr, _expires_at) in self.registry.items():
            if uaddr != addr:
                self.transport.sendto(msg.encode(), uaddr)
                break

    def _prune_expired(self) -> None:
        now = time.monotonic()
        for user, (_addr, expires_at) in list(self.registry.items()):
            if expires_at <= now:
                self.registry.pop(user, None)
        for call_id, (_addr, expires_at) in list(self.transactions.items()):
            if expires_at <= now:
                self.transactions.pop(call_id, None)


class MiniRegistrar:
    """Embeddable SIP registrar with start/stop lifecycle."""

    def __init__(
        self,
        bind: str = "127.0.0.1",
        port: int = 5060,
    ) -> None:
        self._bind = bind
        self._port = port
        self._transport: Optional[asyncio.DatagramTransport] = None

    async def start(self) -> None:
        loop = asyncio.get_running_loop()
        self._transport, _ = await loop.create_datagram_endpoint(
            _SIPProxy,
            local_addr=(self._bind, self._port),
        )
        logger.info(
            "Built-in SIP registrar started on %s:%d",
            self._bind,
            self._port,
        )

    async def stop(self) -> None:
        if self._transport:
            self._transport.close()
            self._transport = None
            logger.info("Built-in SIP registrar stopped")
