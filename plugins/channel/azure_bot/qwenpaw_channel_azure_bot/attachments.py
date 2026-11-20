# -*- coding: utf-8 -*-
"""Public attachment connections and narrowly scoped Bot credentials."""

import ipaddress
import socket
from urllib.parse import urlsplit

import aiohttp
from yarl import URL


# These are Connector attachment endpoints, not tenant-hosted Azure domains.
_TOKEN_HOSTS = {
    "api.botframework.com",
    "smba.trafficmanager.net",
    "botapi.skype.com",
}


def _public_address(host):
    address = ipaddress.ip_address(host)
    if (
        not address.is_global
        or address.is_multicast
        or address.is_reserved
        or getattr(address, "is_site_local", False)
        or getattr(address, "ipv4_mapped", None)
        or getattr(address, "sixtofour", None)
        or getattr(address, "teredo", None)
        or (
            address.version == 6
            and (
                address in ipaddress.ip_network("64:ff9b::/96")
                or address in ipaddress.ip_network("64:ff9b:1::/48")
            )
        )
    ):
        raise ValueError("AZURE_ATTACHMENT_URL_UNSAFE")


def attachment_url(value):
    """Validate the same normalized URL that aiohttp will actually request."""
    if not isinstance(value, str) or any(
        ord(character) <= 32 or ord(character) == 127 or character == "\\"
        for character in value
    ):
        raise ValueError("AZURE_ATTACHMENT_URL_UNSAFE")
    url = URL(value)
    host = url.raw_host
    if (
        url.scheme != "https"
        or not host
        or "@" in urlsplit(value).netloc
        or url.user is not None
        or url.password is not None
        or url.port != 443
        or url.fragment
        or "%" in host
        or host.rstrip(".") == "localhost"
        or host.rstrip(".").endswith((".localhost", ".local", ".internal"))
    ):
        raise ValueError("AZURE_ATTACHMENT_URL_UNSAFE")
    try:
        ipaddress.ip_address(host)
    except ValueError:
        # Older aiohttp connectors bypass the resolver for padded IPv4 forms
        # that ipaddress rejects but the OS can interpret as private addresses.
        if ":" in host or all(c in "0123456789." for c in host):
            raise ValueError("AZURE_ATTACHMENT_URL_UNSAFE")
        # The connector's resolver checks every DNS answer for other names.
    else:
        _public_address(host)
    return url


def attachment_uses_token(url, service_url):
    if url.raw_host in _TOKEN_HOSTS:
        return True
    try:
        # service_url comes from the authenticated activity's signed claim.
        return url.origin() == attachment_url(service_url).origin()
    except ValueError:
        return False


class PublicAttachmentResolver(aiohttp.abc.AbstractResolver):
    """Return only checked numeric addresses to the actual TCP connector."""

    def __init__(self, resolver=None):
        self.resolver = resolver or aiohttp.resolver.DefaultResolver()

    async def resolve(self, host, port=0, family=socket.AF_INET):
        records = await self.resolver.resolve(host, port, family=family)
        if not records:
            raise OSError("AZURE_ATTACHMENT_DNS_EMPTY")
        try:
            for record in records:
                _public_address(record["host"])
        except ValueError as exc:
            raise OSError("AZURE_ATTACHMENT_URL_UNSAFE") from exc
        # Numeric flags prevent a second DNS lookup after validation. Keep the
        # original request hostname untouched for certificate checks and SNI.
        return [
            {
                **record,
                "hostname": host,
                "port": port,
                "flags": socket.AI_NUMERICHOST | socket.AI_NUMERICSERV,
            }
            for record in records
        ]

    async def close(self):
        await self.resolver.close()
