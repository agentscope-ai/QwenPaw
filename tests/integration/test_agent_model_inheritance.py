# -*- coding: utf-8 -*-
"""Agent 模型继承的真实 HTTP 与运行时集成验收。"""

from __future__ import annotations

import hashlib
import json
import threading
import time
from http.server import HTTPServer
from pathlib import Path

import pytest

from tests.integration.helpers import (
    MockLLMHandler,
    default_http_timeout,
    delete_agent_quietly,
)

_HTTP_TIMEOUT = default_http_timeout(20.0)


@pytest.fixture(scope="module")
def model_servers():
    """启动两个可通过请求计数区分的本地 OpenAI 兼容服务。"""
    servers = []
    for _ in range(2):
        server = HTTPServer(("127.0.0.1", 0), MockLLMHandler)
        server.force_error = False
        server.force_tool_call = False
        server.request_count = 0
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        servers.append(
            (
                server,
                f"http://127.0.0.1:{server.server_address[1]}/v1",
            ),
        )
    yield servers
    for server, _url in servers:
        server.shutdown()


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _wait_config_stable(path: Path) -> str:
    """等待首次启动迁移完成，再记录模型切换前的稳定配置哈希。"""
    deadline = time.time() + 10.0
    previous = None
    stable_since = None
    while time.time() < deadline:
        current = _sha256(path)
        if current == previous:
            stable_since = stable_since or time.time()
            if time.time() - stable_since >= 1.0:
                return current
        else:
            previous = current
            stable_since = None
        time.sleep(0.2)
    pytest.fail(f"Agent 配置在 10 秒内未稳定：{path}")
    return ""


def _stable_agent_config(path: Path) -> dict:
    """忽略运行时会补齐的频道默认值，仅比较 Agent 持久化语义。"""
    config = json.loads(path.read_text(encoding="utf-8"))
    config.pop("channels", None)
    return config


def _register_provider(app_server, provider_id: str, base_url: str) -> None:
    create = app_server.api_request(
        "POST",
        "/api/models/custom-providers",
        json={
            "id": provider_id,
            "name": provider_id,
            "default_base_url": base_url,
            "chat_model": "OpenAIChatModel",
            "models": [{"id": "mock-model", "name": "Mock Model"}],
        },
        timeout=_HTTP_TIMEOUT,
    )
    assert create.status_code == 201, app_server.logs_tail()
    configure = app_server.api_request(
        "PUT",
        f"/api/models/{provider_id}/config",
        json={"api_key": "test-key", "base_url": base_url},
        timeout=_HTTP_TIMEOUT,
    )
    assert configure.status_code == 200, app_server.logs_tail()


def _activate(app_server, provider_id: str) -> None:
    response = app_server.api_request(
        "PUT",
        "/api/models/active",
        json={
            "provider_id": provider_id,
            "model": "mock-model",
            "scope": "global",
        },
        timeout=_HTTP_TIMEOUT,
    )
    assert response.status_code == 200, app_server.logs_tail()


def _create_agent(
    app_server,
    agent_id: str,
    *,
    active_model: dict[str, str] | None,
) -> Path:
    payload = {
        "id": agent_id,
        "name": agent_id,
        "description": "Task 4.5-C/2-D isolated acceptance",
    }
    if active_model is not None:
        payload["active_model"] = active_model
    response = app_server.api_request(
        "POST",
        "/api/agents",
        json=payload,
        timeout=_HTTP_TIMEOUT,
    )
    assert response.status_code == 201, app_server.logs_tail()
    return Path(response.json()["workspace_dir"]) / "agent.json"


def _wait_agent_ready(app_server, agent_id: str) -> None:
    deadline = time.time() + 30.0
    last = None
    while time.time() < deadline:
        response = app_server.api_request(
            "GET",
            "/api/agents",
            timeout=_HTTP_TIMEOUT,
        )
        assert response.status_code == 200, app_server.logs_tail()
        last = next(
            (item for item in response.json()["agents"] if item["id"] == agent_id),
            None,
        )
        if last and last.get("startup_status") in {"running", "ready"}:
            return
        time.sleep(0.25)
    pytest.fail(f"Agent 未在 30 秒内就绪：{last}\n{app_server.logs_tail()}")


def _run_chat(app_server, agent_id: str, session_id: str) -> None:
    _wait_agent_ready(app_server, agent_id)
    submit = app_server.api_request(
        "POST",
        "/api/console/chat/task",
        headers={"X-Agent-Id": agent_id},
        json={
            "channel": "console",
            "user_id": f"user-{session_id}",
            "session_id": session_id,
            "input": [
                {
                    "role": "user",
                    "type": "message",
                    "content": [{"type": "text", "text": "ping"}],
                },
            ],
        },
        timeout=_HTTP_TIMEOUT,
    )
    assert submit.status_code == 200, app_server.logs_tail()
    task_id = submit.json()["task_id"]
    deadline = time.time() + 30.0
    last = None
    while time.time() < deadline:
        response = app_server.api_request(
            "GET",
            f"/api/console/chat/task/{task_id}",
            headers={"X-Agent-Id": agent_id},
            timeout=_HTTP_TIMEOUT,
        )
        assert response.status_code == 200, app_server.logs_tail()
        last = response.json()
        if last.get("status") == "finished":
            assert (last.get("result") or {}).get("status") == "completed", last
            return
        time.sleep(0.25)
    pytest.fail(f"聊天任务未完成：{last}\n{app_server.logs_tail()}")


