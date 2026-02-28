# -*- coding: utf-8 -*-
"""Auto-download cloudflared binary if not in PATH."""
from __future__ import annotations

import logging
import os
import platform
import shutil
import stat
import tempfile
from pathlib import Path
from urllib.request import urlretrieve

logger = logging.getLogger(__name__)

_BIN_DIR = Path("~/.copaw/bin").expanduser()

# cloudflared release download URLs by (system, machine) pair.
_DOWNLOAD_URLS: dict[tuple[str, str], str] = {
    ("Darwin", "x86_64"): (
        "https://github.com/cloudflare/cloudflared/releases/latest"
        "/download/cloudflared-darwin-amd64.tgz"
    ),
    ("Darwin", "arm64"): (
        "https://github.com/cloudflare/cloudflared/releases/latest"
        "/download/cloudflared-darwin-arm64.tgz"
    ),
    ("Linux", "x86_64"): (
        "https://github.com/cloudflare/cloudflared/releases/latest"
        "/download/cloudflared-linux-amd64"
    ),
    ("Linux", "aarch64"): (
        "https://github.com/cloudflare/cloudflared/releases/latest"
        "/download/cloudflared-linux-arm64"
    ),
}


def _platform_key() -> tuple[str, str]:
    return (platform.system(), platform.machine())


class BinaryManager:
    """Locate or auto-download the ``cloudflared`` binary."""

    def __init__(self, bin_dir: Path | None = None) -> None:
        self._bin_dir = bin_dir or _BIN_DIR

    def get_binary_path(self) -> str:
        """Return path to ``cloudflared``, downloading if necessary."""
        path = shutil.which("cloudflared")
        if path:
            return path

        local = self._bin_dir / "cloudflared"
        if local.is_file() and os.access(str(local), os.X_OK):
            return str(local)

        return self._download()

    def _download(self) -> str:
        key = _platform_key()
        url = _DOWNLOAD_URLS.get(key)
        if not url:
            raise RuntimeError(
                f"No cloudflared download available for {key}. "
                "Install it manually: https://developers.cloudflare.com"
                "/cloudflare-one/connections/connect-networks/downloads/",
            )

        self._bin_dir.mkdir(parents=True, exist_ok=True)
        dest = self._bin_dir / "cloudflared"

        logger.info("Downloading cloudflared from %s ...", url)

        if url.endswith(".tgz"):
            import tarfile

            with tempfile.NamedTemporaryFile(
                suffix=".tgz",
                delete=False,
            ) as tmp:
                tmp_path = tmp.name
            try:
                urlretrieve(url, tmp_path)
                with tarfile.open(tmp_path, "r:gz") as tar:
                    members = tar.getnames()
                    cf_member = next(
                        (m for m in members if m.endswith("cloudflared")),
                        members[0],
                    )
                    # Guard against path traversal (tar slip)
                    resolved = (self._bin_dir / cf_member).resolve()
                    if not str(resolved).startswith(
                        str(self._bin_dir.resolve()),
                    ):
                        raise RuntimeError(
                            f"Tar member escapes target dir: {cf_member}",
                        )
                    tar.extract(cf_member, path=str(self._bin_dir))
                    extracted = self._bin_dir / cf_member
                    if extracted != dest:
                        extracted.rename(dest)
            finally:
                os.unlink(tmp_path)
        else:
            urlretrieve(url, str(dest))

        dest.chmod(dest.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP)
        logger.info("cloudflared installed to %s", dest)
        return str(dest)
