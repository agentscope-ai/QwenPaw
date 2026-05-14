# -*- coding: utf-8 -*-
# pylint: disable=protected-access
from __future__ import annotations

import hashlib
from pathlib import Path

import httpx
import pytest

from qwenpaw.tunnel import binary_manager


class FakeResponse:
    def __init__(self, chunks: list[bytes]) -> None:
        self._chunks = chunks

    def raise_for_status(self) -> None:
        pass

    async def aiter_bytes(self, chunk_size: int):
        assert chunk_size == 1 << 16
        for chunk in self._chunks:
            yield chunk


class FailingResponse(FakeResponse):
    def __init__(self, status_code: int) -> None:
        super().__init__([])
        request = httpx.Request("GET", "https://example.test/cloudflared")
        self._response = httpx.Response(status_code, request=request)

    def raise_for_status(self) -> None:
        raise httpx.HTTPStatusError(
            "download failed",
            request=self._response.request,
            response=self._response,
        )


class FakeStream:
    def __init__(self, response: FakeResponse) -> None:
        self._response = response

    async def __aenter__(self) -> FakeResponse:
        return self._response

    async def __aexit__(self, *_exc_info: object) -> None:
        return None


class FakeClient:
    def __init__(self, response: FakeResponse) -> None:
        self._response = response
        self.calls: list[tuple[str, str, bool]] = []

    def stream(
        self,
        method: str,
        url: str,
        follow_redirects: bool,
    ) -> FakeStream:
        self.calls.append((method, url, follow_redirects))
        return FakeStream(self._response)


class DownloadingBinaryManager(binary_manager.BinaryManager):
    def __init__(self, bin_dir: Path, result: str) -> None:
        super().__init__(bin_dir)
        self.result = result
        self.downloads = 0

    async def _download(self) -> str:
        self.downloads += 1
        return self.result


async def test_download_file_streams_bytes_to_destination(
    tmp_path: Path,
) -> None:
    dest = tmp_path / "cloudflared"
    client = FakeClient(FakeResponse([b"cloud", b"flared"]))

    await binary_manager._download_file(
        client,  # type: ignore[arg-type]
        "https://example.test/cloudflared",
        str(dest),
    )

    assert dest.read_bytes() == b"cloudflared"
    assert client.calls == [("GET", "https://example.test/cloudflared", True)]


async def test_download_file_maps_http_status_errors(tmp_path: Path) -> None:
    dest = tmp_path / "cloudflared"
    client = FakeClient(FailingResponse(503))

    with pytest.raises(RuntimeError, match="HTTP 503 downloading"):
        await binary_manager._download_file(
            client,  # type: ignore[arg-type]
            "https://example.test/cloudflared",
            str(dest),
        )


async def test_get_binary_path_prefers_existing_path_binary(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    expected = str(tmp_path / "cloudflared")
    monkeypatch.setattr(binary_manager.shutil, "which", lambda _name: expected)
    manager = DownloadingBinaryManager(tmp_path, "downloaded")

    assert await manager.get_binary_path() == expected
    assert manager.downloads == 0


async def test_get_binary_path_uses_local_executable(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    local = tmp_path / "cloudflared"
    local.write_bytes(b"binary")
    local.chmod(0o755)
    monkeypatch.setattr(binary_manager.shutil, "which", lambda _name: None)
    monkeypatch.setattr(binary_manager.platform, "system", lambda: "Linux")
    manager = DownloadingBinaryManager(tmp_path, "downloaded")

    assert await manager.get_binary_path() == str(local)
    assert manager.downloads == 0


async def test_get_binary_path_downloads_when_no_binary_exists(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(binary_manager.shutil, "which", lambda _name: None)
    monkeypatch.setattr(binary_manager.platform, "system", lambda: "Windows")
    manager = DownloadingBinaryManager(tmp_path, "downloaded")

    assert await manager.get_binary_path() == "downloaded"
    assert manager.downloads == 1


def test_verify_checksum_accepts_expected_hash(tmp_path: Path) -> None:
    binary = tmp_path / "cloudflared"
    binary.write_bytes(b"qwenpaw")
    expected = hashlib.sha256(b"qwenpaw").hexdigest()

    binary_manager.BinaryManager._verify_checksum(str(binary), expected)

    assert binary.exists()


def test_verify_checksum_deletes_bad_download(tmp_path: Path) -> None:
    binary = tmp_path / "cloudflared"
    binary.write_bytes(b"bad")

    with pytest.raises(RuntimeError, match="SHA256 mismatch"):
        binary_manager.BinaryManager._verify_checksum(str(binary), "0" * 64)

    assert not binary.exists()


async def test_download_rejects_unsupported_platform(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        binary_manager,
        "_platform_key",
        lambda: ("Plan9", "riscv64"),
    )

    with pytest.raises(
        RuntimeError,
        match="No cloudflared download available",
    ):
        await binary_manager.BinaryManager(tmp_path)._download()
