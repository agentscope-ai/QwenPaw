"""W2 static resolver against real detached config files and request headers."""

from importlib import import_module

from fastapi import FastAPI, HTTPException, Request
import pytest

from qwenpaw.config.config import load_agent_config, save_agent_config
from qwenpaw.config.utils import save_config
from wechat_w2_config_support import write_profiles


def resolver():
    return import_module(
        "qwenpaw.app.channels.qrcode_sessions"
    ).resolve_channel_management_scope


def request(*, state_agent=None, header=None):
    headers = [(b"x-agent-id", header.encode())] if header else []
    value = Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/config/channels/wechat/qrcode",
            "headers": headers,
            "query_string": b"principal_id=untrusted-query-user",
            "app": FastAPI(),
        }
    )
    if state_agent:
        value.state.agent_id = state_agent
    return value


@pytest.mark.parametrize(
    "state_agent,header,active,expected",
    [
        ("A", "B", "B", "A"),
        (None, "A", "B", "A"),
        (None, None, "B", "B"),
        (None, None, "", "default"),
    ],
)
def test_static_resolution_precedence_needs_no_workspace_or_agent_manager(
    tmp_path,
    monkeypatch,
    state_agent,
    header,
    active,
    expected,
):
    _, paths = write_profiles(
        tmp_path,
        monkeypatch,
        "wechat",
        {
            "enabled": False,
            "base_url": "https://wx.test",
        },
        active=active,
    )
    scope = resolver()(
        request(state_agent=state_agent, header=header), "wechat"
    )
    assert scope.workspace_id == expected
    assert scope.workspace_dir == paths[expected].resolve()
    assert scope.channel_key == "wechat"
    assert scope.principal_id is None
    assert scope.config["base_url"] == "https://wx.test"


def test_resolver_keeps_selected_id_but_normalizes_physical_workspace(
    tmp_path,
    monkeypatch,
):
    _, paths = write_profiles(
        tmp_path, monkeypatch, "wechat", {}, shared_path=True
    )
    a = resolver()(request(header="A"), "wechat")
    b = resolver()(request(header="B"), "wechat")
    assert a.workspace_id != b.workspace_id
    assert a.workspace_dir == b.workspace_dir == paths["A"].resolve()


def test_scope_config_is_detached_from_later_disk_changes(
    tmp_path, monkeypatch
):
    write_profiles(
        tmp_path, monkeypatch, "wechat", {"base_url": "https://old.test"}
    )
    scope = resolver()(request(header="A"), "wechat")
    profile = load_agent_config("A")
    profile.channels.wechat.base_url = "https://new.test"
    save_agent_config("A", profile)
    assert scope.config["base_url"] == "https://old.test"
    assert (
        load_agent_config("A").channels.wechat.base_url == "https://new.test"
    )


@pytest.mark.parametrize("missing", [False, True])
def test_unknown_or_disabled_profile_is_refused_without_agent_start(
    tmp_path,
    monkeypatch,
    missing,
):
    config, _ = write_profiles(tmp_path, monkeypatch, "wechat", {})
    if not missing:
        config.agents.profiles["A"].enabled = False
        save_config(config)
    with pytest.raises(HTTPException) as denied:
        resolver()(request(header="missing" if missing else "A"), "wechat")
    assert denied.value.status_code in (403, 404)
