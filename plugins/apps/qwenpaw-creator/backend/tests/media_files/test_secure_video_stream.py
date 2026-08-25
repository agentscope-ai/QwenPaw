# -*- coding: utf-8 -*-
# flake8: noqa: E501
# pylint: disable=redefined-builtin,protected-access
from __future__ import annotations

import asyncio
from functools import wraps
import hashlib
import os
from pathlib import Path
import socket

import httpx
import pytest

from domain.errors import StorageIntegrityError, ValidationError
from services.media_files import secure_video_stream
from services.media_files.secure_video_stream import SecureR2VVideoMaterializer

pytestmark = pytest.mark.unit

_MP4 = b"\x00\x00\x00\x18ftypisom" + b"mp4-payload" * 16
_WEBM = b"\x1a\x45\xdf\xa3\x42\x82\x84webm" + b"webm-payload" * 16


def _run_async(function):
    @wraps(function)
    def run(*args, **kwargs):
        return asyncio.run(function(*args, **kwargs))

    return run


def _scope(tmp_path: Path) -> tuple[Path, Path]:
    project_root = tmp_path.resolve() / "project-1"
    scratch = project_root / "runtime" / "task-work" / "task-1"
    scratch.mkdir(parents=True)
    (project_root / "project.json").write_text("{}", encoding="utf-8")
    return project_root, scratch


async def _materialize(
    output: dict,
    project_root: Path,
    **materializer_kwargs,
):
    request_headers = materializer_kwargs.pop("request_headers", None)
    return await SecureR2VVideoMaterializer(**materializer_kwargs).materialize(
        output,
        project_root=project_root,
        project_id="project-1",
        task_id="task-1",
        request_headers=request_headers,
    )


def _resolver_for(mapping: dict[str, str], calls: list[str] | None = None):
    def resolve(host: str, port: int, *, type: int):
        assert type == socket.SOCK_STREAM
        if calls is not None:
            calls.append(host)
        address = mapping[host]
        family = socket.AF_INET6 if ":" in address else socket.AF_INET
        return [(family, socket.SOCK_STREAM, 6, "", (address, port))]

    return resolve


class _Peer:
    def __init__(self, address: str) -> None:
        self.address = address

    def get_extra_info(self, name: str):
        assert name == "server_addr"
        return (self.address, 443)


class _StaticStream(httpx.AsyncByteStream):
    def __init__(self, content: bytes) -> None:
        self.content = content

    async def __aiter__(self):
        if self.content:
            yield self.content

    async def aclose(self) -> None:
        return None


def _response(
    status: int,
    *,
    peer: str,
    content: bytes = b"",
    headers: dict[str, str] | None = None,
    stream: httpx.AsyncByteStream | None = None,
) -> httpx.Response:
    return httpx.Response(
        status_code=status,
        headers=headers,
        extensions={"network_stream": _Peer(peer)},
        stream=stream or _StaticStream(content),
    )


@pytest.mark.parametrize(
    ("content", "declared", "container"),
    [
        (_MP4, "video/mp4", "mp4"),
        (_WEBM, "video/webm", "webm"),
    ],
)
@_run_async
async def test_local_streaming_detects_video_magic_and_returns_integrity(
    tmp_path: Path,
    content: bytes,
    declared: str,
    container: str,
) -> None:
    project_root, scratch = _scope(tmp_path)
    source = scratch / "provider-output.bin"
    source.write_bytes(content)

    result = await _materialize(
        {"path": str(source), "media_type": declared},
        project_root,
    )

    assert result.path.parent == scratch
    assert result.sha256 == hashlib.sha256(content).hexdigest()
    assert result.container == container
    assert result.path.read_bytes() == content


