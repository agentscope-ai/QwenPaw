# -*- coding: utf-8 -*-
"""Shared helpers for IP address and CIDR allowlists."""

from __future__ import annotations

import ipaddress
from typing import Iterable

IPNetwork = ipaddress.IPv4Network | ipaddress.IPv6Network


def normalize_ip_or_network(value: str) -> str:
    """Validate and canonicalize an IP address or CIDR network.

    Literal addresses remain literals for backwards-compatible config output.
    CIDRs must already use the network address implied by their prefix.
    """
    value = value.strip()
    if "/" not in value:
        return str(ipaddress.ip_address(value))
    return str(ipaddress.ip_network(value, strict=True))


def normalize_ip_network_entries(
    entries: Iterable[str],
) -> tuple[list[str], list[str]]:
    """Normalize, remove empty/duplicate entries, and collect invalid ones."""
    normalized: list[str] = []
    invalid: list[str] = []
    seen: set[str] = set()

    for raw_entry in entries:
        entry = raw_entry.strip()
        if not entry:
            continue
        try:
            canonical = normalize_ip_or_network(entry)
        except ValueError:
            invalid.append(entry)
            continue
        if canonical not in seen:
            seen.add(canonical)
            normalized.append(canonical)

    return normalized, invalid


def parse_ip_networks(entries: Iterable[str]) -> list[IPNetwork]:
    """Parse valid IP/CIDR entries into networks, ignoring invalid entries."""
    networks: list[IPNetwork] = []
    for entry in entries:
        try:
            networks.append(ipaddress.ip_network(entry, strict=True))
        except ValueError:
            continue
    return networks


def ip_in_networks(ip_value: str, networks: Iterable[IPNetwork]) -> bool:
    """Return whether an IP address belongs to any same-family network."""
    try:
        address = ipaddress.ip_address(ip_value)
    except ValueError:
        return False
    return any(
        address.version == network.version and address in network
        for network in networks
    )
