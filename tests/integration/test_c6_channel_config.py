# -*- coding: utf-8 -*-
# pylint: disable=redefined-outer-name
"""C6 config acceptance through the real app and isolated saved profiles."""

import pytest

APP_SERVER_EXTRA_ENV = {"QWENPAW_ENABLED_CHANNELS": "console"}


@pytest.fixture
def c6_agent(app_server):
    agent_id = "c6_channel_config"
    response = app_server.api_request(
        "POST",
        "/api/agents",
        json={"id": agent_id, "name": agent_id},
    )
    assert response.status_code == 201, app_server.logs_tail()
    endpoint = f"/api/agents/{agent_id}/config/channels"
    saved = {
        "feishu": {
            "enabled": False,
            "app_id": "cli_saved",
            "app_secret": "test-only-feishu",
            "domain": "lark",
            "media_dir": None,
        },
        "dingtalk": {
            "enabled": False,
            "client_id": "saved-client",
            "client_secret": "test-only-dingtalk",
            "message_type": "card",
            "card_template_id": "saved-card",
            "card_template_key": "body",
        },
        "removed_plugin": {
            "enabled": False,
            "token": "test-only-custom",
            "options": {"retries": 3},
        },
    }
    response = app_server.api_request("PUT", endpoint, json=saved)
    assert response.status_code == 200, app_server.logs_tail()
    headers = {"X-Agent-Id": agent_id}
    response = app_server.api_request(
        "POST",
        "/api/access-control/whitelist/add",
        headers=headers,
        json={"entries": [{"channel": "feishu", "user_id": "user-a"}]},
    )
    assert response.status_code == 200, app_server.logs_tail()
    response = app_server.api_request(
        "GET",
        "/api/access-control/feishu",
        headers=headers,
    )
    assert response.status_code == 200, response.text
    assert response.json()["whitelist"] == {
        "user-a": {"remark": "", "username": ""},
    }
    response = app_server.api_request("GET", f"/api/agents/{agent_id}")
    assert response.status_code == 200, response.text
    baseline = response.json()["channels"]
    try:
        yield app_server, agent_id, endpoint, baseline
    finally:
        app_server.api_request("DELETE", f"/api/agents/{agent_id}")


def test_c6_omitted_channels_keep_exact_saved_values(c6_agent):
    server, agent_id, endpoint, baseline = c6_agent
    response = server.api_request(
        "PUT",
        endpoint,
        json={"console": {"enabled": False}},
    )
    assert response.status_code == 200, server.logs_tail()
    stored = server.api_request("GET", f"/api/agents/{agent_id}").json()[
        "channels"
    ]
    for key in ("feishu", "dingtalk", "removed_plugin"):
        assert stored.get(key) == baseline[key], key
    assert stored["console"]["enabled"] is True


def test_c6_runtime_gates_do_not_hide_editable_saved_configs(c6_agent):
    server, _agent_id, endpoint, _baseline = c6_agent
    configs = server.api_request("GET", endpoint).json()
    types = server.api_request("GET", endpoint + "/types").json()
    schemas = server.api_request("GET", endpoint + "/schemas").json()
    for key in ("feishu", "dingtalk", "removed_plugin"):
        assert key in configs and key in types and key in schemas, key
        response = server.api_request("GET", endpoint + "/" + key)
        assert response.status_code == 200, response.text
    for key in ("feishu", "dingtalk"):
        assert configs[key]["isBuiltin"] is False
        assert schemas[key]["owner"] == key
        assert schemas[key]["process_mode"] == "runner_process"
        assert schemas[key]["availability"] == "missing_code"
        assert schemas[key]["repair"]["plugin_id"] == key


def test_c6_official_config_validation_is_http_422(c6_agent):
    server, _agent_id, endpoint, baseline = c6_agent
    response = server.api_request(
        "PUT",
        endpoint + "/feishu",
        json={**baseline["feishu"], "domain": "invalid-region"},
    )
    assert response.status_code == 422, response.text


def test_c6_uninstalled_custom_settings_stay_editable(c6_agent):
    server, agent_id, endpoint, _baseline = c6_agent
    changed = {"enabled": False, "options": {"retries": 9}, "token": "new"}
    response = server.api_request(
        "PUT",
        endpoint + "/removed_plugin",
        json=changed,
    )
    assert response.status_code == 200, response.text
    stored = server.api_request("GET", f"/api/agents/{agent_id}").json()
    assert stored["channels"]["removed_plugin"] == changed


@pytest.mark.parametrize("single", [False, True])
def test_c6_catalog_metadata_never_persists_on_config_put(c6_agent, single):
    server, agent_id, endpoint, baseline = c6_agent
    metadata = {
        "isBuiltin": False,
        "availability": "failed",
        "owner": "wrong",
        "repair": {"fake": True},
        "config_schema": {"type": "object"},
        "process_mode": "in_process",
    }
    config = {**baseline["feishu"], **metadata}
    target = endpoint + "/feishu" if single else endpoint
    response = server.api_request(
        "PUT",
        target,
        json=config if single else {"feishu": config},
    )
    assert response.status_code == 200, response.text
    saved = server.api_request("GET", f"/api/agents/{agent_id}").json()[
        "channels"
    ]["feishu"]
    assert saved == baseline["feishu"]
    acl = server.api_request(
        "GET",
        "/api/access-control/feishu",
        headers={"X-Agent-Id": agent_id},
    )
    assert acl.status_code == 200, acl.text
    assert acl.json()["whitelist"] == {
        "user-a": {"remark": "", "username": ""},
    }
