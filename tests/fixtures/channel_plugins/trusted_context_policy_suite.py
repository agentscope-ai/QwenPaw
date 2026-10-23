"""Host-only policy controls; no invented catalog ownership."""
from copy import deepcopy

import pytest

from qwenpaw.plugins.official_execution_context import (
    project_official_execution,
)


def project(key, config, tmp_path, **kwargs):
    return project_official_execution(
        key,
        config,
        working_dir=tmp_path,
        legacy_state_dir=tmp_path / "legacy",
        environment={
            "QQ_API_BASE": "",
            "QQ_TOKEN_URL": "token",
            "QQ_PORTAL_HOST": "portal",
            "DASHSCOPE_API_KEY": "env-key",
            "UNRELATED": "no",
        },
        **kwargs,
    )


def test_policy_selects_exact_keys_preserves_defaults_and_detaches(tmp_path):
    raw = {"nested": {"items": [1]}}
    saved = deepcopy(raw)
    values, env = project("qq", raw, tmp_path)
    assert env == {
        "QQ_API_BASE": "",
        "QQ_TOKEN_URL": "token",
        "QQ_PORTAL_HOST": "portal",
    }
    values["nested"]["items"].append(2)
    assert raw == saved
    for owner in ("fixture.third_party", "unknown"):
        values, env = project(owner, raw, tmp_path)
        assert values == raw and env == {}
    assert (
        project("sip", {"dashscope_api_key": "explicit"}, tmp_path)[0][
            "dashscope_api_key"
        ]
        == "explicit"
    )
    assert project("sip", {"dashscope_api_key": ""}, tmp_path) == (
        {"dashscope_api_key": "env-key"},
        {},
    )


def test_paths_preserve_tilde_and_symlink_sensitive_lexical_parent(
    tmp_path, monkeypatch
):
    home = tmp_path / "home"
    home.mkdir()
    target = tmp_path / "other" / "target"
    target.mkdir(parents=True)
    (tmp_path / "link").symlink_to(target, target_is_directory=True)
    monkeypatch.setenv("HOME", str(home))
    config = {
        "db_path": "~/Library/Messages/chat.db",
        "media_dir": "link/../media",
    }
    saved = deepcopy(config)
    values, env = project("imessage", config, tmp_path)
    assert values["db_path"] == str(home / "Library/Messages/chat.db")
    assert values["media_dir"] == str(tmp_path / "link/../media")
    assert values["media_dir"] != str((tmp_path / "link/../media").resolve())
    assert config == saved and env == {}
    default, _ = project("imessage", {}, tmp_path)
    assert default["db_path"] == str(home / "Library/Messages/chat.db")
    assert default["media_dir"] == str(tmp_path / "legacy/media")
    workspace, _ = project(
        "imessage", {}, tmp_path, workspace_dir=tmp_path / "workspace"
    )
    assert "media_dir" not in workspace


@pytest.mark.parametrize("key", ["matrix", "azure_bot"])
def test_legacy_root_overrides_client_claim_without_mutating_saved_config(
    tmp_path, key
):
    config = {"legacy_state_dir": "client-owned-untrusted"}
    values, env = project(key, config, tmp_path)
    assert values["legacy_state_dir"] == str(tmp_path / "legacy") and env == {}
    assert config == {"legacy_state_dir": "client-owned-untrusted"}


def test_wechat_uses_same_lexical_host_token_path(tmp_path):
    raw = {"bot_token_file": "link/../token", "media_dir": "media"}
    values, env = project("wechat", raw, tmp_path)
    assert values["bot_token_file"] == str(tmp_path / "link/../token")
    assert values["media_dir"] == str(tmp_path / "media") and env == {}
    assert project("wechat", {}, tmp_path)[0]["bot_token_file"] == str(
        tmp_path / "legacy/wechat_bot_token"
    )
