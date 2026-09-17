# -*- coding: utf-8 -*-
# pylint: disable=protected-access
from __future__ import annotations

import hashlib
import stat
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

import qwenpaw.tunnel.binary_manager as bm_module
from qwenpaw.tunnel.binary_manager import BinaryManager, _download_file

# ---------------------------------------------------------------------------
# BinaryManager.get_binary_path — PATH lookup
# ---------------------------------------------------------------------------


async def test_get_binary_path_found_in_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("shutil.which", lambda _name: "/usr/bin/cloudflared")
    mgr = BinaryManager()
    result = await mgr.get_binary_path()
    assert result == "/usr/bin/cloudflared"


async def test_get_binary_path_found_local(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("shutil.which", lambda _name: None)
    monkeypatch.setattr("platform.system", lambda: "Linux")
    bin_file = tmp_path / "cloudflared"
    bin_file.write_bytes(b"binary")
    bin_file.chmod(bin_file.stat().st_mode | stat.S_IXUSR)

    mgr = BinaryManager(bin_dir=tmp_path)
    result = await mgr.get_binary_path()
    assert result == str(bin_file)


async def test_get_binary_path_triggers_download(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("shutil.which", lambda _name: None)
    mgr = BinaryManager(bin_dir=tmp_path)

    fake_download = AsyncMock(return_value=str(tmp_path / "cloudflared"))
    monkeypatch.setattr(mgr, "_download", fake_download)

    result = await mgr.get_binary_path()
    assert result == str(tmp_path / "cloudflared")
    fake_download.assert_awaited_once()


# ---------------------------------------------------------------------------
# BinaryManager._verify_checksum
# ---------------------------------------------------------------------------


def test_verify_checksum_success(tmp_path: Path) -> None:
    content = b"test binary content"
    filepath = tmp_path / "binary"
    filepath.write_bytes(content)

    expected = hashlib.sha256(content).hexdigest()
    BinaryManager._verify_checksum(str(filepath), expected)


def test_verify_checksum_mismatch_deletes(tmp_path: Path) -> None:
    filepath = tmp_path / "binary"
    filepath.write_bytes(b"content")

    with pytest.raises(RuntimeError, match="SHA256 mismatch"):
        BinaryManager._verify_checksum(str(filepath), "0" * 64)

    assert not filepath.exists()


# ---------------------------------------------------------------------------
# BinaryManager._download — unsupported platform
# ---------------------------------------------------------------------------


async def test_download_unsupported_platform(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(bm_module, "_platform_key", lambda: ("Haiku", "riscv"))
    mgr = BinaryManager(bin_dir=tmp_path)

    with pytest.raises(RuntimeError, match="No cloudflared download"):
        await mgr._download()


# ---------------------------------------------------------------------------
# _download_file — HTTP error mapping
# ---------------------------------------------------------------------------


async def test_download_file_timeout() -> None:
    import httpx

    class FakeStream:
        async def __aenter__(self):
            raise httpx.TimeoutException("timed out")

        async def __aexit__(self, *args):
            pass

    client = MagicMock()
    client.stream = MagicMock(return_value=FakeStream())

    with pytest.raises(RuntimeError, match="Timed out"):
        await _download_file(client, "https://example.com/file", "/tmp/out")


async def test_download_file_http_error() -> None:
    import httpx

    mock_response = MagicMock()
    mock_response.status_code = 404

    class FakeStream:
        async def __aenter__(self):
            raise httpx.HTTPStatusError(
                "Not Found",
                request=MagicMock(),
                response=mock_response,
            )

        async def __aexit__(self, *args):
            pass

    client = MagicMock()
    client.stream = MagicMock(return_value=FakeStream())

    with pytest.raises(RuntimeError, match="HTTP 404"):
        await _download_file(client, "https://example.com/file", "/tmp/out")


# ---------------------------------------------------------------------------
# _platform_key
# ---------------------------------------------------------------------------


def test_platform_key_returns_tuple(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("platform.system", lambda: "Linux")
    monkeypatch.setattr("platform.machine", lambda: "x86_64")
    from qwenpaw.tunnel.binary_manager import _platform_key

    key = _platform_key()
    assert key == ("Linux", "x86_64")
