# -*- coding: utf-8 -*-
"""Actual form parser, scoped files and streaming through minimal SDK routes."""

import asyncio
import io
import os
import threading

import httpx
import pytest

from qwenpaw.plugins.testing import PluginTestHost
from qwenpaw.plugins.compliance import check_plugin
from qwenpaw.plugins.apps import PawApp, FileResponse
from qwenpaw.plugins import custody
from qwenpaw.plugins._http import _DownloadReader
from qwenpaw.plugins.errors import ResourceError
from qwenpaw.plugins.resources import ResourceOwner, ResourceScope
from .sdk_author_fixture import make_plugin

SOURCE = """
from qwenpaw.plugins.apps import PawApp, HttpResponse, FileResponse, UploadedFile
class Plugin:
    def register(self, ctx):
        app = PawApp(app_id='transfer-contract')
        @app.route('/upload', methods=('POST',), body='form', max_body_bytes=2 * 1024 * 1024)
        async def upload(call, request):
            values = request.form.get('file', ())
            if len(values) != 1 or not isinstance(values[0], UploadedFile):
                return HttpResponse({'error': 'one file required'}, status=400)
            file = values[0]
            await call.storage.awrite_bytes('report.bin', file.content)
            return HttpResponse({'filename': file.filename, 'size': file.size, 'content_type': file.content_type})
        @app.route('/download')
        async def download(call, request):
            return FileResponse(call.storage.path('report.bin'), filename='download.bin')
        ctx.register_app(app)
plugin = Plugin()
"""


async def test_download_reuses_one_worker_and_joins_it(
    sdk_component,
    monkeypatch,
):
    workers = set()
    original = os.fdopen

    def tracked_open(*args, **kwargs):
        stream = original(*args, **kwargs)
        if stream.mode != "rb":
            return stream

        class Reader:
            def read(self, size):
                workers.add(threading.current_thread())
                return stream.read(size)

            def __getattr__(self, name):
                return getattr(stream, name)

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return stream.__exit__(*exc)

        return Reader()

    content = bytes(range(256)) * 16384

    def declare(ctx):
        app = PawApp(app_id="reader")

        @app.route("/file")
        async def download(call, request):
            await call.storage.awrite_bytes("report.bin", content)
            return FileResponse(call.storage.path("report.bin"))

        ctx.register_app(app)

    async with sdk_component(declare, capabilities=("apps",)) as (host, _):
        monkeypatch.setattr(os, "fdopen", tracked_open)
        response = await host.request("GET", "/api/reader/file")
        assert (response.status, response.body) == (200, content)
        assert len(workers) == 1
        assert not any(worker.is_alive() for worker in workers)


@pytest.mark.parametrize("operation", ["open", "read"])
async def test_download_cancel_keeps_file_until_worker_exits(
    monkeypatch,
    operation,
):
    monkeypatch.setattr(custody, "CONNECTION_STOP_SECONDS", 0.03)
    resources = ResourceScope(ResourceOwner("download-test", 1), lambda: None)
    reader = resources.connection(_DownloadReader(), "file download")
    stream = io.BytesIO(b"contents")
    entered, release = threading.Event(), threading.Event()
    workers = []

    def work():
        workers.append(threading.current_thread())
        if operation == "open":
            reader.files.enter_context(stream)
        entered.set()
        release.wait(5)
        return stream.read()

    if operation == "read":
        reader.files.enter_context(stream)
    waiting = asyncio.create_task(reader.run(work))
    try:
        assert await asyncio.to_thread(entered.wait, 2)
        waiting.cancel()
        with pytest.raises(asyncio.CancelledError):
            await waiting
        with pytest.raises(ResourceError, match="did not fully close"):
            await resources.close()
        assert (resources.closed, stream.closed, workers[0].is_alive()) == (
            False,
            False,
            True,
        )
        assert resources.snapshot()["resources"] == ("file download",)
    finally:
        release.set()
        monkeypatch.setattr(custody, "CONNECTION_STOP_SECONDS", 5)
        await resources.close()
    assert (resources.closed, stream.closed, workers[0].is_alive()) == (
        True,
        True,
        False,
    )


