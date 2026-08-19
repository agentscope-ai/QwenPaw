# -*- coding: utf-8 -*-
# pylint: disable=unused-argument,redefined-outer-name
"""OSS-hosted inspiration example behavior."""
from __future__ import annotations

import asyncio
import hashlib
import io
import json
import zipfile
from uuid import uuid4

import pytest

from api import example_routes
from httpx import ASGITransport, AsyncClient

pytestmark = pytest.mark.unit

_CREATE_PAYLOAD = {
    "clientRequestId": "example-fixture-request-1",
    "name": "乌鸦喝水示例",
    "description": "做一个乌鸦喝水的卡通短视频",
    "scenario": "short_drama",
    "aspectRatio": "16:9",
    "resolution": "720P",
    "contentType": None,
}

_EXAMPLE_ID = "crow-short-drama"
_ARCHIVE_URL = f"https://oss.example.test/examples/{_EXAMPLE_ID}.zip"


def _client(app) -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://t")


async def _export_project_archive(client) -> tuple[str, bytes]:
    """Create a real Project, export it, then remove it from the data root."""

    created = await client.post("/projects", json=_CREATE_PAYLOAD)
    assert created.status_code == 201
    project_id = created.json()["projectId"]
    exported = await client.get(
        f"/projects/{project_id}/export",
        headers={"Idempotency-Key": uuid4().hex},
    )
    assert exported.status_code == 200
    deleted = await client.delete(
        f"/projects/{project_id}",
        headers={"Idempotency-Key": uuid4().hex},
    )
    assert deleted.status_code == 204
    return project_id, exported.content


def _stage_manifest(examples_dir, entries) -> None:
    examples_dir.mkdir(exist_ok=True)
    (examples_dir / "manifest.json").write_text(
        json.dumps({"examples": entries}, ensure_ascii=False),
        encoding="utf-8",
    )


def _fake_downloader(payload_by_url: dict[str, bytes]):
    """Serve archive bytes from memory instead of the network."""

    def download(url: str, local_path: str, on_progress=None) -> None:
        payload = payload_by_url.get(url)
        if payload is None:
            raise RuntimeError(f"Remote file download failed: {url}")
        with open(local_path, "wb") as handle:
            handle.write(payload)
        if on_progress is not None:
            on_progress(len(payload), len(payload))

    return download


@pytest.fixture()
def hosted_example(app, api_runtime_root, tmp_path, monkeypatch):
    """Stage one OSS-hosted example built from a real exported Project."""

    async def scenario():
        async with _client(app) as client:
            return await _export_project_archive(client)

    project_id, archive = asyncio.run(scenario())
    examples_dir = tmp_path / "hosted-examples"
    _stage_manifest(
        examples_dir,
        [
            {
                "id": _EXAMPLE_ID,
                "title": "短剧制作",
                "description": "做一个乌鸦喝水的卡通短视频",
                "projectId": project_id,
                "archiveUrl": _ARCHIVE_URL,
                "sha256": hashlib.sha256(archive).hexdigest(),
            },
        ],
    )
    monkeypatch.setattr(example_routes, "examples_root", lambda: examples_dir)
    monkeypatch.setattr(
        example_routes,
        "download_remote_file",
        _fake_downloader({_ARCHIVE_URL: archive}),
    )
    return project_id


def test_examples_list_reports_hosted_catalogue(app, hosted_example):
    async def scenario():
        async with _client(app) as client:
            return await client.get("/examples")

    listed = asyncio.run(scenario())

    assert listed.status_code == 200
    items = listed.json()["items"]
    assert [item["id"] for item in items] == [_EXAMPLE_ID]
    assert items[0]["projectId"] == hosted_example
    assert items[0]["installed"] is False
    # Neither the archive URL nor the checksum leaks to the home page.
    assert "archiveUrl" not in items[0]
    assert "sha256" not in items[0]


def test_open_materializes_without_surfacing_in_project_list(
    app,
    api_runtime_root,
    hosted_example,
):
    async def scenario():
        async with _client(app) as client:
            opened = await client.post(f"/examples/{_EXAMPLE_ID}/open")
            listed_projects = await client.get("/projects")
            listed_examples = await client.get("/examples")
            snapshot = await client.get(
                f"/projects/{hosted_example}/project",
            )
            return opened, listed_projects, listed_examples, snapshot

    opened, listed_projects, listed_examples, snapshot = asyncio.run(
        scenario(),
    )

    assert opened.status_code == 200
    assert opened.json() == {"projectId": hosted_example, "installed": True}
    # The materialized example carries the marker and stays off the shelf...
    marker = api_runtime_root / hosted_example / ".builtin-example"
    assert marker.is_file()
    assert listed_projects.json()["items"] == []
    assert listed_examples.json()["items"][0]["installed"] is True
    # ...while id-addressed routes serve it like any other Project.
    assert snapshot.status_code == 200
    assert snapshot.json()["projectId"] == hosted_example


