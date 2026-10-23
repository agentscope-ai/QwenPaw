"""Static all18 resource proof and historical environment-reader oracles."""

import importlib.abc
import json
import sys
import tomllib

import pytest

import official_g1_suite as core

registry = core.registry


def test_all18_actual_resources_are_exact_rebuild_and_requirement_union(
    tmp_path,
):
    from qwenpaw.__version__ import __version__
    from qwenpaw.plugins.official_channel_catalog import OFFICIAL_CHANNELS

    assert len(OFFICIAL_CHANNELS) == 18
    requirements = set()
    for row in OFFICIAL_CHANNELS:
        path = (
            core.ROOT
            / "plugins/channel"
            / row["source_dir"]
            / "requirements.txt"
        )
        requirements.update(
            line.strip()
            for line in path.read_text().splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        )
    project = tomllib.loads((core.ROOT / "pyproject.toml").read_text())
    assert len(requirements) == 37
    assert (
        set(project["project"]["optional-dependencies"]["channels"])
        == requirements
    )
    defaults = project["project"]["dependencies"]
    assert not any(
        value.split("[", 1)[0].split(">", 1)[0].split("=", 1)[0].lower()
        in {"twilio", "wecom-aibot-python-sdk", "matrix-nio"}
        for value in defaults
    )
    assert project["project"]["optional-dependencies"]["matrix-e2ee"] == [
        "matrix-nio[e2e]>=0.25.0"
    ]
    built = core.packager().build_official_channel_bundle(
        core.ROOT,
        tmp_path / "resources",
        host_version=__version__,
    )
    approved = core.ROOT / "src/qwenpaw/official_channels"
    assert built.read_bytes() == (approved / "index.json").read_bytes()
    index = json.loads(built.read_text())
    assert len(index["plugins"]) == 18
    assert {row["plugin_id"] for row in index["plugins"]} == {
        row["plugin_id"] for row in OFFICIAL_CHANNELS
    }
    for row in index["plugins"]:
        assert (built.parent / row["filename"]).read_bytes() == (
            approved / row["filename"]
        ).read_bytes()


def test_old_registry_entrypoint_loads_only_console_with_all18_reserved(
    registry, monkeypatch
):
    from qwenpaw.app.channels import registry as channels
    from qwenpaw.plugins.official_channel_catalog import (
        official_channel_owners,
    )

    names = set(official_channel_owners())
    assert len(names) == 18
    assert set(channels._BUILTIN_SPECS) == {"console"}
    attempts = []

    class NoLegacy(importlib.abc.MetaPathFinder):
        def find_spec(self, fullname, path=None, target=None):
            for name in names:
                prefix = "qwenpaw.app.channels." + name
                if fullname == prefix or fullname.startswith(prefix + "."):
                    attempts.append(fullname)
                    raise AssertionError(
                        "retired entrypoint imported legacy channel"
                    )

    monkeypatch.setattr(sys, "meta_path", [NoLegacy(), *sys.meta_path])
    monkeypatch.setattr(channels, "_BUILTIN_CHANNEL_CACHE", None)
    assert channels.selected_process_channels() == frozenset(names)
    loaded = channels.get_channel_registry()
    assert set(loaded) == {"console"}
    assert loaded["console"].__module__.startswith(
        "qwenpaw.app.channels.console"
    )
    assert registry.get_registered_channels() == {}
    assert attempts == []


@pytest.mark.parametrize(
    "key,enabled",
    [
        ("qq", True),
        ("yuanbao", True),
        ("imessage", True),
        ("matrix", True),
        ("xiaoyi", False),
        ("wechat", False),
        ("wecom", False),
        ("onebot", False),
    ],
)
def test_remaining_readers_preserve_original_enabled_defaults_and_exact_one(
    key, enabled
):
    from qwenpaw.config.channel_env import read_channel_env

    assert read_channel_env(key, {})["enabled"] is enabled
    assert read_channel_env(key, {key.upper() + "_CHANNEL_ENABLED": "true"})[
        "enabled"
    ] is (key == "matrix")
    assert (
        read_channel_env(key, {key.upper() + "_CHANNEL_ENABLED": "1"})[
            "enabled"
        ]
        is True
    )


