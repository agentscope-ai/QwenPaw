# -*- coding: utf-8 -*-
"""Unit tests for desktop backend port persistence helpers.

Complements ``test_port.py`` (socket construction failure) by covering
the port-file round trip, the bind/reuse logic, and the env-var fixed
port handling in ``get_stable_port``.
"""
# pylint: disable=protected-access
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from qwenpaw.utils import port as port_mod


# ---------------------------------------------------------------------------
# read_last_port
# ---------------------------------------------------------------------------


class TestReadLastPort:
    def test_missing_file_returns_none(self, tmp_path):
        assert port_mod.read_last_port(tmp_path / "nope") is None

    def test_valid_port(self, tmp_path):
        path = tmp_path / "port"
        path.write_text("8123\n", encoding="utf-8")
        assert port_mod.read_last_port(path) == 8123

    def test_non_integer_returns_none(self, tmp_path):
        path = tmp_path / "port"
        path.write_text("not-a-number", encoding="utf-8")
        assert port_mod.read_last_port(path) is None

    @pytest.mark.parametrize("value", ["80", "70000", "-1"])
    def test_out_of_range_returns_none(self, tmp_path, value):
        path = tmp_path / "port"
        path.write_text(value, encoding="utf-8")
        assert port_mod.read_last_port(path) is None

    def test_accepts_string_path(self, tmp_path):
        path = tmp_path / "port"
        path.write_text("9999", encoding="utf-8")
        assert port_mod.read_last_port(str(path)) == 9999


# ---------------------------------------------------------------------------
# write_port_file
# ---------------------------------------------------------------------------


class TestWritePortFile:
    def test_writes_port_atomically(self, tmp_path):
        path = tmp_path / "nested" / "port"
        port_mod.write_port_file(path, 8080)
        assert path.read_text(encoding="utf-8") == "8080"
        # No leftover temp files.
        assert list(path.parent.iterdir()) == [path]

    def test_failure_is_swallowed(self, tmp_path):
        path = tmp_path / "port"
        with patch.object(Path, "write_text", side_effect=OSError("full")):
            # Must not raise.
            port_mod.write_port_file(path, 8080)
        assert not path.exists()


# ---------------------------------------------------------------------------
# try_bind_port / find_free_port
# ---------------------------------------------------------------------------


class TestBindAndFindPort:
    def test_bind_success_returns_listening_socket(self):
        free = port_mod.find_free_port()
        sock = port_mod.try_bind_port("127.0.0.1", free)
        assert sock is not None
        sock.close()

    def test_bind_occupied_port_returns_none(self):
        holder = port_mod.try_bind_port("127.0.0.1", 0)
        assert holder is not None
        occupied = holder.getsockname()[1]
        try:
            assert port_mod.try_bind_port("127.0.0.1", occupied) is None
        finally:
            holder.close()

    def test_find_free_port_returns_usable_port(self):
        free = port_mod.find_free_port()
        assert 1024 <= free <= 65535


# ---------------------------------------------------------------------------
# get_stable_port
# ---------------------------------------------------------------------------


class TestGetStablePort:
    def test_env_var_port_wins(self, tmp_path):
        port_file = tmp_path / "port"
        free = port_mod.find_free_port()
        with patch.object(port_mod, "QWENPAW_DESKTOP_PORT", str(free)):
            port, sock = port_mod.get_stable_port(port_file)
        try:
            assert port == free
            assert sock is not None
            # Env-var port is not persisted.
            assert not port_file.exists()
        finally:
            if sock is not None:
                sock.close()

    def test_env_var_invalid_falls_back(self, tmp_path):
        port_file = tmp_path / "port"
        with patch.object(port_mod, "QWENPAW_DESKTOP_PORT", "not-int"):
            port, sock = port_mod.get_stable_port(port_file)
        if sock is not None:
            sock.close()
        assert 1024 <= port <= 65535
        # Fallback persists the chosen port.
        assert port_file.read_text(encoding="utf-8") == str(port)

    def test_env_var_out_of_range_falls_back(self, tmp_path):
        port_file = tmp_path / "port"
        with patch.object(port_mod, "QWENPAW_DESKTOP_PORT", "99"):
            port, sock = port_mod.get_stable_port(port_file)
        if sock is not None:
            sock.close()
        assert port != 99

    def test_env_var_unavailable_falls_back(self, tmp_path):
        holder = port_mod.try_bind_port("127.0.0.1", 0)
        assert holder is not None
        occupied = holder.getsockname()[1]
        try:
            with patch.object(
                port_mod,
                "QWENPAW_DESKTOP_PORT",
                str(occupied),
            ):
                port, sock = port_mod.get_stable_port(tmp_path / "port")
            if sock is not None:
                sock.close()
            assert port != occupied
        finally:
            holder.close()

    def test_reuses_recorded_port(self, tmp_path):
        port_file = tmp_path / "port"
        recorded = port_mod.find_free_port()
        port_file.write_text(str(recorded), encoding="utf-8")

        port, sock = port_mod.get_stable_port(port_file)

        try:
            assert port == recorded
            assert sock is not None
        finally:
            if sock is not None:
                sock.close()

    def test_unavailable_recorded_port_falls_back(self, tmp_path):
        holder = port_mod.try_bind_port("127.0.0.1", 0)
        assert holder is not None
        occupied = holder.getsockname()[1]
        port_file = tmp_path / "port"
        port_file.write_text(str(occupied), encoding="utf-8")
        try:
            port, sock = port_mod.get_stable_port(port_file)
            if sock is not None:
                sock.close()
            assert port != occupied
            # New port persisted over the stale one.
            assert port_file.read_text(encoding="utf-8") == str(port)
        finally:
            holder.close()

    def test_no_port_file_allocates_and_persists(self, tmp_path):
        port_file = tmp_path / "port"
        port, sock = port_mod.get_stable_port(port_file)
        if sock is not None:
            sock.close()
        assert sock is None
        assert 1024 <= port <= 65535
        assert port_file.read_text(encoding="utf-8") == str(port)
