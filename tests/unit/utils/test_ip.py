# -*- coding: utf-8 -*-
"""Tests for shared IP/CIDR allowlist helpers."""

from qwenpaw.utils.ip import normalize_ip_network_entries


def test_normalize_entries_handles_cidr_deduplication_and_invalid_values():
    normalized, invalid = normalize_ip_network_entries(
        [
            " ",
            " 192.168.1.0/24 ",
            "192.168.1.0/24",
            "fd00:0:0:0::/64",
            "192.168.1.42/24",
            "fd00::1234/64",
            "bad-ip-value",
            "fd00::/129",
        ],
    )
    assert normalized == ["192.168.1.0/24", "fd00::/64"]
    assert invalid == [
        "192.168.1.42/24",
        "fd00::1234/64",
        "bad-ip-value",
        "fd00::/129",
    ]
