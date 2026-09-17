# -*- coding: utf-8 -*-
"""Tests for desktop backend port allocation."""

from unittest.mock import patch

from qwenpaw.utils.port import try_bind_port


def test_try_bind_port_handles_socket_construction_error() -> None:
    with patch(
        "qwenpaw.utils.port.socket.socket",
        side_effect=OSError("file descriptor limit reached"),
    ):
        assert try_bind_port("127.0.0.1", 8088) is None