@pytest.mark.integration
@pytest.mark.p0
def test_00_inherited_create_without_global_model_has_no_residue(
    app_server,
) -> None:
    """无全局默认模型时，继承型创建失败且不留下文件或配置记录。"""
    agent_id = "integ-inherit-no-global"
    workspace = app_server.working_dir / "workspaces" / agent_id
    response = app_server.api_request(
        "POST",
        "/api/agents",
        json={"id": agent_id, "name": agent_id},
        timeout=_HTTP_TIMEOUT,
    )
    assert response.status_code == 400, app_server.logs_tail()
    assert not workspace.exists()
    listed = app_server.api_request("GET", "/api/agents", timeout=_HTTP_TIMEOUT)
    assert agent_id not in {item["id"] for item in listed.json()["agents"]}


@pytest.mark.integration
@pytest.mark.p0
def test_inherited_agent_follows_global_model_without_rewriting_config(
    app_server,
    model_servers,
) -> None:
    """继承型 Agent 切换全局模型后改变真实运行供应商，但配置哈希不变。"""
    (server_a, url_a), (server_b, url_b) = model_servers
    provider_a = "integ-inherit-a"
    provider_b = "integ-inherit-b"
    agent_id = "integ-inherited-runtime"
    try:
        _register_provider(app_server, provider_a, url_a)
        _register_provider(app_server, provider_b, url_b)
        _activate(app_server, provider_a)
        config_path = _create_agent(app_server, agent_id, active_model=None)
        _run_chat(app_server, agent_id, "inherit-a")
        assert server_a.request_count >= 1
        requests_a = server_a.request_count

        _activate(app_server, provider_b)
        _run_chat(app_server, agent_id, "inherit-b")
        assert server_b.request_count >= 1
        assert server_a.request_count == requests_a

        # 首次热重载可能补齐历史频道默认字段。待该一次性迁移稳定后，
        # 再验证后续全局模型切换不会改写 Agent 配置。
        _wait_config_stable(config_path)
        before_switch_config = _stable_agent_config(config_path)
        requests_b = server_b.request_count
        _activate(app_server, provider_a)
        _wait_config_stable(config_path)
        assert _stable_agent_config(config_path) == before_switch_config
        _run_chat(app_server, agent_id, "inherit-a-again")
        assert server_a.request_count > requests_a
        assert server_b.request_count == requests_b

        profile = app_server.api_request(
            "GET",
            f"/api/agents/{agent_id}",
            timeout=_HTTP_TIMEOUT,
        ).json()
        assert profile.get("active_model") is None
    finally:
        delete_agent_quietly(app_server, agent_id)


@pytest.mark.integration
@pytest.mark.p0
def test_explicit_agent_stays_fixed_then_clear_restores_inheritance(
    app_server,
    model_servers,
) -> None:
    """显式型 Agent 不随全局切换；清空后恢复继承并走新全局供应商。"""
    (server_a, url_a), (server_b, url_b) = model_servers
    provider_a = "integ-explicit-a"
    provider_b = "integ-explicit-b"
    agent_id = "integ-explicit-runtime"
    explicit = {"provider_id": provider_a, "model": "mock-model"}
    try:
        _register_provider(app_server, provider_a, url_a)
        _register_provider(app_server, provider_b, url_b)
        _activate(app_server, provider_b)
        _create_agent(app_server, agent_id, active_model=explicit)

        before_a = server_a.request_count
        before_b = server_b.request_count
        _run_chat(app_server, agent_id, "explicit-fixed")
        assert server_a.request_count > before_a
        assert server_b.request_count == before_b

        profile_response = app_server.api_request(
            "GET",
            f"/api/agents/{agent_id}",
            timeout=_HTTP_TIMEOUT,
        )
        profile = profile_response.json()
        assert profile["active_model"] == explicit
        profile["active_model"] = None
        update = app_server.api_request(
            "PUT",
            f"/api/agents/{agent_id}",
            json=profile,
            timeout=_HTTP_TIMEOUT,
        )
        assert update.status_code == 200, app_server.logs_tail()

        before_b = server_b.request_count
        _run_chat(app_server, agent_id, "explicit-cleared")
        assert server_b.request_count > before_b
        assert update.json().get("active_model") is None
    finally:
        delete_agent_quietly(app_server, agent_id)
