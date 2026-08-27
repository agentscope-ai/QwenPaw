# -*- coding: utf-8 -*-
# pylint: disable=unused-argument,redefined-outer-name
"""OSS-hosted inspiration example behavior."""
from __future__ import annotations

import hashlib
import io
import json
import zipfile
from uuid import uuid4

import pytest

from api import example_routes

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


async def _export_project_archive(client) -> tuple[str, bytes]:
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
def hosted_example(
    app,
    api_runtime_root,
    tmp_path,
    monkeypatch,
    run_scenario,
):
    project_id, archive = run_scenario(app, _export_project_archive)
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


def test_open_materializes_without_surfacing_in_project_list(
    app,
    api_runtime_root,
    hosted_example,
    run_scenario,
):
    async def scenario(client):
        listed = await client.get("/examples")
        opened = await client.post(f"/examples/{_EXAMPLE_ID}/open")
        projects = await client.get("/projects")
        examples = await client.get("/examples")
        snapshot = await client.get(f"/projects/{hosted_example}/project")
        return listed, opened, projects, examples, snapshot

    listed, opened, projects, examples, snapshot = run_scenario(
        app,
        scenario,
    )

    assert listed.status_code == 200
    item = listed.json()["items"][0]
    assert [it["id"] for it in listed.json()["items"]] == [_EXAMPLE_ID]
    assert item["projectId"] == hosted_example
    assert item["installed"] is False
    assert "archiveUrl" not in item
    assert "sha256" not in item
    assert opened.status_code == 200
    assert opened.json() == {"projectId": hosted_example, "installed": True}
    marker = api_runtime_root / hosted_example / ".builtin-example"
    assert marker.is_file()
    assert projects.json()["items"] == []
    assert examples.json()["items"][0]["installed"] is True
    assert snapshot.status_code == 200
    assert snapshot.json()["projectId"] == hosted_example


def _zip_bytes(member: str) -> bytes:
    payload = io.BytesIO()
    with zipfile.ZipFile(payload, "w") as archive:
        archive.writestr(member, "{}")
    return payload.getvalue()


@pytest.mark.parametrize(
    ("archive", "sha256", "expected_message"),
    [
        pytest.param(
            _zip_bytes("project-000000000002/project.json"),
            "0" * 64,
            "校验失败",
            id="checksum-mismatch",
        ),
        pytest.param(
            _zip_bytes("../escape.txt"),
            "match",
            "损坏",
            id="zip-member-traversal-is-corrupt",
        ),
    ],
)
def test_hosted_archive_integrity_failures_are_503(
    app,
    api_runtime_root,
    tmp_path,
    monkeypatch,
    api_request,
    archive,
    sha256,
    expected_message,
):
    examples_dir = tmp_path / "single-example"
    entry = {
        "id": "bad",
        "title": "损坏归档",
        "description": "远端归档异常",
        "projectId": "project-000000000002",
        "archiveUrl": "https://oss.example.test/bad.zip",
    }
    payload_by_url = {entry["archiveUrl"]: archive}
    if sha256 == "match":
        sha256 = hashlib.sha256(archive).hexdigest()
    if sha256 is not None:
        entry["sha256"] = sha256
    _stage_manifest(examples_dir, [entry])
    monkeypatch.setattr(example_routes, "examples_root", lambda: examples_dir)
    monkeypatch.setattr(
        example_routes,
        "download_remote_file",
        _fake_downloader(payload_by_url),
    )

    response = api_request(app, "POST", "/examples/bad/open")

    # Hosted archives are publisher-controlled, so damage is 503 not 400.
    assert response.status_code == 503
    assert expected_message in response.json()["message"]
    assert not (api_runtime_root / "project-000000000002").exists()
