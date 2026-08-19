# -*- coding: utf-8 -*-
# flake8: noqa: E501
# pylint: disable=too-many-return-statements
"""Creator-owned native executable dependency management.

QwenPaw installs Python requirements for plugins.  Creator additionally needs
native executables, so this module gives those tools one explicit, testable
resolution boundary instead of letting feature code depend on the host PATH.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from hashlib import sha256
import logging
import os
from pathlib import Path
import platform
import shutil
import tempfile
import threading
from typing import Any
from urllib.request import Request, urlopen

from services.storage_root import require_creator_data_root


logger = logging.getLogger("qwenpaw.creator.runtime_dependencies")

CREATOR_BINARY_DIR_ENV = "CREATOR_BINARY_DIR"
CREATOR_JQ_PATH_ENV = "CREATOR_JQ_PATH"
CREATOR_FFMPEG_PATH_ENV = "CREATOR_FFMPEG_PATH"
CREATOR_FFPROBE_PATH_ENV = "CREATOR_FFPROBE_PATH"
CREATOR_AUTO_INSTALL_BINARIES_ENV = "CREATOR_AUTO_INSTALL_BINARIES"
CREATOR_JQ_BASE_URL_ENV = "CREATOR_JQ_BASE_URL"
CREATOR_LIBREOFFICE_PATH_ENV = "CREATOR_LIBREOFFICE_PATH"

JQ_VERSION = "1.8.2"
_JQ_RELEASE_BASE_URL = (
    f"https://github.com/jqlang/jq/releases/download/jq-{JQ_VERSION}"
)
_JQ_ASSETS: dict[tuple[str, str], tuple[str, str]] = {
    ("linux", "amd64"): (
        "jq-linux-amd64",
        "b1c22172dd303f3be49e935aa56aa48a8b7a46e0bc838b4997d3bb451495870f",
    ),
    ("linux", "arm64"): (
        "jq-linux-arm64",
        "8b85c817833814ddca00a144c33705546355afccf0cf39b188f3cdb48b852309",
    ),
    ("darwin", "amd64"): (
        "jq-macos-amd64",
        "e94b266e3c26690550006abe63152b782280f4e14374accdf04cbde844f00bc0",
    ),
    ("darwin", "arm64"): (
        "jq-macos-arm64",
        "2d75340ba57a4b4b4c8708a21c2dc8e958a48aaa8bba13b27f77f6e4c0eca07e",
    ),
    ("windows", "amd64"): (
        "jq-windows-amd64.exe",
        "a6fc67fedaf9128a3309a1e2ebb8b986aeccf70122ee46d2cb4849e423f0c627",
    ),
    ("windows", "arm64"): (
        "jq-windows-arm64.exe",
        "083b5377392bc57cf27052b6d20a2d927770683bca844632901ff38b4b7b0ac7",
    ),
}
_MAX_JQ_DOWNLOAD_BYTES = 32 * 1024 * 1024
_DOWNLOAD_LOCK = threading.Lock()


class CreatorBinaryDependencyError(RuntimeError):
    """A required Creator native dependency could not be prepared."""


@dataclass(frozen=True, slots=True)
class BinaryStatus:
    name: str
    status: str
    path: str | None
    source: str
    required: bool
    detail: str | None = None

    def as_dict(self) -> dict[str, str | bool | None]:
        return asdict(self)


def _is_executable(path: str | Path | None) -> bool:
    if not path:
        return False
    candidate = Path(path).expanduser()
    if not candidate.is_file():
        return False
    return os.name == "nt" or os.access(candidate, os.X_OK)


def _configured_executable(environment_name: str) -> str | None:
    raw = os.environ.get(environment_name, "").strip()
    if not raw:
        return None
    candidate = Path(raw).expanduser()
    if not candidate.is_absolute() or not _is_executable(candidate):
        return None
    return os.fspath(candidate.resolve(strict=False))


def _managed_binary_path(name: str) -> Path | None:
    raw = os.environ.get(CREATOR_BINARY_DIR_ENV, "").strip()
    if not raw:
        return None
    directory = Path(raw).expanduser()
    if not directory.is_absolute():
        return None
    suffix = ".exe" if os.name == "nt" else ""
    return directory / f"{name}{suffix}"


def resolve_jq() -> str | None:
    configured = _configured_executable(CREATOR_JQ_PATH_ENV)
    if configured:
        return configured
    managed = _managed_binary_path("jq")
    if managed is not None and _is_executable(managed):
        asset = _JQ_ASSETS.get(_platform_key())
        if asset is not None and _file_sha256(managed) == asset[1]:
            return os.fspath(managed)
    return shutil.which("jq")


def resolve_ffmpeg() -> str | None:
    configured = _configured_executable(CREATOR_FFMPEG_PATH_ENV)
    if configured:
        return configured
    system = shutil.which("ffmpeg")
    if system:
        return system
    try:
        import imageio_ffmpeg

        bundled = imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return None
    return (
        os.fspath(Path(bundled).resolve(strict=False))
        if _is_executable(bundled)
        else None
    )


def resolve_ffprobe(*, ffmpeg_path: str | None = None) -> str | None:
    configured = _configured_executable(CREATOR_FFPROBE_PATH_ENV)
    if configured:
        return configured
    system = shutil.which("ffprobe")
    if system:
        return system
    paired_ffmpeg = ffmpeg_path or resolve_ffmpeg()
    if paired_ffmpeg:
        ffmpeg = Path(paired_ffmpeg)
        suffix = ".exe" if ffmpeg.suffix.casefold() == ".exe" else ""
        sibling = ffmpeg.with_name(f"ffprobe{suffix}")
        if _is_executable(sibling):
            return os.fspath(sibling)
    return None


# Optional office-document conversion backend (no auto-install; same
# optional-tool policy as jq). Server processes often start with a minimal
# PATH, so well-known install locations are probed explicitly.
_SOFFICE_CANDIDATES = (
    "/Applications/LibreOffice.app/Contents/MacOS/soffice",
    os.path.expanduser(
        "~/Applications/LibreOffice.app/Contents/MacOS/soffice",
    ),
    "/opt/homebrew/bin/soffice",
    "/usr/local/bin/soffice",
    "/usr/bin/soffice",
    "/usr/bin/libreoffice",
    "/snap/bin/libreoffice",
)


def resolve_libreoffice() -> str | None:
    configured = _configured_executable(CREATOR_LIBREOFFICE_PATH_ENV)
    if configured:
        return configured
    for name in ("libreoffice", "soffice"):
        system = shutil.which(name)
        if system:
            return system
    for candidate in _SOFFICE_CANDIDATES:
        if _is_executable(candidate):
            return candidate
    return None


def _platform_key() -> tuple[str, str]:
    system = platform.system().casefold()
    system_aliases = {"macos": "darwin", "osx": "darwin"}
    system = system_aliases.get(system, system)
    machine = platform.machine().casefold()
    if machine in {"x86_64", "amd64", "x64"}:
        architecture = "amd64"
    elif machine in {"aarch64", "arm64"}:
        architecture = "arm64"
    else:
        architecture = machine
    return system, architecture


def _auto_install_enabled() -> bool:
    value = (
        os.environ.get(CREATOR_AUTO_INSTALL_BINARIES_ENV, "0")
        .strip()
        .casefold()
    )
    return value not in {"0", "false", "no", "off"}


def _file_sha256(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


class CreatorBinaryManager:
    """Resolve required tools and install the pinned jq binary when needed."""

    def __init__(self, *, binary_dir: Path | None = None) -> None:
        if binary_dir is None:
            configured = os.environ.get(CREATOR_BINARY_DIR_ENV, "").strip()
            binary_dir = (
                Path(configured).expanduser()
                if configured
                else require_creator_data_root() / "runtime-tools" / "bin"
            )
        if not binary_dir.is_absolute():
            raise CreatorBinaryDependencyError(
                "CREATOR_BINARY_DIR must be absolute",
            )
        self.binary_dir = binary_dir.resolve(strict=False)
        os.environ[CREATOR_BINARY_DIR_ENV] = os.fspath(self.binary_dir)

    @property
    def jq_path(self) -> Path:
        suffix = ".exe" if os.name == "nt" else ""
        return self.binary_dir / f"jq{suffix}"

    def _jq_asset(self) -> tuple[str, str]:
        key = _platform_key()
        try:
            return _JQ_ASSETS[key]
        except KeyError as error:
            raise CreatorBinaryDependencyError(
                "Creator cannot auto-install jq for "
                f"{key[0] or 'unknown'}/{key[1] or 'unknown'}; configure "
                f"{CREATOR_JQ_PATH_ENV} with an absolute executable path",
            ) from error

    def _download_jq(self) -> Path:
        asset_name, expected_sha256 = self._jq_asset()
        base_url = (
            os.environ.get(CREATOR_JQ_BASE_URL_ENV, "").strip().rstrip("/")
        )
        url = f"{base_url or _JQ_RELEASE_BASE_URL}/{asset_name}"
        self.binary_dir.mkdir(parents=True, exist_ok=True)
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=".jq-download-",
            dir=self.binary_dir,
        )
        os.close(descriptor)
        temporary_path = Path(temporary_name)
        try:
            digest = sha256()
            size = 0
            with temporary_path.open("wb") as temporary:
                request = Request(
                    url,
                    headers={"User-Agent": "QwenPaw-Creator/0.1"},
                )
                with urlopen(request, timeout=60) as response:
                    while chunk := response.read(1024 * 1024):
                        size += len(chunk)
                        if size > _MAX_JQ_DOWNLOAD_BYTES:
                            raise CreatorBinaryDependencyError(
                                "Downloaded jq binary exceeds the 32 MiB safety limit",
                            )
                        digest.update(chunk)
                        temporary.write(chunk)
                temporary.flush()
                os.fsync(temporary.fileno())
            actual_sha256 = digest.hexdigest()
            if actual_sha256 != expected_sha256:
                raise CreatorBinaryDependencyError(
                    "Downloaded jq binary failed SHA-256 verification",
                )
            if os.name != "nt":
                temporary_path.chmod(0o755)
            os.replace(temporary_path, self.jq_path)
        except Exception:
            temporary_path.unlink(missing_ok=True)
            raise
        logger.info("Installed verified jq %s at %s", JQ_VERSION, self.jq_path)
        return self.jq_path

    def ensure_jq(self) -> BinaryStatus:
        def missing(source: str, detail: str) -> BinaryStatus:
            os.environ.pop(CREATOR_JQ_PATH_ENV, None)
            logger.warning(
                "jq is unavailable; Creator will start in degraded mode: %s",
                detail,
            )
            return BinaryStatus(
                "jq",
                "missing",
                None,
                source,
                True,
                detail,
            )

        configured = _configured_executable(CREATOR_JQ_PATH_ENV)
        if configured:
            return BinaryStatus("jq", "ok", configured, "configured", True)
        system = shutil.which("jq")
        if system:
            os.environ[CREATOR_JQ_PATH_ENV] = system
            return BinaryStatus("jq", "ok", system, "system", True)
        managed = self.jq_path
        try:
            _, expected_sha256 = self._jq_asset()
        except CreatorBinaryDependencyError as error:
            return missing("unsupported-platform", str(error))
        if (
            _is_executable(managed)
            and _file_sha256(managed) == expected_sha256
        ):
            path = os.fspath(managed)
            os.environ[CREATOR_JQ_PATH_ENV] = path
            return BinaryStatus(
                "jq",
                "ok",
                path,
                f"managed-{JQ_VERSION}",
                True,
            )
        if not _auto_install_enabled():
            return missing(
                "auto-install-disabled",
                f"jq is missing and {CREATOR_AUTO_INSTALL_BINARIES_ENV}=0; "
                f"configure {CREATOR_JQ_PATH_ENV} or install jq on PATH",
            )
        with _DOWNLOAD_LOCK:
            if not (
                _is_executable(managed)
                and _file_sha256(managed) == expected_sha256
            ):
                try:
                    self._download_jq()
                except Exception as error:
                    return missing(
                        "auto-install-failed",
                        f"Unable to download jq {JQ_VERSION}: {error}",
                    )
        path = os.fspath(managed)
        os.environ[CREATOR_JQ_PATH_ENV] = path
        return BinaryStatus("jq", "ok", path, f"managed-{JQ_VERSION}", True)

    def ensure_ffmpeg(self) -> BinaryStatus:
        configured = _configured_executable(CREATOR_FFMPEG_PATH_ENV)
        path = resolve_ffmpeg()
        if not path:
            raise CreatorBinaryDependencyError(
                "ffmpeg is missing; reinstall Creator so imageio-ffmpeg is installed, "
                f"or configure {CREATOR_FFMPEG_PATH_ENV}",
            )
        source = (
            "configured"
            if configured
            else (
                "system"
                if shutil.which("ffmpeg") == path
                else "imageio-ffmpeg"
            )
        )
        os.environ[CREATOR_FFMPEG_PATH_ENV] = path
        return BinaryStatus("ffmpeg", "ok", path, source, True)

    def ensure_ffprobe(self, *, ffmpeg_path: str) -> BinaryStatus:
        path = resolve_ffprobe(ffmpeg_path=ffmpeg_path)
        if path:
            os.environ[CREATOR_FFPROBE_PATH_ENV] = path
            return BinaryStatus(
                "ffprobe",
                "ok",
                path,
                "system-or-paired",
                False,
            )
        os.environ.pop(CREATOR_FFPROBE_PATH_ENV, None)
        return BinaryStatus(
            "ffprobe",
            "fallback",
            None,
            "ffmpeg-metadata",
            False,
            "ffprobe is optional; Creator will probe metadata with the resolved ffmpeg binary",
        )

    def ensure_all(self) -> dict[str, BinaryStatus]:
        jq = self.ensure_jq()
        ffmpeg = self.ensure_ffmpeg()
        ffprobe = self.ensure_ffprobe(ffmpeg_path=ffmpeg.path or "")
        return {"jq": jq, "ffmpeg": ffmpeg, "ffprobe": ffprobe}


_LAST_STATUS: dict[str, BinaryStatus] | None = None
_STATUS_LOCK = threading.Lock()


def ensure_creator_runtime_dependencies() -> dict[str, BinaryStatus]:
    global _LAST_STATUS
    status = CreatorBinaryManager().ensure_all()
    with _STATUS_LOCK:
        _LAST_STATUS = status
    return status


def creator_runtime_dependency_health() -> dict[str, Any]:
    with _STATUS_LOCK:
        snapshot = dict(_LAST_STATUS) if _LAST_STATUS is not None else None
    if snapshot is None:
        ffmpeg = resolve_ffmpeg()
        ffprobe = resolve_ffprobe(ffmpeg_path=ffmpeg)
        jq = resolve_jq()
        snapshot = {
            "jq": BinaryStatus(
                "jq",
                "ok" if jq else "missing",
                jq,
                "resolved",
                True,
            ),
            "ffmpeg": BinaryStatus(
                "ffmpeg",
                "ok" if ffmpeg else "missing",
                ffmpeg,
                "resolved",
                True,
            ),
            "ffprobe": BinaryStatus(
                "ffprobe",
                "ok" if ffprobe else ("fallback" if ffmpeg else "missing"),
                ffprobe,
                "resolved" if ffprobe else "ffmpeg-metadata",
                False,
            ),
        }
    required_ready = all(
        item.status == "ok" for item in snapshot.values() if item.required
    )
    return {
        "status": "ok" if required_ready else "degraded",
        "tools": {name: item.as_dict() for name, item in snapshot.items()},
    }


__all__ = [
    "BinaryStatus",
    "CREATOR_AUTO_INSTALL_BINARIES_ENV",
    "CREATOR_BINARY_DIR_ENV",
    "CREATOR_FFMPEG_PATH_ENV",
    "CREATOR_FFPROBE_PATH_ENV",
    "CREATOR_JQ_PATH_ENV",
    "CreatorBinaryDependencyError",
    "CreatorBinaryManager",
    "creator_runtime_dependency_health",
    "ensure_creator_runtime_dependencies",
    "resolve_ffmpeg",
    "resolve_ffprobe",
    "resolve_jq",
]