@pytest.mark.parametrize(
    "value,expected",
    [
        (" YES ", True),
        ("on", True),
        ("TrUe", True),
        ("1", True),
        ("0", False),
        ("false", False),
    ],
)
def test_qq_legacy_markdown_parser_is_distinct_from_enabled_flag(
    value, expected
):
    from qwenpaw.config.channel_env import read_channel_env

    assert (
        read_channel_env("qq", {"QQ_MARKDOWN_ENABLED": value})[
            "markdown_enabled"
        ]
        is expected
    )


def test_remaining_reader_special_fields_match_historical_factory_oracles():
    from qwenpaw.config.channel_env import read_channel_env

    matrix = read_channel_env(
        "matrix",
        {
            "HICLAW_MATRIX_SERVER": "https://matrix.invalid///",
            "HICLAW_MATRIX_TOKEN": "historical",
            "MATRIX_HOMESERVER": "ignored",
            "MATRIX_ACCESS_TOKEN": "ignored",
            "MATRIX_VISION_ENABLED": "1",
        },
    )
    assert matrix == {
        "enabled": True,
        "vision_enabled": False,
        "homeserver": "https://matrix.invalid",
        "access_token": "historical",
    }
    xiaoyi = read_channel_env(
        "xiaoyi",
        {
            "XIAOYI_AK": "ak",
            "XIAOYI_SK": "sk",
            "XIAOYI_AGENT_ID": "agent",
            "XIAOYI_MEDIA_DIR": "runtime-media",
            "XIAOYI_WS_URL": "ignored",
            "XIAOYI_TASK_TIMEOUT_MS": "123",
        },
    )
    assert xiaoyi == {
        "enabled": False,
        "ak": "ak",
        "sk": "sk",
        "agent_id": "agent",
        "media_dir": "runtime-media",
    }
    assert read_channel_env("onebot", {"ONEBOT_ALLOW_FROM": " a, ,b "})[
        "allow_from"
    ] == [" a", " ", "b "]
    for key in ("wechat", "wecom", "yuanbao", "imessage"):
        assert read_channel_env(key, {key.upper() + "_ALLOW_FROM": " a, ,b "})[
            "allow_from"
        ] == ["a", "b"]
    wecom = read_channel_env(
        "wecom",
        {
            "WECOM_MAX_RECONNECT_ATTEMPTS": "-9",
            "WECOM_WS_URL": "wss://offline.invalid",
            "WECOM_SHARE_SESSION_IN_GROUP": "0",
        },
    )
    assert wecom["max_reconnect_attempts"] == -9
    assert wecom["ws_url"] == "wss://offline.invalid"
    assert wecom["share_session_in_group"] is False
    assert read_channel_env("wecom", {})["share_session_in_group"] is True
    assert read_channel_env("wecom", {})["max_reconnect_attempts"] == -1
    imessage = read_channel_env(
        "imessage",
        {"IMESSAGE_POLL_SEC": "0.25", "IMESSAGE_MAX_DECODED_SIZE": "800000"},
    )
    assert (
        imessage["poll_sec"] == 0.25 and imessage["max_decoded_size"] == 800000
    )
    onebot = read_channel_env(
        "onebot",
        {
            "ONEBOT_WS_PORT": "6198",
            "ONEBOT_MEDIA_BASE64_MAX_MB": "11",
            "ONEBOT_MEDIA_DOWNLOAD_MAX_MB": "51",
        },
    )
    assert onebot["ws_port"] == 6198
    assert (
        onebot["media_base64_max_mb"] == 11
        and onebot["media_download_max_mb"] == 51
    )


@pytest.mark.parametrize(
    "key,variable",
    [
        ("imessage", "IMESSAGE_POLL_SEC"),
        ("imessage", "IMESSAGE_MAX_DECODED_SIZE"),
        ("wecom", "WECOM_MAX_RECONNECT_ATTEMPTS"),
        ("onebot", "ONEBOT_WS_PORT"),
    ],
)
def test_historical_invalid_numeric_env_still_raises(key, variable):
    from qwenpaw.config.channel_env import read_channel_env

    with pytest.raises(ValueError):
        read_channel_env(key, {variable: "not-a-number"})


@pytest.mark.parametrize("key", ["voice", "sip", "azure_bot"])
def test_channels_with_no_legacy_env_factory_remain_without_one(key):
    from qwenpaw.config.channel_env import read_channel_env

    assert (
        read_channel_env(key, {key.upper() + "_CHANNEL_ENABLED": "1"}) is None
    )
