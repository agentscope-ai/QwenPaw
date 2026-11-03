"""Install and upgrade the exact runtime selected by QwenPaw Local."""

import hashlib
import io
import json
from pathlib import Path
from queue import Queue
import tarfile
import zipfile

import httpx
import pytest

from qwenpaw.local_models.download_manager import (
    DownloadTaskResult,
    DownloadTaskStatus,
)
from qwenpaw.local_models.llamacpp import LlamaCppBackend
from qwenpaw.local_models.runtime_release import RELEASE, RUNTIME_METADATA


def backend_for(target, directory):
    backend = object.__new__(LlamaCppBackend)
    backend.target_dir = directory
    backend.os_name = target["os"]
    backend.arch = target["arch"]
    backend.backend = target["backend"]
    backend.cuda_version = (
        ".".join(target.get("cuda", "").split(".")[:2]) or None
    )
    return backend


def bundle(target, release=None):
    metadata = {
        key: RELEASE[key]
        for key in ("release", "upstream_commit", "patch_sha256")
    }
    metadata.update(target=target["id"], capabilities=["chat", "piccolo"])
    if release:
        metadata["release"] = release
    executable = (
        "llama-server.exe" if target["os"] == "windows" else "llama-server"
    )
    files = {
        executable: b"new runtime",
        RUNTIME_METADATA: json.dumps(metadata).encode(),
    }
    data = io.BytesIO()
    if target["os"] == "windows":
        with zipfile.ZipFile(data, "w") as archive:
            for name, content in files.items():
                archive.writestr(name, content)
    else:
        with tarfile.open(fileobj=data, mode="w:gz") as archive:
            for name, content in files.items():
                info = tarfile.TarInfo(name)
                info.size = len(content)
                info.mode = 0o755 if name == executable else 0o644
                archive.addfile(info, io.BytesIO(content))
    return metadata, data.getvalue()


@pytest.mark.parametrize("target", RELEASE["targets"], ids=lambda t: t["id"])
@pytest.mark.parametrize(
    "upgrade", [False, True], ids=["new-install", "upgrade"]
)
@pytest.mark.asyncio
async def test_install_and_upgrade_all_selected_packages(
    target, upgrade, tmp_path, monkeypatch
):
    backend = backend_for(target, tmp_path / "bin")
    if upgrade:
        backend.target_dir.mkdir()
        backend.executable.write_bytes(b"old runtime")
        assert await backend.has_update(RELEASE["release"])
    filename = backend._build_filename(RELEASE["release"])
    assert backend._runtime_target() == target["id"]
    metadata, archive = bundle(target)
    manifest = metadata | {
        "artifacts": {
            filename: {
                "sha256": hashlib.sha256(archive).hexdigest(),
                "size": len(archive),
            }
        }
    }
    client = httpx.Client

    def handler(request):
        if request.url.path.endswith("/runtime-release.json"):
            return httpx.Response(200, json=manifest)
        assert request.url.path.endswith("/" + filename)
        return httpx.Response(200, content=archive)

    monkeypatch.setattr(
        httpx,
        "Client",
        lambda **kwargs: client(
            transport=httpx.MockTransport(handler), **kwargs
        ),
    )
    staging = tmp_path / "staging"
    queue = Queue()
    backend._download_worker(
        {
            "url": "https://runtime.test/"
            + RELEASE["release"]
            + "/"
            + filename,
            "staging_dir": str(staging),
            "file_name": filename,
            "chunk_size": 100,
            "timeout": 5,
            "headers": {},
            "release": RELEASE["release"],
            "target": target["id"],
        },
        queue,
    )
    results = list(queue.queue)
    downloaded = DownloadTaskResult.from_message(results[-1])
    assert downloaded.status == DownloadTaskStatus.COMPLETED
    if upgrade:
        assert backend.executable.read_bytes() == b"old runtime"
    result, _ = backend._finalize_download_result(
        downloaded, staging_dir=staging, final_dir=backend.target_dir
    )
    assert result.status == DownloadTaskStatus.COMPLETED
    assert backend.executable.read_bytes() == b"new runtime"
    assert not await backend.has_update(RELEASE["release"])


def test_failed_swap_restores_the_previous_runtime(tmp_path, monkeypatch):
    backend = backend_for(RELEASE["targets"][0], tmp_path / "bin")
    backend.target_dir.mkdir()
    backend.executable.write_bytes(b"old runtime")
    staging = tmp_path / "staging"
    staging.mkdir()
    (staging / "llama-server").write_bytes(b"new runtime")
    rename = Path.rename

    def fail_install(path, destination):
        if path == staging:
            raise OSError("installation interrupted")
        return rename(path, destination)

    monkeypatch.setattr(Path, "rename", fail_install)
    result, _ = backend._finalize_download_result(
        DownloadTaskResult(status=DownloadTaskStatus.COMPLETED),
        staging_dir=staging,
        final_dir=backend.target_dir,
    )
    assert result.status == DownloadTaskStatus.FAILED
    assert backend.executable.read_bytes() == b"old runtime"


@pytest.mark.parametrize(
    "failure", ["checksum", "missing-release", "wrong-target"]
)
def test_bad_download_does_not_replace_installed_files(
    failure, tmp_path, monkeypatch
):
    target = RELEASE["targets"][0]
    backend = backend_for(target, tmp_path / "bin")
    backend.target_dir.mkdir()
    backend.executable.write_bytes(b"old runtime")
    metadata, archive = bundle(
        RELEASE["targets"][1] if failure == "wrong-target" else target
    )
    filename = backend._build_filename(RELEASE["release"])
    manifest = metadata | {
        "artifacts": {
            filename: {
                "size": len(archive),
                "sha256": (
                    "0" * 64
                    if failure == "checksum"
                    else hashlib.sha256(archive).hexdigest()
                ),
            }
        }
    }
    client = httpx.Client

    def handler(request):
        if request.url.path.endswith("/runtime-release.json"):
            return (
                httpx.Response(404)
                if failure == "missing-release"
                else httpx.Response(200, json=manifest)
            )
        return httpx.Response(200, content=archive)

    monkeypatch.setattr(
        httpx,
        "Client",
        lambda **kwargs: client(
            transport=httpx.MockTransport(handler), **kwargs
        ),
    )
    queue = Queue()
    backend._download_worker(
        {
            "url": "https://runtime.test/" + filename,
            "staging_dir": str(tmp_path / "staging"),
            "file_name": filename,
            "chunk_size": 100,
            "timeout": 5,
            "headers": {},
            "release": RELEASE["release"],
            "target": target["id"],
        },
        queue,
    )
    assert (
        DownloadTaskResult.from_message(list(queue.queue)[-1]).status
        == DownloadTaskStatus.FAILED
    )
    assert backend.executable.read_bytes() == b"old runtime"
