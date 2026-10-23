"""Host-path projection controls; execute only after the Source freeze."""

import copy
import json
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[3]


def project(key, saved, host, legacy, workspace=None):
    from qwenpaw.plugins.official_execution_context import (
        project_official_execution,
    )

    return project_official_execution(
        key,
        saved,
        working_dir=host,
        legacy_state_dir=legacy,
        environment={},
        workspace_dir=workspace,
    )


@pytest.mark.parametrize("kind", ["absolute", "tilde", "lexical", "symlink"])
def test_onebot_explicit_path_preserves_host_lexical_meaning(
    tmp_path, monkeypatch, kind
):
    host, home, legacy = (
        tmp_path / name for name in ("cwd", "home", "legacy")
    )
    host.mkdir()
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    target = tmp_path / "outside"
    target.mkdir()
    (host / "link").symlink_to(target, target_is_directory=True)
    raw, expected = {
        "absolute": (str(tmp_path / "explicit"), str(tmp_path / "explicit")),
        "tilde": ("~/saved-media", str(home / "saved-media")),
        "lexical": ("missing/../media", str(host / "missing/../media")),
        "symlink": ("link/../media", str(host / "link/../media")),
    }[kind]
    saved = {"media_dir": raw, "custom": {"value": [1]}}
    before = copy.deepcopy(saved)
    values, environment = project("onebot", saved, host, legacy)
    assert values["media_dir"] == expected
    assert environment == {} and saved == before
    values["custom"]["value"].append(2)
    assert saved == before
    assert not Path(expected).exists()


@pytest.mark.parametrize("value", ["", None])
def test_onebot_empty_media_keeps_runtime_default_choice(tmp_path, value):
    saved = {"media_dir": value}
    values, environment = project(
        "onebot",
        saved,
        tmp_path / "host",
        tmp_path / "legacy",
        tmp_path / "workspace",
    )
    assert values == saved == {"media_dir": value}
    assert environment == {}
    assert not (tmp_path / "workspace").exists()


def test_onebot_absent_media_is_not_materialized(tmp_path):
    values, environment = project(
        "onebot", {}, tmp_path / "host", tmp_path / "legacy"
    )
    assert values == {} and environment == {}
    assert not (tmp_path / "legacy").exists()


def test_same_channel_key_third_party_keeps_own_relative_business_field(
    tmp_path, monkeypatch
):
    from extension_sample import sample_source
    from qwenpaw.plugins.architecture import PluginManifest
    from qwenpaw.plugins.channel_adapter import describe_channel
    from qwenpaw.runtime.runtime import Runtime
    from qwenpaw.__version__ import __version__

    source = sample_source(tmp_path / "source", "onebot_shadow")
    descriptor_path = source / "channel.json"
    descriptor = json.loads(descriptor_path.read_text())
    descriptor["channel_key"] = "onebot"
    descriptor["config_schema"]["properties"]["media_dir"] = {"type": "string"}
    descriptor["config_fields"].append("media_dir")
    descriptor_path.write_text(json.dumps(descriptor))
    manifest = PluginManifest.from_dict(
        json.loads((source / "plugin.json").read_text())
    )
    with pytest.raises(ValueError, match="owner 'onebot' conflicts"):
        describe_channel(source, manifest)
    descriptor["channel_key"] = "onebot_shadow"
    descriptor_path.write_text(json.dumps(descriptor))
    description = describe_channel(source, manifest)
    host = tmp_path / "cwd"
    host.mkdir()
    monkeypatch.chdir(host)
    saved = {"enabled": False, "media_dir": "third-party-relative"}
    proxy = description.create_proxy(
        Runtime.run,
        saved,
        python_executable=sys.executable,
        support_root=ROOT / "src",
        instance_id="third-party-path",
        generation=1,
        qwenpaw_version=__version__,
        workspace_dir=tmp_path / "workspace",
    )
    assert proxy._launch_spec.plugin_id == "onebot_shadow"
    assert proxy._launch_spec.config["media_dir"] == "third-party-relative"
    assert saved == {"enabled": False, "media_dir": "third-party-relative"}
    assert proxy.channel_process.health_snapshot()["pid"] is None
    assert not (host / "third-party-relative").exists()
    from qwenpaw.plugins.official_execution_context import (
        prepare_official_execution,
    )

    values, environment = prepare_official_execution(
        "onebot",
        saved,
        official=None,
        working_dir=host,
        legacy_state_dir=None,
        environment={},
    )
    assert values == saved and environment == {}


# OneBot is the separately retained original failing node. These14 + that node
# cover all15 consumers without repeating the OneBot original assertion.
@pytest.mark.parametrize(
    "key",
    [
        "telegram",
        "slack",
        "discord",
        "mattermost",
        "dingtalk",
        "feishu",
        "qq",
        "wecom",
        "yuanbao",
        "xiaoyi",
        "wechat",
        "matrix",
        "imessage",
        "azure_bot",
    ],
)
def test_actual_official_family_factory_binds_media_path_without_start(
    tmp_path, monkeypatch, key
):
    import importlib.abc

    from qwenpaw.__version__ import __version__
    from qwenpaw.plugins.architecture import PluginManifest
    from qwenpaw.plugins.channel_adapter import describe_channel
    from qwenpaw.plugins.official_channels import bundled_channel_source
    from qwenpaw.runtime.runtime import Runtime

    class NoPrivateImport(importlib.abc.MetaPathFinder):
        def find_spec(self, fullname, path=None, target=None):
            if fullname.startswith("qwenpaw_channel_"):
                raise AssertionError(
                    "passive factory imported private channel"
                )

    monkeypatch.setattr(sys, "meta_path", [NoPrivateImport(), *sys.meta_path])
    host = tmp_path / "host-cwd"
    host.mkdir()
    monkeypatch.chdir(host)
    saved = {"enabled": False, "media_dir": "saved-media"}
    with bundled_channel_source(
        "azure-bot" if key == "azure_bot" else key
    ) as source:
        description = describe_channel(
            source,
            PluginManifest.from_dict(
                json.loads((source / "plugin.json").read_text())
            ),
        )
        proxy = description.create_proxy(
            Runtime.run,
            saved,
            python_executable=sys.executable,
            support_root=ROOT / "src",
            instance_id="official-path-" + key,
            generation=1,
            qwenpaw_version=__version__,
            workspace_dir=tmp_path / "workspace",
        )
        assert proxy._launch_spec.config["media_dir"] == str(
            host / "saved-media"
        )
        assert proxy.channel_process.health_snapshot()["pid"] is None
        assert saved == {"enabled": False, "media_dir": "saved-media"}
        assert not (host / "saved-media").exists()
        assert not (tmp_path / "workspace").exists()


@pytest.mark.parametrize("key", ["mqtt", "voice", "sip"])
def test_non_media_consumer_projection_does_not_invent_media_default(
    tmp_path, key
):
    values, environment = project(key, {}, tmp_path, tmp_path / "legacy")
    assert "media_dir" not in values
    assert environment == {}
    assert not (tmp_path / "legacy").exists()