@pytest.mark.parametrize(
    "source_factory",
    [
        lambda root, _scratch: str(
            root / "runtime" / "task-work" / "task-2" / "v.mp4",
        ),
        lambda _root, _scratch: "/generated/projects/project-2/task-work/task-1/v.mp4",
        lambda root, _scratch: str(
            root / "runtime" / "task-work" / "task-1-neighbor" / "v.mp4",
        ),
    ],
)
@_run_async
async def test_local_absolute_file_and_generated_sources_cannot_cross_scope(
    tmp_path: Path,
    source_factory,
) -> None:
    project_root, scratch = _scope(tmp_path)
    source = source_factory(project_root, scratch)

    with pytest.raises(ValidationError, match="跨越|scope"):
        await _materialize(
            {"path": source, "media_type": "video/mp4"},
            project_root,
        )

    assert not list(scratch.glob("r2v-materialized-*"))


@_run_async
async def test_current_generated_url_is_allowed_but_openat_rejects_symlink_file(
    tmp_path: Path,
) -> None:
    project_root, scratch = _scope(tmp_path)
    outside = tmp_path / "outside.mp4"
    outside.write_bytes(_MP4)
    (scratch / "provider.mp4").symlink_to(outside)

    with pytest.raises(ValidationError, match="符号链接|regular"):
        await _materialize(
            {
                "url": "/generated/projects/project-1/task-work/task-1/provider.mp4",
                "media_type": "video/mp4",
            },
            project_root,
        )


@_run_async
async def test_openat_rejects_symlink_parent_and_hard_link(
    tmp_path: Path,
) -> None:
    project_root, scratch = _scope(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "provider.mp4").write_bytes(_MP4)
    (scratch / "linked").symlink_to(outside, target_is_directory=True)

    with pytest.raises(ValidationError, match="符号链接|父目录"):
        await _materialize(
            {"path": "linked/provider.mp4", "media_type": "video/mp4"},
            project_root,
        )

    source = scratch / "source.mp4"
    source.write_bytes(_MP4)
    hard_link = scratch / "hard.mp4"
    os.link(source, hard_link)
    with pytest.raises(ValidationError, match="硬链接"):
        await _materialize(
            {"path": str(hard_link), "media_type": "video/mp4"},
            project_root,
        )


@_run_async
async def test_size_mime_checksum_and_magic_failures_remove_partial_file(
    tmp_path: Path,
) -> None:
    project_root, scratch = _scope(tmp_path)
    source = scratch / "provider.bin"
    source.write_bytes(_MP4)

    cases = [
        (
            {"max_bytes": len(_MP4) - 1},
            {"path": str(source), "media_type": "video/mp4"},
            ValidationError,
            "大小",
        ),
        (
            {},
            {"path": str(source), "media_type": "video/webm"},
            ValidationError,
            "MIME",
        ),
        (
            {},
            {
                "path": str(source),
                "media_type": "video/mp4",
                "checksum": "0" * 64,
            },
            StorageIntegrityError,
            "checksum",
        ),
    ]
    for kwargs, output, error_type, match in cases:
        with pytest.raises(error_type, match=match):
            await _materialize(output, project_root, **kwargs)
        assert not list(scratch.glob("r2v-materialized-*"))

    source.write_bytes(b"not a video")
    with pytest.raises(ValidationError, match="magic"):
        await _materialize(
            {"path": str(source), "media_type": "video/mp4"},
            project_root,
        )
    assert not list(scratch.glob("r2v-materialized-*"))


@_run_async
async def test_remote_stream_pins_peer_to_preresolved_public_dns(
    tmp_path: Path,
) -> None:
    project_root, _scratch = _scope(tmp_path)
    transport = httpx.MockTransport(
        lambda _request: _response(
            200,
            peer="93.184.216.34",
            content=_MP4,
            headers={"content-type": "video/mp4"},
        ),
    )

    result = await _materialize(
        {"url": "https://video.example/result", "media_type": "video/mp4"},
        project_root,
        resolver=_resolver_for({"video.example": "93.184.216.34"}),
        transport=transport,
    )

    assert result.source_kind == "remote"
    assert result.path.read_bytes() == _MP4


