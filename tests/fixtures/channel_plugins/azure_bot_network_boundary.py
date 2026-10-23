"""Offline public DNS and socket boundary; attachment policy stays real."""

import asyncio
import socket

import aiohttp

PUBLIC_IP = "93.184.216.34"
KNOWN_HOSTS = {
    "login.botframework.com",
    "connector.test",
    "media.test",
    "api.botframework.com",
    "smba.trafficmanager.net",
    "botapi.skype.com",
    "api.botframework.com.attacker.test",
    "tenant.blob.core.windows.net",
    "mismatch.test",
}


def install_attachment_network(monkeypatch, boundary):
    """Map only validated public socket destinations onto a real TLS server."""
    boundary.dns_answers = {}
    boundary.dns_calls = []
    boundary.connections = []

    class ExternalDNS(aiohttp.abc.AbstractResolver):
        def __init__(self):
            self.closed = False

        async def resolve(self, host, port=0, family=socket.AF_INET):
            assert host in KNOWN_HOSTS, host
            boundary.dns_calls.append(host)
            configured = boundary.dns_answers.get(host, [PUBLIC_IP])
            addresses = configured() if callable(configured) else configured
            return [
                {
                    "hostname": host,
                    "host": address,
                    "port": port,
                    "family": socket.AF_INET6
                    if ":" in address
                    else socket.AF_INET,
                    "proto": socket.IPPROTO_TCP,
                    "flags": 0,
                }
                for address in addresses
            ]

        async def close(self):
            self.closed = True

    monkeypatch.setattr(aiohttp.resolver, "DefaultResolver", ExternalDNS)
    loop = asyncio.get_running_loop()
    original_connect = loop.sock_connect

    async def connect(sock, address):
        host, port = address[:2]
        if host == PUBLIC_IP:
            assert port == 443
            boundary.connections.append((host, port))
            return await original_connect(sock, ("127.0.0.1", boundary.port))
        # The fixture's own listeners and trusted auth/outbound sessions use
        # local sockets. Security tests independently assert zero new connects.
        assert host == "127.0.0.1", address
        return await original_connect(sock, address)

    monkeypatch.setattr(loop, "sock_connect", connect)
