# -*- coding: utf-8 -*-
"""Exclusive runtime ownership and authenticated desktop discovery."""

from __future__ import annotations

import json
import os
import secrets
from pathlib import Path

from packaging.version import Version

from ..__version__ import __version__

if os.name == "nt":
    import msvcrt
else:
    import fcntl


class BackendInstance:
    """Hold the data-directory lock for the entire backend lifetime."""

    def __init__(self, working_dir: Path, mode: str) -> None:
        self.directory = working_dir / "runtime" / mode
        self.mode = mode
        self.token = secrets.token_hex(32)
        self.instance = secrets.token_hex(16)
        self._lock = None

    def __enter__(self) -> BackendInstance:
        if os.environ.get("QWENPAW_RUNTIME_ID"):
            raise RuntimeError(f"Hub runtimes cannot become shared hosts")
        self.directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.directory.chmod(0o700)
        self._lock = (self.directory / "runtime.lock").open("a+b")
        try:
            if os.name == "nt":
                self._lock.seek(0)
                msvcrt.locking(self._lock.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                fcntl.flock(
                    self._lock.fileno(),
                    fcntl.LOCK_EX | fcntl.LOCK_NB,
                )
        except OSError:
            self._lock.close()
            raise RuntimeError(
                f"A desktop backend already owns {self.directory.parent}",
            ) from None
        os.environ["QWENPAW_RUNTIME_CONTROL_TOKEN"] = self.token
        return self

    def publish(self, port: int) -> None:
        """Publish only while holding the lifetime lock."""
        # Match the PEP 440 to SemVer mapping used by desktop packaging.
        # Packaging rejects epochs, local segments and non-triplet releases.
        release = Version(__version__)
        version = f"{release.major}.{release.minor}.{release.micro}"
        labels = []
        if release.pre:
            kind, number = release.pre
            name = {"a": "alpha", "b": "beta", "rc": "rc"}[kind]
            labels.append(f"{name}.{number}")
        if release.dev is not None:
            labels.append(f"dev.{release.dev}")
        if labels:
            version += f"-{'.'.join(labels)}"
        if release.post is not None:
            version += f"+post.{release.post}"
        temporary = self.directory / "runtime.json.tmp"
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(
                {
                    "protocol": 1,
                    "version": version,
                    "instance": self.instance,
                    "token": self.token,
                    "port": port,
                    "mode": self.mode,
                },
                stream,
            )
        temporary.replace(self.directory / "runtime.json")

    def request_stop(self) -> None:
        """Tell the native supervisor not to restart this instance."""
        (self.directory / "stop-request").write_text(
            self.instance,
            encoding="utf-8",
        )

    def __exit__(self, *_args: object) -> None:
        try:
            (self.directory / "runtime.json").unlink(missing_ok=True)
        finally:
            self._lock.close()