def test_open_is_idempotent_and_downloads_once(
    app,
    api_runtime_root,
    hosted_example,
    monkeypatch,
):
    calls: list[str] = []
    real_download = example_routes.download_remote_file

    def counting_download(url: str, local_path: str, on_progress=None) -> None:
        calls.append(url)
        real_download(url, local_path, on_progress=on_progress)

    monkeypatch.setattr(
        example_routes,
        "download_remote_file",
        counting_download,
    )

    async def scenario():
        async with _client(app) as client:
            first = await client.post(f"/examples/{_EXAMPLE_ID}/open")
            second = await client.post(f"/examples/{_EXAMPLE_ID}/open")
            return first, second

    first, second = asyncio.run(scenario())

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json() == second.json()
    # The already-installed project short-circuits the second download.
    assert calls == [_ARCHIVE_URL]
    staging = api_runtime_root / ".example-staging"
    assert not staging.exists() or not [
        entry for entry in staging.iterdir() if entry.is_dir()
    ]


def test_open_unknown_example_is_not_found(app, hosted_example):
    async def scenario():
        async with _client(app) as client:
            return await client.post("/examples/no-such-example/open")

    response = asyncio.run(scenario())

    assert response.status_code == 404


def test_manifest_entries_with_invalid_urls_are_hidden(
    app,
    api_runtime_root,
    tmp_path,
    monkeypatch,
):
    examples_dir = tmp_path / "broken-examples"
    _stage_manifest(
        examples_dir,
        [
            {
                "id": "no-url",
                "title": "缺下载地址",
                "description": "archiveUrl 不存在",
                "projectId": "project-000000000000",
            },
            {
                "id": "bad-scheme",
                "title": "非法协议",
                "description": "archiveUrl 非 http(s)",
                "projectId": "project-000000000001",
                "archiveUrl": "ftp://oss.example.test/escape.zip",
            },
            {
                "id": "bad-checksum",
                "title": "非法校验和",
                "description": "sha256 格式错误",
                "projectId": "project-000000000002",
                "archiveUrl": "https://oss.example.test/ok.zip",
                "sha256": "not-a-checksum",
            },
        ],
    )
    monkeypatch.setattr(example_routes, "examples_root", lambda: examples_dir)

    async def scenario():
        async with _client(app) as client:
            listed = await client.get("/examples")
            opened = await client.post("/examples/no-url/open")
            return listed, opened

    listed, opened = asyncio.run(scenario())

    assert listed.json()["items"] == []
    assert opened.status_code == 404


def _stage_single_entry(
    tmp_path,
    monkeypatch,
    *,
    payload_by_url: dict[str, bytes],
    sha256: str | None,
) -> None:
    examples_dir = tmp_path / "single-example"
    entry = {
        "id": "bad",
        "title": "损坏归档",
        "description": "远端归档异常",
        "projectId": "project-000000000002",
        "archiveUrl": "https://oss.example.test/bad.zip",
    }
    if sha256 is not None:
        entry["sha256"] = sha256
    _stage_manifest(examples_dir, [entry])
    monkeypatch.setattr(example_routes, "examples_root", lambda: examples_dir)
    monkeypatch.setattr(
        example_routes,
        "download_remote_file",
        _fake_downloader(payload_by_url),
    )


def _open_bad_example(app):
    async def scenario():
        async with _client(app) as client:
            return await client.post("/examples/bad/open")

    return asyncio.run(scenario())


def test_download_failure_is_an_integrity_error(
    app,
    api_runtime_root,
    tmp_path,
    monkeypatch,
):
    # The fake downloader has no payload for the URL, so it raises like the
    # real transport does on network errors.
    _stage_single_entry(
        tmp_path,
        monkeypatch,
        payload_by_url={},
        sha256=None,
    )

    response = _open_bad_example(app)

    assert response.status_code == 503
    assert "下载失败" in response.json()["message"]
    assert not (api_runtime_root / "project-000000000002").exists()


def test_checksum_mismatch_is_an_integrity_error(
    app,
    api_runtime_root,
    tmp_path,
    monkeypatch,
):
    payload = io.BytesIO()
    with zipfile.ZipFile(payload, "w") as archive:
        archive.writestr("project-000000000002/project.json", "{}")
    _stage_single_entry(
        tmp_path,
        monkeypatch,
        payload_by_url={
            "https://oss.example.test/bad.zip": payload.getvalue(),
        },
        sha256="0" * 64,
    )

    response = _open_bad_example(app)

    assert response.status_code == 503
    assert "校验失败" in response.json()["message"]
    assert not (api_runtime_root / "project-000000000002").exists()


def test_corrupt_hosted_archive_is_an_integrity_error(
    app,
    api_runtime_root,
    tmp_path,
    monkeypatch,
):
    payload = io.BytesIO()
    with zipfile.ZipFile(payload, "w") as archive:
        archive.writestr("../escape.txt", "boom")
    archive_bytes = payload.getvalue()
    _stage_single_entry(
        tmp_path,
        monkeypatch,
        payload_by_url={
            "https://oss.example.test/bad.zip": archive_bytes,
        },
        sha256=hashlib.sha256(archive_bytes).hexdigest(),
    )

    response = _open_bad_example(app)

    # Hosted archives are publisher-controlled, so damage is 503 not 400.
    assert response.status_code == 503
    assert "损坏" in response.json()["message"]
    assert not (api_runtime_root / "project-000000000002").exists()
