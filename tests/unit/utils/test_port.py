# -*- coding: utf-8 -*-
# pylint: disable=protected-access
"""Tests for port persistence utilities."""
from __future__ import annotations

import socket

from qwenpaw.utils.port import (
    find_free_port,
    get_stable_port,
    read_last_port,
    try_bind_port,
    write_port_file,
)


class TestReadLastPort:
    """Tests for read_last_port()."""

    def test_returns_port_from_valid_file(self, tmp_path):
        port_file = tmp_path / "desktop_port"
        port_file.write_text("12345")

        assert read_last_port(port_file) == 12345

    def test_returns_none_when_file_missing(self, tmp_path):
        assert read_last_port(tmp_path / "nonexistent") is None

    def test_returns_none_for_non_integer(self, tmp_path):
        port_file = tmp_path / "desktop_port"
        port_file.write_text("not_a_number")

        assert read_last_port(port_file) is None

    def test_returns_none_for_port_below_range(self, tmp_path):
        port_file = tmp_path / "desktop_port"
        port_file.write_text("80")

        assert read_last_port(port_file) is None

    def test_returns_none_for_port_above_range(self, tmp_path):
        port_file = tmp_path / "desktop_port"
        port_file.write_text("70000")

        assert read_last_port(port_file) is None

    def test_handles_whitespace_and_newline(self, tmp_path):
        port_file = tmp_path / "desktop_port"
        port_file.write_text("  54321\n")

        assert read_last_port(port_file) == 54321

    def test_returns_none_for_empty_file(self, tmp_path):
        port_file = tmp_path / "desktop_port"
        port_file.write_text("")

        assert read_last_port(port_file) is None


class TestWritePortFile:
    """Tests for write_port_file()."""

    def test_writes_port_to_file(self, tmp_path):
        port_file = tmp_path / "desktop_port"
        write_port_file(port_file, 44444)

        assert port_file.read_text().strip() == "44444"

    def test_overwrites_existing_file(self, tmp_path):
        port_file = tmp_path / "desktop_port"
        write_port_file(port_file, 11111)
        write_port_file(port_file, 22222)

        assert port_file.read_text().strip() == "22222"

    def test_creates_parent_directory(self, tmp_path):
        port_file = tmp_path / "sub" / "dir" / "desktop_port"
        write_port_file(port_file, 33333)

        assert port_file.read_text().strip() == "33333"

    def test_does_not_raise_on_unwritable_path(self, tmp_path):
        # Non-existent deeply nested path under a file (not a dir)
        blocker = tmp_path / "blocker"
        blocker.write_text("I am a file")
        write_port_file(blocker / "sub" / "desktop_port", 33333)


class TestTryBindPort:
    """Tests for try_bind_port()."""

    def test_binds_to_available_port(self):
        sock = try_bind_port("127.0.0.1", 0)
        assert sock is not None
        assert sock.getsockname()[1] > 0
        sock.close()

    def test_returns_none_for_occupied_port(self):
        # Use SO_EXCLUSIVEADDRUSE on Windows to truly block
        occupied = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            occupied.setsockopt(
                socket.SOL_SOCKET,
                socket.SO_EXCLUSIVEADDRUSE,
                1,
            )
        occupied.bind(("127.0.0.1", 0))
        occupied.listen(1)
        port = occupied.getsockname()[1]

        try:
            assert try_bind_port("127.0.0.1", port) is None
        finally:
            occupied.close()

    def test_returned_socket_is_listening(self):
        sock = try_bind_port("127.0.0.1", 0)
        assert sock is not None
        port = sock.getsockname()[1]

        client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            client.connect(("127.0.0.1", port))
        finally:
            client.close()
            sock.close()


class TestFindFreePort:
    """Tests for find_free_port()."""

    def test_returns_valid_port(self):
        port = find_free_port()
        assert 1024 <= port <= 65535


class TestGetStablePort:
    """Tests for get_stable_port()."""

    def test_first_launch_allocates_and_persists(self, tmp_path):
        port_file = tmp_path / "desktop_port"

        port, sock = get_stable_port(port_file)

        assert 1024 <= port <= 65535
        assert port_file.exists()
        # sock is None for random-port fallback
        assert sock is None

    def test_second_launch_reuses_port_and_returns_socket(self, tmp_path):
        port_file = tmp_path / "desktop_port"

        first_port, _ = get_stable_port(port_file)
        second_port, sock = get_stable_port(port_file)

        assert second_port == first_port
        assert sock is not None
        sock.close()

    def test_falls_back_when_port_occupied(self, tmp_path):
        port_file = tmp_path / "desktop_port"

        first_port, _ = get_stable_port(port_file)

        # Occupy the port with SO_EXCLUSIVEADDRUSE
        blocker = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            blocker.setsockopt(
                socket.SOL_SOCKET,
                socket.SO_EXCLUSIVEADDRUSE,
                1,
            )
        blocker.bind(("127.0.0.1", first_port))
        blocker.listen(1)

        try:
            fallback_port, sock = get_stable_port(port_file)
            assert fallback_port != first_port
            assert 1024 <= fallback_port <= 65535
            assert sock is None  # random fallback
        finally:
            blocker.close()

    def test_invalid_port_file_falls_back(self, tmp_path):
        port_file = tmp_path / "desktop_port"
        port_file.write_text("garbage")

        port, _ = get_stable_port(port_file)

        assert 1024 <= port <= 65535

    def test_out_of_range_port_falls_back(self, tmp_path):
        port_file = tmp_path / "desktop_port"
        port_file.write_text("99999")

        port, _ = get_stable_port(port_file)

        assert 1024 <= port <= 65535
