# -*- coding: utf-8 -*-
"""Standalone release boundaries, exercised using only the stable SDK."""

import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException, Request

ROOT = Path(__file__).resolve().parents[3]
APP = ROOT / "plugins/apps/qwenpaw-data"
spec = importlib.util.spec_from_file_location(
    "standalone_release",
    APP / "backend/standalone.py",
)
assert spec is not None and spec.loader is not None
standalone = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = standalone
spec.loader.exec_module(standalone)


def request(body=None, headers=(), query=b"", user="alice"):
    async def receive():
        return {"type": "http.request", "body": json.dumps(body).encode()}

    return Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/console/chat",
            "headers": list(headers),
            "query_string": query,
            "state": {"user": user},
        },
        receive,
    )


@pytest.mark.asyncio
async def test_native_admission_passes_scoped_identity_and_private_bindings():
    gateway = SimpleNamespace(
        json=AsyncMock(
            side_effect=[
                {
                    "console_protocol": 1,
                    "scoped_sessions": True,
                    "runtime_model_bindings": True,
                    "dataset_context": True,
                },
                {"chat": {"id": "run"}},
            ],
        ),
    )
    resolver = AsyncMock(return_value={"analysis": {"api_key": "private"}})
    result = await standalone.dispatch_console_chat(
        request(
            {
                "session_id": "session",
                "text": "query",
                "datasource_id": "ds",
                "dataset_names": ["sales"],
            },
        ),
        gateway,
        resolver,
    )
    assert result == {"chat": {"id": "run"}}
    call = gateway.json.call_args
    assert call.args == ("POST", "/api/v1/console/chat")
    assert call.kwargs["body"]["dataset_names"] == ["sales"]
    assert (
        call.kwargs["body"]["runtime_models"]["analysis"]["api_key"]
        == "private"
    )
    assert call.kwargs["user_id"] == standalone.identity_namespace(
        standalone.DataScope(principal_id="alice", workspace_id="default"),
    )
    assert "private" not in json.dumps(result)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "body",
    [
        {"runtime_models": {}},
        {"enable_clarification": False},
        [],
    ],
)
async def test_browser_cannot_override_trusted_bindings(body):
    gateway = SimpleNamespace(json=AsyncMock())
    resolver = AsyncMock()
    with pytest.raises(HTTPException) as error:
        await standalone.dispatch_console_chat(
            request(body),
            gateway,
            resolver,
        )
    assert error.value.status_code == 422
    gateway.json.assert_not_called()
    resolver.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "headers,query",
    [
        ([(b"x-user-id", b"bob")], b""),
        ([], b"user_id=alice&user_id=bob"),
        ([(b"x-agent-id", b"one")], b"agent_id=two"),
        ([(b"x-pawapp-id", b"other")], b""),
        ([(b"x-channel", b"external")], b""),
    ],
)
async def test_conflicting_scope_claims_are_rejected(headers, query):
    with pytest.raises(HTTPException) as error:
        await standalone.console_scope(request(headers=headers, query=query))
    assert error.value.status_code == 403


@pytest.mark.asyncio
async def test_old_engine_fails_before_resolving_credentials():
    gateway = SimpleNamespace(
        json=AsyncMock(return_value={"scoped_sessions": True}),
    )
    resolver = AsyncMock()
    with pytest.raises(HTTPException) as error:
        await standalone.dispatch_console_chat(
            request({"text": "hi"}),
            gateway,
            resolver,
        )
    assert error.value.status_code == 503
    resolver.assert_not_called()
    assert gateway.json.call_count == 1


@pytest.mark.asyncio
async def test_stable_sdk_sidecar_environment_is_isolated_and_refreshed(
    tmp_path,
    monkeypatch,
):
    monkeypatch.syspath_prepend(str(APP))
    from backend import service_compat

    monkeypatch.setattr(service_compat, "APP_DATA_DIR", tmp_path)
    monkeypatch.setenv("UNGRANTED_SECRET", "never-in-child")
    monkeypatch.setenv("RELEASE_NETWORK_SETTING", "granted")
    model = {"MODEL_SECRET": "literal-{host}-{port}"}
    (tmp_path / "environment_probe.py").write_text(
        "import os,json; print(json.dumps(dict(os.environ)))",
        encoding="utf-8",
    )
    app = SimpleNamespace(managed_service=lambda name, **kwargs: kwargs)
    service = service_compat.managed_service(
        app,
        "test",
        command=(
            sys.executable,
            "-m",
            "environment_probe",
        ),
        inherit_env=("RELEASE_NETWORK_SETTING",),
        env_factory=lambda: model,
    )
    for key in ("literal-{host}-{port}", "rotated"):
        model["MODEL_SECRET"] = key
        await service["on_before_start"]()
        child = json.loads(
            subprocess.check_output(
                service["command"],
                text=True,
                cwd=tmp_path,
            ),
        )
        assert child["MODEL_SECRET"] == key
        assert child["RELEASE_NETWORK_SETTING"] == "granted"
        assert "UNGRANTED_SECRET" not in child
        assert "MODEL_SECRET" not in os.environ
    if os.name != "nt":
        assert (
            tmp_path / "service-env/test.json"
        ).stat().st_mode & 0o777 == 0o600


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [401, 403, 404, 500])
async def test_capability_errors_never_fall_back(status):
    gateway = SimpleNamespace(
        json=AsyncMock(side_effect=HTTPException(status, "upstream")),
    )
    resolver = AsyncMock()
    with pytest.raises(HTTPException) as error:
        await standalone.dispatch_console_chat(
            request({"text": "hi"}),
            gateway,
            resolver,
        )
    assert error.value.status_code == (503 if status == 404 else status)
    assert gateway.json.call_count == 1
    resolver.assert_not_called()
