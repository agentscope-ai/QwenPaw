# -*- coding: utf-8 -*-
"""Auto-download cloudflared binary if not in PATH."""
from __future__ import annotations

import hashlib
import logging
import os
import platform
import shutil
import stat
import tempfile
from pathlib import Path

import httpx

from ..constant import WORKING_DIR

logger = logging.getLogger(__name__)

_DOWNLOAD_TIMEOUT = 90  # seconds

_BIN_DIR = Path(f"{WORKING_DIR}/bin").expanduser()

# Pinned cloudflared version — update checksums when bumping.
_CLOUDFLARED_VERSION = "2026.2.0"
_BASE_URL = (
    "https://github.com/cloudflare/cloudflared/releases/"
    f"download/{_CLOUDFLARED_VERSION}"
)

# cloudflared release download URLs by (system, machine) pair.
_DOWNLOAD_URLS: dict[tuple[str, str], str] = {
    ("Darwin", "x86_64"): f"{_BASE_URL}/cloudflared-darwin-amd64.tgz",
    ("Darwin", "arm64"): f"{_BASE_URL}/cloudflared-darwin-arm64.tgz",
    ("Linux", "x86_64"): f"{_BASE_URL}/cloudflared-linux-amd64",
    ("Linux", "aarch64"): f"{_BASE_URL}/cloudflared-linux-arm64",
    ("Windows", "AMD64"): f"{_BASE_URL}/cloudflared-windows-amd64.exe",
}

# SHA256 checksums from the official release.
_SHA256_CHECKSUMS: dict[tuple[str, str], str] = {
    (
        "Darwin",
        "x86_64",
    ): "685688a260c324eb8d9c9434ca22f0ce4f504fd6acd0706787c4833de8d6eb17",
    (
        "Darwin",
        "arm64",
    ): "ba99c6f87320236b9f842c3ba4b9526f687560125b7b43a581201579543ca4ff",
    (
        "Linux",
        "x86_64",
    ): "176746db3be7dc7bd48f3dd287c8930a4645ebb6e6700f883fddda5a4c307c16",
    (
        "Linux",
        "aarch64",
    ): "03c5d58e283f521d752dc4436014eb341092edf076eb1095953ab82debe54a8e",
    (
        "Windows",
        "AMD64",
    ): "b3279f2186a1c3c438ad5865e802bbbec26090c5d3fdb4ac1113f1143a94837a",
}


def _platform_key() -> tuple[str, str]:
    return (platform.system(), platform.machine())


async def _download_file(
    client: httpx.AsyncClient,
    url: str,
    dest: str,
) -> None:
    """Stream-download *url* to *dest*."""
    try:
        async with client.stream("GET", url, follow_redirects=True) as resp:
            resp.raise_for_status()
            with open(dest, "wb") as f:
                async for chunk in resp.aiter_bytes(chunk_size=1 << 16):
                    f.write(chunk)
    except httpx.TimeoutException as exc:
        raise RuntimeError(
            f"Timed out downloading {url}: {exc}",
        ) from exc
    except httpx.HTTPStatusError as exc:
        raise RuntimeError(
            f"HTTP {exc.response.status_code} downloading {url}",
        ) from exc


class BinaryManager:
    """Locate or auto-download the ``cloudflared`` binary."""

    def __init__(self, bin_dir: Path | None = None) -> None:
        self._bin_dir = bin_dir or _BIN_DIR

    async def get_binary_path(self) -> str:
        """Return path to ``cloudflared``, downloading if necessary."""
        path = shutil.which("cloudflared")
        if path:
            return path

        bin_name = (
            "cloudflared.exe"
            if platform.system() == "Windows"
            else "cloudflared"
        )
        local = self._bin_dir / bin_name
        if local.is_file() and os.access(str(local), os.X_OK):
            return str(local)

        return await self._download()

    @staticmethod
    def _verify_checksum(path: str, expected: str) -> None:
        """Verify SHA256 checksum of a downloaded file."""
        sha256 = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(1 << 16), b""):
                sha256.update(chunk)
        actual = sha256.hexdigest()
        if actual != expected:
            os.unlink(path)
            raise RuntimeError(
                f"SHA256 mismatch for {path}: "
                f"expected {expected}, got {actual}",
            )

    async def _download(self) -> str:
        key = _platform_key()
        url = _DOWNLOAD_URLS.get(key)
        expected_hash = _SHA256_CHECKSUMS.get(key)
        if not url or not expected_hash:
            raise RuntimeError(
                f"No cloudflared download available for {key}. "
                "Install it manually: "
                "https://developers.cloudflare.com"
                "/cloudflare-one/connections/connect-networks"
                "/downloads/",
            )

        is_windows = key[0] == "Windows"
        self._bin_dir.mkdir(parents=True, exist_ok=True)
        bin_name = "cloudflared.exe" if is_windows else "cloudflared"
        dest = self._bin_dir / bin_name

        logger.info(
            "Downloading cloudflared %s from %s ...",
            _CLOUDFLARED_VERSION,
            url,
        )

        timeout = httpx.Timeout(_DOWNLOAD_TIMEOUT, connect=30)
        async with httpx.AsyncClient(timeout=timeout) as client:
            if url.endswith(".tgz"):
                import tarfile

                with tempfile.NamedTemporaryFile(
                    suffix=".tgz",
                    delete=False,
                ) as tmp:
                    tmp_path = tmp.name
                try:
                    await _download_file(client, url, tmp_path)
                    self._verify_checksum(tmp_path, expected_hash)
                    with tarfile.open(tmp_path, "r:gz") as tar:
                        member = next(
                            (
                                m
                                for m in tar.getmembers()
                                if m.name.endswith("cloudflared")
                            ),
                            None,
                        )
                        if member is None:
                            raise RuntimeError(
                                "Archive does not contain a "
                                "cloudflared binary",
                            )
                        if not member.isfile():
                            raise RuntimeError(
                                "Tar member is not a regular"
                                f" file: {member.name} "
                                f"(type {member.type!r})",
                            )
                        fileobj = tar.extractfile(member)
                        if fileobj is None:
                            raise RuntimeError(
                                f"Cannot read tar member: {member.name}",
                            )
                        with fileobj, open(dest, "wb") as out:
                            shutil.copyfileobj(fileobj, out)
                finally:
                    if os.path.exists(tmp_path):
                        os.unlink(tmp_path)
            else:
                await _download_file(client, url, str(dest))
                self._verify_checksum(str(dest), expected_hash)

        if not is_windows:
            dest.chmod(
                dest.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP,
            )
        logger.info(
            "cloudflared %s installed to %s",
            _CLOUDFLARED_VERSION,
            dest,
        )
        return str(dest)