async def test_uploaded_content_download_identity_limits_and_lifecycle(
    tmp_path,
):
    source = make_plugin(
        tmp_path,
        SOURCE,
        ["apps"],
        plugin_id="transfer-contract",
        sdk_version="1.2",
    )
    assert check_plugin(source).ok
    async with PluginTestHost(tmp_path / "host") as host:
        assert (await host.install(source)).ok

        async def upload(content, user="alice", workspace="one", files=None):
            request = httpx.Request(
                "POST",
                "http://local/upload",
                files=files
                or {
                    "file": (
                        "../untrusted.bin",
                        content,
                        "application/octet-stream",
                    ),
                },
            )
            return await host.request(
                "POST",
                "/api/transfer-contract/upload",
                user_id=user,
                workspace_id=workspace,
                body=request.read(),
                headers=dict(request.headers),
            )

        content = (
            bytes(range(256)) * 5000
        )  # Larger than the parser's spool threshold.
        result = await upload(content)
        assert result.status == 200, result.text
        assert result.json() == {
            "filename": "../untrusted.bin",
            "size": len(content),
            "content_type": "application/octet-stream",
        }
        response = await host.request(
            "GET",
            "/api/transfer-contract/download",
            user_id="alice",
            workspace_id="one",
        )
        assert response.status == 200, response.text[:300]
        assert response.body == content
        assert "attachment" in response.headers["content-disposition"]
        async with host.open_http(
            "GET",
            "/api/transfer-contract/download",
            user_id="alice",
            workspace_id="one",
        ) as streaming:
            assert len(await anext(streaming.chunks())) == 64 * 1024
        assert not host.resource_snapshot("transfer-contract")["active_calls"]
        for user, workspace in (("bob", "one"), ("alice", "two")):
            other = await host.request(
                "GET",
                "/api/transfer-contract/download",
                user_id=user,
                workspace_id=workspace,
            )
            assert other.status == 404, other.text
        assert (await upload(b"x" * (2 * 1024 * 1024))).status == 413
        assert (
            await upload(
                b"",
                files=[("file", ("one", b"1")), ("file", ("two", b"2"))],
            )
        ).status == 400
        assert (
            await host.request(
                "POST",
                "/api/transfer-contract/upload",
                json={},
            )
        ).status == 415
        assert (await host.update_config("transfer-contract", {})).ok
        assert (await host.reload("transfer-contract")).ok
        assert (await upload(b"after reload")).status == 200
        assert (await host.set_enabled("transfer-contract", False)).ok
        assert (await upload(b"disabled")).status == 404
        assert (await host.set_enabled("transfer-contract", True)).ok
        assert (await host.uninstall("transfer-contract")).clean
        assert (await upload(b"removed")).status == 404


async def test_form_repetition_truncation_limits_and_spool_cleanup(
    sdk_component,
    monkeypatch,
):
    from starlette import formparsers

    spools = []
    original = formparsers.SpooledTemporaryFile

    def track(*args, **kwargs):
        file = original(*args, **kwargs)
        spools.append(file)
        return file

    monkeypatch.setattr(formparsers, "SpooledTemporaryFile", track)

    def declare(ctx):
        app = PawApp(app_id="forms")

        @app.route(
            "/form",
            methods=("POST",),
            body="form",
            max_body_bytes=20 * 1024 * 1024,
        )
        async def form(call, request):
            return {
                "labels": list(request.form.get("label", ())),
                "files": len(request.form.get("file", ())),
            }

        ctx.register_app(app)

    async with sdk_component(declare, capabilities=("apps",)) as (host, _):
        response = await host.request(
            "POST",
            "/api/forms/form",
            body=b"label=one&label=two",
            headers={"content-type": "application/x-www-form-urlencoded"},
        )
        assert response.json() == {"labels": ["one", "two"], "files": 0}
        encoded = httpx.Request(
            "POST",
            "http://local",
            files=[("file", (str(i), b"x")) for i in range(17)],
        )
        response = await host.request(
            "POST",
            "/api/forms/form",
            body=encoded.read(),
            headers=dict(encoded.headers),
        )
        assert response.status == 400
        assert len(spools) == 16 and all(file.closed for file in spools)
        encoded = httpx.Request(
            "POST",
            "http://local",
            files={"file": ("truncated", b"x" * 100)},
        )
        response = await host.request(
            "POST",
            "/api/forms/form",
            body=encoded.read()[:-50],
            headers=dict(encoded.headers),
        )
        assert response.status == 400
        assert all(file.closed for file in spools)


async def test_download_rejects_scope_escape_sensitive_file_and_symlink(
    sdk_component,
    tmp_path,
):
    def declare(ctx):
        app = PawApp(app_id="downloads")

        @app.route("/file")
        async def download(call, request):
            return FileResponse(request.query["path"])

        ctx.register_app(app)

    async with sdk_component(declare, capabilities=("apps",)) as (host, _):
        from urllib.parse import quote

        one = (await host._workspace("one")).workspace_dir
        two = (await host._workspace("two")).workspace_dir
        secret = one / ".env"
        secret.write_text("PRIVATE")
        from qwenpaw.config.utils import load_config, save_config

        config = load_config()
        config.security.file_guard.sensitive_files = [str(secret)]
        save_config(config)
        other = two / "report.txt"
        other.write_text("OTHER WORKSPACE")
        link = one / "escape"
        link.symlink_to(other)
        for path in (secret, other, link):
            response = await host.request(
                "GET",
                "/api/downloads/file?path=" + quote(str(path), safe=""),
                workspace_id="one",
            )
            assert response.status == 403, response.text
            assert (
                "PRIVATE" not in response.text
                and "OTHER WORKSPACE" not in response.text
            )
