# -*- coding: utf-8 -*-
"""Unit tests for ``qwenpaw.app.routers.coding_cli``.

Scope: route wiring (404/202/409), settings redaction and ``***``
preserve semantics, install task state machine. The service runs for
real against a redirected ``~`` (``os.path.expanduser`` monkeypatched
to a tmp dir); subprocess probing is mocked.
"""

# pylint: disable=protected-access,redefined-outer-name,unused-argument
from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Generator
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from qwenpaw.app.routers.coding_cli import router as coding_cli_router
from qwenpaw.coding_cli.service import CodingCliService


@pytest.fixture
def app(tmp_path, monkeypatch) -> FastAPI:
    monkeypatch.setattr(
        "os.path.expanduser",
        lambda p: str(tmp_path / p.lstrip("~/")),
    )
    application = FastAPI()
    application.include_router(coding_cli_router, prefix="/api")
    application.state.coding_cli_service = CodingCliService()
    return application


@pytest.fixture
def client(app) -> TestClient:
    return TestClient(app)


@pytest.fixture
def no_bin() -> Generator[None, None, None]:
    """Make version probing report 'not installed'."""

    with patch(
        "qwenpaw.coding_cli.service.CodingCliService._run",
        return_value=None,
    ):
        yield


def test_list_clis(client, no_bin) -> None:
    res = client.get("/api/coding-cli")
    assert res.status_code == 200
    ids = {item["id"] for item in res.json()["clis"]}
    assert ids == {"qwen-code", "opencode"}
    for item in res.json()["clis"]:
        assert item["installed"] is False
        assert item["auth"]["configured"] is False


def test_unknown_cli_404(client) -> None:
    assert client.get("/api/coding-cli/claude-code").status_code == 404
    assert (
        client.put(
            "/api/coding-cli/claude-code/settings",
            json={"a": 1},
        ).status_code
        == 404
    )


def test_settings_roundtrip_redaction(client, tmp_path) -> None:
    qwen_dir = tmp_path / ".qwen"
    qwen_dir.mkdir()
    (qwen_dir / "settings.json").write_text(
        json.dumps(
            {
                "security": {
                    "auth": {
                        "selectedType": "openai",
                        "apiKey": "sk-secret",
                        "baseUrl": "http://h:7113/v1",
                    },
                },
                "model": {"name": "qwen3.6-27b-fp8"},
            },
        ),
    )
    res = client.get("/api/coding-cli/qwen-code/settings")
    assert res.status_code == 200
    auth = res.json()["settings"]["security"]["auth"]
    assert auth["apiKey"] == {"redacted": True, "has_value": True}
    assert auth["baseUrl"] == "http://h:7113/v1"
    assert "sk-secret" not in res.text

    # PUT merge with *** preserves the secret.
    res = client.put(
        "/api/coding-cli/qwen-code/settings",
        json={
            "settings": {
                "security": {"auth": {"apiKey": "***"}},
                "tools": {"useBuiltinRipgrep": False},
            },
        },
    )
    assert res.status_code == 200
    on_disk = json.loads((qwen_dir / "settings.json").read_text())
    assert on_disk["security"]["auth"]["apiKey"] == "sk-secret"
    assert on_disk["tools"]["useBuiltinRipgrep"] is False
    assert on_disk["model"]["name"] == "qwen3.6-27b-fp8"


def test_settings_write_creates_file(client, tmp_path) -> None:
    res = client.put(
        "/api/coding-cli/opencode/settings",
        json={"settings": {"$schema": 1}},
    )
    assert res.status_code == 200
    assert (tmp_path / ".config/opencode/opencode.json").is_file()


def test_install_post_returns_202(client) -> None:
    res = client.post(
        "/api/coding-cli/qwen-code/install",
        json={"tag": "0.25.0"},
    )
    assert res.status_code == 202
    body = res.json()
    assert body["cli"] == "qwen-code"
    assert body["tag"] == "0.25.0"
    assert body["task_id"]


def test_install_lifecycle(client) -> None:
    """Drive the install state machine deterministically on one loop."""
    import asyncio

    from qwenpaw.coding_cli.registry import get_cli

    service = client.app.state.coding_cli_service
    spec = get_cli("qwen-code")

    async def drive() -> dict:
        task_id = await service.start_install(spec, "0.25.0")
        for _ in range(100):
            task = service.install_status(task_id)
            if task and task["state"] != "running":
                return task
            await asyncio.sleep(0.02)
        return service.install_status(task_id)

    with patch(
        "qwenpaw.coding_cli.service.CodingCliService._run",
        return_value=SimpleNamespace(
            returncode=0,
            stdout="qwen 0.25.0",
            stderr="",
        ),
    ), patch(
        "qwenpaw.coding_cli.service.CodingCliService._installable",
        return_value=True,
    ):
        task = asyncio.run(drive())

    assert task["state"] == "success"
    assert task["version"] == "0.25.0"
    res = client.get(f"/api/coding-cli/qwen-code/install/{task['task_id']}")
    assert res.status_code == 200
    assert res.json()["state"] == "success"


def test_install_nightly_tag_uses_dist_tag(client) -> None:
    """A dist-tag like ``nightly`` must be appended as ``pkg@nightly``,
    not silently dropped to latest."""
    from qwenpaw.coding_cli.registry import get_cli

    service = client.app.state.coding_cli_service
    spec = get_cli("qwen-code")
    calls: list = []

    def fake_run(cmd, timeout=30.0):
        calls.append(cmd)
        return SimpleNamespace(returncode=0, stdout="qwen 0.25.0", stderr="")

    import asyncio

    async def drive() -> None:
        task_id = await service.start_install(spec, "nightly")
        for _ in range(100):
            task = service.install_status(task_id)
            if task and task["state"] != "running":
                return
            await asyncio.sleep(0.02)

    with patch.object(
        CodingCliService,
        "_run",
        staticmethod(fake_run),
    ), patch.object(CodingCliService, "_installable", return_value=True):
        asyncio.run(drive())

    assert ("npm", "install", "-g", "@qwen-code/qwen-code@nightly") in calls


def test_install_invalid_tag_400(client) -> None:
    res = client.post(
        "/api/coding-cli/qwen-code/install",
        json={"tag": "latest; rm -rf /"},
    )
    assert res.status_code == 400


def test_opencode_auth_probe_without_settings_file(client, tmp_path) -> None:
    """opencode keeps credentials in auth.json; the probe must report
    configured=True even when opencode.json does not exist."""
    auth_dir = tmp_path / ".local/share/opencode"
    auth_dir.mkdir(parents=True)
    (auth_dir / "auth.json").write_text("{}")
    res = client.get("/api/coding-cli")
    items = {item["id"]: item for item in res.json()["clis"]}
    assert items["opencode"]["auth"]["configured"] is True


def test_install_busy_409(client) -> None:
    service = client.app.state.coding_cli_service
    service._busy.add("qwen-code")
    res = client.post(
        "/api/coding-cli/qwen-code/install",
        json={"tag": "latest"},
    )
    assert res.status_code == 409
    service._busy.discard("qwen-code")


def test_install_task_404(client) -> None:
    assert (
        client.get(
            "/api/coding-cli/qwen-code/install/nope",
        ).status_code
        == 404
    )