@_run_async
async def test_remote_rejects_peer_outside_dns_set_and_private_dns(
    tmp_path: Path,
) -> None:
    project_root, scratch = _scope(tmp_path)
    requests = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal requests
        requests += 1
        return _response(
            200,
            peer="93.184.216.35",
            content=_MP4,
            headers={"content-type": "video/mp4"},
        )

    with pytest.raises(ValidationError, match="预解析集合"):
        await _materialize(
            {"url": "https://video.example/result", "media_type": "video/mp4"},
            project_root,
            resolver=_resolver_for({"video.example": "93.184.216.34"}),
            transport=httpx.MockTransport(handler),
        )
    assert requests == 1

    with pytest.raises(ValidationError, match="私有|保留"):
        await _materialize(
            {
                "url": "https://private.example/result",
                "media_type": "video/mp4",
            },
            project_root,
            resolver=_resolver_for({"private.example": "127.0.0.1"}),
            transport=httpx.MockTransport(handler),
        )
    assert requests == 1
    assert not list(scratch.glob("r2v-materialized-*"))


@_run_async
async def test_each_redirect_hop_is_resolved_and_peer_pinned_again(
    tmp_path: Path,
) -> None:
    project_root, _scratch = _scope(tmp_path)
    calls: list[str] = []
    request_headers: dict[str, str | None] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        request_headers[str(request.url.host)] = request.headers.get(
            "x-goog-api-key",
        )
        if request.url.host == "origin.example":
            return _response(
                302,
                peer="93.184.216.34",
                headers={"location": "https://cdn.example/video"},
            )
        return _response(
            200,
            peer="142.250.72.14",
            content=_WEBM,
            headers={"content-type": "video/webm"},
        )

    result = await _materialize(
        {"url": "https://origin.example/start", "media_type": "video/webm"},
        project_root,
        resolver=_resolver_for(
            {
                "origin.example": "93.184.216.34",
                "cdn.example": "142.250.72.14",
            },
            calls,
        ),
        transport=httpx.MockTransport(handler),
        request_headers={"x-goog-api-key": "gm-secret"},
    )

    assert calls == ["origin.example", "cdn.example"]
    assert request_headers == {
        "origin.example": "gm-secret",
        "cdn.example": None,
    }
    assert result.container == "webm"


# ── Windows path semantics for provider-local results ─────────────────────


def _windows_semantics(monkeypatch) -> None:
    """Emulate Windows path/URL parsing on any host.

    The production code uses the platform ``Path`` and ``url2pathname``;
    swapping in their Windows counterparts reproduces exactly what a
    Windows interpreter would do.
    """

    import nturl2path
    from pathlib import PureWindowsPath

    monkeypatch.setattr(secure_video_stream, "Path", PureWindowsPath)
    monkeypatch.setattr(
        secure_video_stream,
        "url2pathname",
        nturl2path.url2pathname,
    )


def test_windows_native_and_file_uri_paths_resolve_to_scratch(
    monkeypatch,
) -> None:
    """Drive-letter paths and Path.as_uri() file URLs must materialize.

    The review's reproduction: ``file:///C:/...`` was parsed with POSIX
    semantics into a drive-less path and rejected, and ``C:\\...`` was
    read as URL scheme "c".
    """

    from pathlib import PureWindowsPath

    _windows_semantics(monkeypatch)
    project_root = PureWindowsPath(r"C:\data\project-1")

    for source in (
        r"C:\data\project-1\runtime\task-work\task-1\out.mp4",
        "file:///C:/data/project-1/runtime/task-work/task-1/out.mp4",
    ):
        parts = secure_video_stream._local_relative_parts(  # noqa: SLF001
            source,
            project_root=project_root,
            project_id="project-1",
            task_id="task-1",
        )
        assert parts == ("out.mp4",), source

    # The Windows forms gain no way around the Task scratch containment.
    for source in (
        r"C:\data\project-1\runtime\task-work\task-2\out.mp4",
        r"\\server\share\out.mp4",
        "file:///C:/data/other/out.mp4",
    ):
        with pytest.raises(ValidationError, match="跨越|scope"):
            secure_video_stream._local_relative_parts(  # noqa: SLF001
                source,
                project_root=project_root,
                project_id="project-1",
                task_id="task-1",
            )
