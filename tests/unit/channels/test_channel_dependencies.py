# -*- coding: utf-8 -*-
# pylint: disable=protected-access
import asyncio
import json
from importlib.metadata import PackageNotFoundError
import os
from pathlib import Path
import subprocess
import sys
import threading
import time
import tomllib
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from packaging.requirements import Requirement
import pytest
import psutil

from qwenpaw.app.channels.catalog import BUILTIN_CHANNEL_CATALOG, ChannelSpec
from qwenpaw.app.channels.dependencies import (
    ChannelDependencyService,
    InstallJob,
    _channel_site_dir,
    _channel_state_dir,
    _ensure_channel_site_on_path,
    _requirement_state,
    _is_requirement_satisfied,
    _source_pyproject,
    enabled_builtin_channels,
    missing_requirements,
    requirements_for_extra,
    version_mismatch_requirements,
)
from qwenpaw.config.utils import get_available_channels


def test_lazy_runtime_imports_are_declared_in_channel_extras():
    expected = {
        "mattermost": "websockets",
        "qq": "websocket-client",
        "wechat": "pycryptodome",
    }
    for channel, distribution in expected.items():
        spec = BUILTIN_CHANNEL_CATALOG[channel]
        names = {
            Requirement(raw).name.lower()
            for raw in requirements_for_extra(spec.extra)
        }
        assert distribution in names


def test_core_dependencies_are_not_repeated_in_channel_extras():
    pyproject = Path(__file__).resolve().parents[3] / "pyproject.toml"
    project = tomllib.loads(pyproject.read_text(encoding="utf-8"))["project"]
    core = {Requirement(raw).name.lower() for raw in project["dependencies"]}
    extras = project["optional-dependencies"]

    for name, requirements in extras.items():
        if name.startswith("channel-"):
            extra = {Requirement(raw).name.lower() for raw in requirements}
            assert core.isdisjoint(extra)


def test_optional_channel_dependencies_use_verified_pins():
    pyproject = Path(__file__).resolve().parents[3] / "pyproject.toml"
    project = tomllib.loads(pyproject.read_text(encoding="utf-8"))["project"]
    core = {
        Requirement(raw).name.lower(): str(Requirement(raw).specifier)
        for raw in project["dependencies"]
    }
    assert {
        "dingtalk-stream": ">=0.24.3",
        "alibabacloud-dingtalk": ">=2.2.42",
        "python-telegram-bot": ">=20.0",
        "segno": ">=1.6.6",
    }.items() <= core.items()

    expected_extras = {
        "discord": {"discord-py": "==2.7.1"},
        "feishu": {
            "lark-oapi": "==1.7.1",
            "python-socks": "==2.8.2",
        },
        "qq": {"websocket-client": "==1.9.0"},
        "mattermost": {"websockets": "==15.0.1"},
        "slack": {
            "slack-bolt": "==1.30.0",
            "slack-sdk": "==3.43.0",
        },
        "mqtt": {"paho-mqtt": "==2.1.0"},
        "matrix": {
            "matrix-nio": "==0.26.0",
            "python-socks": "==2.8.2",
        },
        "voice": {"twilio": "==9.10.9"},
        "sip": {
            "pyvoip": "==1.6.8",
            "dashscope": "==1.26.4",
            "dashscope-realtime": "==0.1.8",
            "audioop-lts": "==0.2.2",
            "livekit": "==1.1.13",
            "livekit-api": "==1.2.0",
        },
        "wecom": {"wecom-aibot-python-sdk": "==1.0.2"},
        "wechat": {"pycryptodome": "==3.23.0"},
        "yuanbao": {"protobuf": "==7.35.1"},
    }
    for channel, requirements in expected_extras.items():
        spec = BUILTIN_CHANNEL_CATALOG[channel]
        actual = {
            Requirement(raw).name.lower(): str(Requirement(raw).specifier)
            for raw in requirements_for_extra(spec.extra)
        }
        assert actual == requirements


def test_every_catalog_extra_exists_and_channels_all_is_complete():
    pyproject = Path(__file__).resolve().parents[3] / "pyproject.toml"
    data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    extras = data["project"]["optional-dependencies"]
    channel_extras = {
        spec.extra for spec in BUILTIN_CHANNEL_CATALOG.values() if spec.extra
    }

    assert channel_extras <= extras.keys()
    expected = {
        str(Requirement(raw))
        for extra in channel_extras
        for raw in extras[extra]
    }
    actual = {str(Requirement(raw)) for raw in extras["channels-all"]}
    assert actual == expected

    full = Requirement(extras["full"][0])
    assert full.name == "qwenpaw"
    assert set(full.extras) == {"local", "whisper"}


def test_available_channel_keys_do_not_load_builtin_registry():
    plugin_registry = MagicMock()
    plugin_registry.get_registered_channels.return_value = {
        "plugin-channel": object(),
    }
    with (
        patch(
            "qwenpaw.plugins.registry.PluginRegistry",
            return_value=plugin_registry,
        ),
        patch(
            "qwenpaw.app.channels.registry.get_channel_registry",
        ) as load_registry,
        patch.dict(os.environ, {}, clear=True),
    ):
        available = get_available_channels()

    assert "console" in available
    assert "plugin-channel" in available
    load_registry.assert_not_called()


def test_channel_only_sdks_are_not_core_dependencies():
    pyproject = Path(__file__).resolve().parents[3] / "pyproject.toml"
    data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    core = {
        Requirement(raw).name.lower()
        for raw in data["project"]["dependencies"]
    }
    channel_only = {
        "discord-py",
        "lark-oapi",
        "python-socks",
        "websockets",
        "websocket-client",
        "slack-bolt",
        "paho-mqtt",
        "matrix-nio",
        "twilio",
        "pyvoip",
        "dashscope-realtime",
        "livekit",
        "livekit-api",
        "wecom-aibot-python-sdk",
        "pycryptodome",
    }
    assert core.isdisjoint(channel_only)

    assert {
        "alibabacloud-tea-openapi",
        "alibabacloud-credentials",
        "alibabacloud-tea-util",
        "alibabacloud-dingtalk",
        "dingtalk-stream",
        "pillow",
        "python-telegram-bot",
        "segno",
    } <= core


def test_dingtalk_and_telegram_do_not_use_optional_extras():
    assert BUILTIN_CHANNEL_CATALOG["dingtalk"].extra is None
    assert BUILTIN_CHANNEL_CATALOG["telegram"].extra is None


def test_legacy_sip_extras_keep_their_original_scope():
    pyproject = Path(__file__).resolve().parents[3] / "pyproject.toml"
    data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    extras = data["project"]["optional-dependencies"]
    sip = {Requirement(raw).name.lower() for raw in extras["sip"]}
    sip_livekit = {
        Requirement(raw).name.lower() for raw in extras["sip-livekit"]
    }

    assert "livekit" not in sip
    assert "livekit-api" not in sip
    assert {"livekit", "livekit-api", "qwenpaw"} <= sip_livekit

    sip_versions = {
        Requirement(raw).name.lower(): str(Requirement(raw).specifier)
        for raw in extras["sip"]
    }
    assert sip_versions == {
        "pyvoip": "==1.6.8",
        "dashscope": "==1.26.4",
        "dashscope-realtime": "==0.1.8",
        "audioop-lts": "==0.2.2",
    }
    sip_livekit_versions = {
        Requirement(raw).name.lower(): str(Requirement(raw).specifier)
        for raw in extras["sip-livekit"]
    }
    assert sip_livekit_versions == {
        "qwenpaw": "",
        "livekit": "==1.1.13",
        "livekit-api": "==1.2.0",
    }


def test_source_pyproject_skips_unrelated_parent_project(tmp_path):
    project = tmp_path / "qwenpaw"
    module = project / "src" / "qwenpaw" / "app" / "channels" / "module.py"
    module.parent.mkdir(parents=True)
    module.touch()
    (project / "src" / "pyproject.toml").write_text(
        '[project]\nname = "unrelated"\n',
        encoding="utf-8",
    )
    expected = project / "pyproject.toml"
    expected.write_text('[project]\nname = "qwenpaw"\n', encoding="utf-8")

    with patch("qwenpaw.app.channels.dependencies.__file__", str(module)):
        assert _source_pyproject() == expected


def test_missing_requirements_returns_only_unsatisfied_items():
    spec = BUILTIN_CHANNEL_CATALOG["feishu"]
    with patch(
        "qwenpaw.app.channels.dependencies._is_requirement_satisfied",
        side_effect=lambda req: req.name != "lark-oapi",
    ):
        assert missing_requirements(spec) == ["lark-oapi==1.7.1"]


def test_requirement_state_distinguishes_missing_and_version_mismatch():
    requirement = Requirement("lark-oapi==1.7.1")
    with patch(
        "qwenpaw.app.channels.dependencies.version",
        side_effect=PackageNotFoundError,
    ):
        assert _requirement_state(requirement) == "missing"

    with patch(
        "qwenpaw.app.channels.dependencies.version",
        return_value="1.5.0",
    ):
        assert _requirement_state(requirement) == "version_mismatch"

    with patch(
        "qwenpaw.app.channels.dependencies.version",
        return_value="2.0.0",
    ):
        assert _requirement_state(requirement) == "version_mismatch"

    with patch(
        "qwenpaw.app.channels.dependencies.version",
        return_value="1.7.1",
    ):
        assert _requirement_state(requirement) == "satisfied"


def test_version_mismatch_requirements_ignores_missing_packages():
    spec = BUILTIN_CHANNEL_CATALOG["feishu"]

    def requirement_state(requirement):
        if requirement.name == "lark-oapi":
            return "version_mismatch"
        return "missing"

    with patch(
        "qwenpaw.app.channels.dependencies._requirement_state",
        side_effect=requirement_state,
    ):
        assert version_mismatch_requirements(spec) == [
            "lark-oapi==1.7.1",
        ]


def test_requirements_for_extra_caches_pyproject_reads(tmp_path):
    project = tmp_path / "pyproject.toml"
    project.write_text(
        "[project]\n"
        'name = "qwenpaw"\n'
        "[project.optional-dependencies]\n"
        'channel-test = ["example-package>=1"]\n',
        encoding="utf-8",
    )
    from qwenpaw.app.channels import dependencies

    dependencies._requirements_for_extra_cached.cache_clear()
    original_read_text = Path.read_text
    reads = 0

    def counting_read_text(path, *args, **kwargs):
        nonlocal reads
        reads += 1
        return original_read_text(path, *args, **kwargs)

    with (
        patch.object(dependencies, "_source_pyproject", return_value=project),
        patch.object(Path, "read_text", counting_read_text),
    ):
        assert requirements_for_extra("channel-test") == [
            "example-package>=1",
        ]
        assert requirements_for_extra("channel-test") == [
            "example-package>=1",
        ]

    assert reads == 1
    dependencies._requirements_for_extra_cached.cache_clear()


def test_non_frozen_uninstalled_package_is_not_satisfied_by_loaded_module():
    req = Requirement("lark-oapi==1.7.1")
    with (
        patch(
            "qwenpaw.app.channels.dependencies._is_frozen",
            return_value=False,
        ),
        patch(
            "qwenpaw.app.channels.dependencies.version",
            side_effect=PackageNotFoundError,
        ),
        patch(
            "qwenpaw.app.channels.dependencies."
            "PluginLoader.is_requirement_satisfied",
            return_value=True,
        ) as plugin_check,
    ):
        assert not _is_requirement_satisfied(req)

    plugin_check.assert_not_called()


def test_frozen_unversioned_bundled_package_is_satisfied_when_pinned():
    req = Requirement("lark-oapi==1.7.1")
    with (
        patch(
            "qwenpaw.app.channels.dependencies._is_frozen",
            return_value=True,
        ),
        patch(
            "qwenpaw.app.channels.dependencies.version",
            side_effect=PackageNotFoundError,
        ),
        patch(
            "qwenpaw.app.channels.dependencies."
            "PluginLoader.is_requirement_satisfied",
            return_value=True,
        ) as plugin_check,
    ):
        assert _requirement_state(req) == "satisfied"

    checked = plugin_check.call_args.args[0]
    assert checked.name == "lark-oapi"
    assert not checked.specifier


def test_enabled_builtin_channels_uses_enabled_agent_profiles():
    config = SimpleNamespace(
        agents=SimpleNamespace(
            profiles={
                "enabled-agent": SimpleNamespace(enabled=True),
                "disabled-agent": SimpleNamespace(enabled=False),
            },
        ),
    )
    channels = SimpleNamespace(
        feishu=SimpleNamespace(enabled=True),
        matrix=SimpleNamespace(enabled=False),
    )
    with patch(
        "qwenpaw.app.channels.dependencies.load_agent_config",
        return_value=SimpleNamespace(channels=channels),
    ) as load_agent:
        assert enabled_builtin_channels(config) == {"feishu"}

    load_agent.assert_called_once_with("enabled-agent")


def test_non_frozen_environment_does_not_read_channel_runtime(tmp_path):
    with (
        patch("qwenpaw.app.channels.dependencies.WORKING_DIR", tmp_path),
        patch(
            "qwenpaw.app.channels.dependencies._is_frozen",
            return_value=False,
        ),
        patch("qwenpaw.app.channels.dependencies.site.addsitedir") as add,
    ):
        runtime = str(_channel_site_dir())
        _channel_site_dir().mkdir(parents=True)
        sys.path.insert(0, runtime)
        _ensure_channel_site_on_path()

    add.assert_not_called()
    assert runtime not in sys.path


def test_channel_job_state_is_isolated_by_runtime_environment(tmp_path):
    with patch("qwenpaw.app.channels.dependencies.WORKING_DIR", tmp_path):
        with patch(
            "qwenpaw.app.channels.dependencies._is_frozen",
            return_value=True,
        ):
            desktop = _channel_state_dir()
        with (
            patch(
                "qwenpaw.app.channels.dependencies._is_frozen",
                return_value=False,
            ),
            patch(
                "qwenpaw.app.channels.dependencies.sys.executable",
                "/a/python",
            ),
        ):
            first = _channel_state_dir()
        with (
            patch(
                "qwenpaw.app.channels.dependencies._is_frozen",
                return_value=False,
            ),
            patch(
                "qwenpaw.app.channels.dependencies.sys.executable",
                "/b/python",
            ),
        ):
            second = _channel_state_dir()

    assert len({desktop, first, second}) == 3


def test_platform_unsupported_status(tmp_path):
    unsupported = ChannelSpec(
        "imessage",
        ".imessage",
        "IMessageChannel",
        platforms=frozenset({"never-this-platform"}),
    )
    with (
        patch("qwenpaw.app.channels.dependencies.WORKING_DIR", tmp_path),
        patch.dict(BUILTIN_CHANNEL_CATALOG, {"imessage": unsupported}),
    ):
        status = ChannelDependencyService().channel_status("imessage")
    assert status["status"] == "platform_unsupported"


def test_failed_install_is_reported_as_retryable(tmp_path):
    with patch("qwenpaw.app.channels.dependencies.WORKING_DIR", tmp_path):
        service = ChannelDependencyService()
    job = InstallJob(
        id="failed-job",
        channel="telegram",
        requirements=["python-telegram-bot>=20.0"],
        status="failed",
        error="network unavailable",
    )
    service._jobs[job.id] = job  # pylint: disable=protected-access
    service._active_by_channel[
        job.channel
    ] = job.id  # pylint: disable=protected-access

    with patch(
        "qwenpaw.app.channels.dependencies.missing_requirements",
        return_value=job.requirements,
    ):
        status = service.channel_status("telegram")

    assert status["status"] == "failed"
    assert status["last_job_id"] == job.id
    assert status["last_error"] == "network unavailable"


def test_interrupted_install_is_restored_as_failed(tmp_path):
    with patch("qwenpaw.app.channels.dependencies.WORKING_DIR", tmp_path):
        service = ChannelDependencyService()
        path = service._state_dir / "install_jobs.json"
        service._state_dir.mkdir(parents=True)
        path.write_text(
            json.dumps(
                [
                    InstallJob(
                        id="interrupted-job",
                        channel="telegram",
                        requirements=["python-telegram-bot>=20.0"],
                        status="installing",
                    ).storage_dict(),
                ],
            ),
            encoding="utf-8",
        )
        service = ChannelDependencyService()

    restored = service.get_job("interrupted-job")
    assert restored is not None
    assert restored.status == "failed"
    assert "restart" in (restored.error or "")
    persisted = json.loads(path.read_text(encoding="utf-8"))
    assert persisted[0]["status"] == "failed"


def test_default_aliyun_source_falls_back_to_pypi_for_network_errors(tmp_path):
    with patch("qwenpaw.app.channels.dependencies.WORKING_DIR", tmp_path):
        service = ChannelDependencyService()
    job = InstallJob(
        id="network-job",
        channel="telegram",
        requirements=["python-telegram-bot>=20.0"],
    )

    with (
        patch.dict("os.environ", {}, clear=True),
        patch.object(
            service,
            "_run_install",
            side_effect=[
                subprocess.CompletedProcess([], 1, "connection reset", ""),
                subprocess.CompletedProcess([], 0, "", ""),
            ],
        ) as run_install,
    ):
        service._install_with_sources(  # pylint: disable=protected-access
            job,
            job.requirements,
        )

    assert run_install.call_count == 2
    assert job.attempted_sources == [
        "aliyun",
        "pypi",
    ]


def test_source_fallback_handles_mirror_sync_lag(tmp_path):
    with patch("qwenpaw.app.channels.dependencies.WORKING_DIR", tmp_path):
        service = ChannelDependencyService()
    job = InstallJob(
        id="mirror-sync-job",
        channel="telegram",
        requirements=["python-telegram-bot>=20.0"],
    )

    with patch.object(
        service,
        "_run_install",
        side_effect=[
            subprocess.CompletedProcess(
                [],
                1,
                "No matching distribution found",
                "",
            ),
            subprocess.CompletedProcess([], 0, "", ""),
        ],
    ) as run_install:
        service._install_with_sources(job, job.requirements)

    assert run_install.call_count == 2


def test_each_source_has_one_public_fallback(tmp_path):
    with patch("qwenpaw.app.channels.dependencies.WORKING_DIR", tmp_path):
        service = ChannelDependencyService()
    requirements = ["python-telegram-bot>=20.0"]
    assert service._source_candidates(  # pylint: disable=protected-access
        InstallJob(
            id="pypi-source-job",
            channel="telegram",
            requirements=requirements,
            source="pypi",
        ),
    ) == [
        ("https://pypi.org/simple/", "pypi"),
        ("https://mirrors.aliyun.com/pypi/simple/", "aliyun"),
    ]
    assert service._source_candidates(  # pylint: disable=protected-access
        InstallJob(
            id="aliyun-source-job",
            channel="telegram",
            requirements=requirements,
        ),
    ) == [
        ("https://mirrors.aliyun.com/pypi/simple/", "aliyun"),
        ("https://pypi.org/simple/", "pypi"),
    ]


def test_pypi_missing_distribution_does_not_fallback(tmp_path):
    with patch("qwenpaw.app.channels.dependencies.WORKING_DIR", tmp_path):
        service = ChannelDependencyService()
    job = InstallJob(
        id="pypi-missing-job",
        channel="telegram",
        requirements=["python-telegram-bot>=20.0"],
        source="pypi",
    )

    with patch.object(
        service,
        "_run_install",
        return_value=subprocess.CompletedProcess(
            [],
            1,
            "No matching distribution found",
            "",
        ),
    ) as run_install:
        with pytest.raises(RuntimeError, match="No matching distribution"):
            service._install_with_sources(job, job.requirements)

    run_install.assert_called_once()


def test_pypi_not_found_does_not_fallback(tmp_path):
    with patch("qwenpaw.app.channels.dependencies.WORKING_DIR", tmp_path):
        service = ChannelDependencyService()
    job = InstallJob(
        id="pypi-not-found-job",
        channel="telegram",
        requirements=["python-telegram-bot>=20.0"],
        source="pypi",
    )

    with patch.object(
        service,
        "_run_install",
        return_value=subprocess.CompletedProcess(
            [],
            1,
            "HTTP error 404 while fetching package index",
            "",
        ),
    ) as run_install:
        with pytest.raises(RuntimeError, match="HTTP error 404"):
            service._install_with_sources(job, job.requirements)

    run_install.assert_called_once()


@pytest.mark.parametrize(
    "output",
    [
        "Package requires a different Python version: 3.9 not in >=3.10",
        "Ignored version with Requires-Python >=3.12",
        "package.whl is not a supported wheel on this platform",
    ],
)
def test_python_or_platform_incompatibility_does_not_fallback(
    tmp_path,
    output,
):
    with patch("qwenpaw.app.channels.dependencies.WORKING_DIR", tmp_path):
        service = ChannelDependencyService()
    job = InstallJob(
        id="incompatible-job",
        channel="telegram",
        requirements=["python-telegram-bot>=20.0"],
    )

    with patch.object(
        service,
        "_run_install",
        return_value=subprocess.CompletedProcess([], 1, output, ""),
    ) as run_install:
        with pytest.raises(RuntimeError):
            service._install_with_sources(job, job.requirements)

    run_install.assert_called_once()


def test_custom_source_credentials_are_not_exposed_or_persisted(tmp_path):
    with patch("qwenpaw.app.channels.dependencies.WORKING_DIR", tmp_path):
        service = ChannelDependencyService()
    job = InstallJob(
        id="custom-source-job",
        channel="telegram",
        requirements=["python-telegram-bot>=20.0"],
        source="custom",
        custom_index_url="https://user:secret@example.com/simple/",
        owner_pid=123,
    )

    assert service._source_candidates(
        job,
    ) == [  # pylint: disable=protected-access
        ("https://user:secret@example.com/simple/", "custom:example.com"),
        ("https://mirrors.aliyun.com/pypi/simple/", "aliyun"),
    ]
    service._append_attempted_source(  # pylint: disable=protected-access
        job,
        "custom:example.com",
    )

    public = job.public_dict()
    persisted = json.loads(
        (service._state_dir / "install_jobs.json").read_text(
            encoding="utf-8",
        ),
    )[0]
    serialized = json.dumps({"public": public, "persisted": persisted})
    assert "secret" not in serialized
    assert "user:" not in serialized
    assert public["attempted_sources"] == ["custom:example.com"]
    assert "owner_pid" not in public


def test_legacy_job_source_credentials_are_sanitized_on_load(tmp_path):
    with patch("qwenpaw.app.channels.dependencies.WORKING_DIR", tmp_path):
        service = ChannelDependencyService()
        service._state_dir.mkdir(parents=True)
        (service._state_dir / "install_jobs.json").write_text(
            json.dumps(
                [
                    {
                        "id": "legacy-job",
                        "channel": "telegram",
                        "requirements": ["python-telegram-bot>=20.0"],
                        "status": "failed",
                        "attempted_sources": [
                            "https://user:secret@example.com/simple/",
                        ],
                        "error": (
                            "Could not fetch "
                            "https://user:secret@example.com/simple/package"
                        ),
                    },
                ],
            ),
            encoding="utf-8",
        )
        service = ChannelDependencyService()

    restored = service.get_job("legacy-job")
    assert restored is not None
    serialized = json.dumps(restored.public_dict())
    assert "secret" not in serialized
    assert "user:" not in serialized
    assert restored.attempted_sources == ["custom:example.com"]


def test_services_merge_jobs_through_shared_state_file(tmp_path):
    with patch("qwenpaw.app.channels.dependencies.WORKING_DIR", tmp_path):
        first = ChannelDependencyService()
        second = ChannelDependencyService()
    first_job = InstallJob(
        id="first-job",
        channel="telegram",
        requirements=["python-telegram-bot>=20.0"],
        status="failed",
    )
    second_job = InstallJob(
        id="second-job",
        channel="slack",
        requirements=["slack-bolt>=1.22.0"],
        status="failed",
    )

    first._persist_job(first_job)  # pylint: disable=protected-access
    second._persist_job(second_job)  # pylint: disable=protected-access

    assert first.get_job(first_job.id) is not None
    assert first.get_job(second_job.id) is not None
    payload = json.loads(
        (first._state_dir / "install_jobs.json").read_text(
            encoding="utf-8",
        ),
    )
    assert {item["id"] for item in payload} == {first_job.id, second_job.id}


def test_running_job_owned_by_another_process_is_not_marked_interrupted(
    tmp_path,
):
    job = InstallJob(
        id="peer-job",
        channel="telegram",
        requirements=["python-telegram-bot>=20.0"],
        status="installing",
        owner_pid=456,
        owner_started_at=123.0,
    )
    with (
        patch("qwenpaw.app.channels.dependencies.WORKING_DIR", tmp_path),
        patch.object(
            ChannelDependencyService,
            "_pid_is_running",
            return_value=True,
        ),
    ):
        service = ChannelDependencyService()
        service._state_dir.mkdir(parents=True)
        (service._state_dir / "install_jobs.json").write_text(
            json.dumps([job.storage_dict()]),
            encoding="utf-8",
        )
        service = ChannelDependencyService()
        restored = service.get_job(job.id)
    assert restored is not None
    assert restored.status == "installing"


def test_cancel_install_creates_cross_process_marker(tmp_path):
    with patch("qwenpaw.app.channels.dependencies.WORKING_DIR", tmp_path):
        service = ChannelDependencyService()
    job = InstallJob(
        id="active-job",
        channel="telegram",
        requirements=["python-telegram-bot>=20.0"],
        status="installing",
        owner_pid=os.getpid(),
        owner_started_at=psutil.Process().create_time(),
    )
    service._persist_job(job)

    cancelled = service.cancel_install("telegram")

    assert cancelled.id == job.id
    assert service._is_cancel_requested(job)


def test_cancel_install_rejects_inactive_channel(tmp_path):
    with patch("qwenpaw.app.channels.dependencies.WORKING_DIR", tmp_path):
        service = ChannelDependencyService()

    with pytest.raises(ValueError, match="not active"):
        service.cancel_install("telegram")


def test_custom_source_is_passed_via_environment_not_command_line(tmp_path):
    source = "https://user:secret@example.com/simple/"
    with patch("qwenpaw.app.channels.dependencies.WORKING_DIR", tmp_path):
        service = ChannelDependencyService()

    with patch(
        "qwenpaw.app.channels.dependencies.PluginLoader."
        "run_subprocess_with_streaming_log",
        return_value=subprocess.CompletedProcess([], 0, "", ""),
    ) as run:
        service._run_install(  # pylint: disable=protected-access
            ["python-telegram-bot>=20.0"],
            source,
            "telegram",
        )

    args = run.call_args.args[0]
    kwargs = run.call_args.kwargs
    assert source not in args
    assert kwargs["environment"]["PIP_INDEX_URL"] == source
    assert kwargs["environment"]["UV_INDEX_URL"] == source
    assert kwargs["redact_values"] == [source, "user:secret@"]


def test_non_frozen_install_targets_current_python_environment(tmp_path):
    with patch("qwenpaw.app.channels.dependencies.WORKING_DIR", tmp_path):
        service = ChannelDependencyService()

    with (
        patch(
            "qwenpaw.app.channels.dependencies._is_frozen",
            return_value=False,
        ),
        patch(
            "qwenpaw.app.channels.dependencies.PluginLoader."
            "run_subprocess_with_streaming_log",
            return_value=subprocess.CompletedProcess([], 0, "", ""),
        ) as run,
    ):
        service._run_install(  # pylint: disable=protected-access
            ["matrix-nio>=0.25.0"],
            None,
            "matrix",
        )

    args = run.call_args.args[0]
    assert args[:4] == [
        sys.executable,
        "-m",
        "pip",
        "install",
    ]
    assert "--target" not in args


def test_frozen_install_targets_channel_runtime(tmp_path):
    desktop_python = str(tmp_path / "python")
    with patch("qwenpaw.app.channels.dependencies.WORKING_DIR", tmp_path):
        service = ChannelDependencyService()
        expected_target = str(_channel_site_dir())
        with (
            patch(
                "qwenpaw.app.channels.dependencies._is_frozen",
                return_value=True,
            ),
            patch(
                "qwenpaw.app.channels.dependencies._desktop_python",
                return_value=desktop_python,
            ),
            patch(
                "qwenpaw.app.channels.dependencies.PluginLoader."
                "run_subprocess_with_streaming_log",
                return_value=subprocess.CompletedProcess([], 0, "", ""),
            ) as run,
        ):
            service._run_install(  # pylint: disable=protected-access
                ["matrix-nio>=0.25.0"],
                None,
                "matrix",
            )

    args = run.call_args.args[0]
    target_index = args.index("--target")
    assert args[0] == desktop_python
    assert args[target_index + 1] == expected_target


def test_non_network_install_error_does_not_change_source(tmp_path):
    with patch("qwenpaw.app.channels.dependencies.WORKING_DIR", tmp_path):
        service = ChannelDependencyService()
    job = InstallJob(
        id="resolver-job",
        channel="telegram",
        requirements=["python-telegram-bot>=20.0"],
    )

    with patch.object(
        service,
        "_run_install",
        return_value=subprocess.CompletedProcess(
            [],
            1,
            "ResolutionImpossible: conflicting dependencies",
            "",
        ),
    ) as run_install:
        try:
            service._install_with_sources(  # pylint: disable=protected-access
                job,
                job.requirements,
            )
        except RuntimeError:
            pass
        else:
            raise AssertionError("expected dependency resolution failure")

    run_install.assert_called_once()


def test_install_lock_timeout_fails_instead_of_writing_unlocked(tmp_path):
    with patch("qwenpaw.app.channels.dependencies.WORKING_DIR", tmp_path):
        service = ChannelDependencyService()
    job = InstallJob(
        id="lock-timeout-job",
        channel="telegram",
        requirements=["python-telegram-bot>=20.0"],
    )

    with patch(
        "qwenpaw.app.channels.dependencies.plugin_install_lock",
    ) as install_lock:
        install_lock.return_value.__enter__.return_value = False
        install_lock.return_value.__exit__.return_value = False
        try:
            service._install_locked(job)  # pylint: disable=protected-access
        except RuntimeError as exc:
            assert "another channel dependency install" in str(exc)
        else:
            raise AssertionError("expected a lock timeout failure")


async def test_successful_install_runs_post_install_callback(tmp_path):
    with patch("qwenpaw.app.channels.dependencies.WORKING_DIR", tmp_path):
        service = ChannelDependencyService()
    job = InstallJob(
        id="successful-job",
        channel="telegram",
        requirements=["python-telegram-bot>=20.0"],
    )
    callback = MagicMock()

    with (
        patch.object(service, "_install_locked"),
        patch(
            "qwenpaw.app.channels.dependencies.missing_requirements",
            return_value=[],
        ),
        patch("importlib.import_module") as import_module,
    ):
        import_module.return_value.TelegramChannel = object
        await service._run_job(  # pylint: disable=protected-access
            job,
            on_success=callback,
        )

    assert job.status == "succeeded"
    callback.assert_called_once_with()


async def test_automatic_repair_schedules_only_version_mismatches(tmp_path):
    with patch("qwenpaw.app.channels.dependencies.WORKING_DIR", tmp_path):
        service = ChannelDependencyService()
    repaired = InstallJob(
        id="repair-job",
        channel="feishu",
        requirements=["lark-oapi==1.7.1"],
        version_repair=True,
    )
    callback = AsyncMock()

    def mismatches(spec):
        if spec.key == "feishu":
            return repaired.requirements
        return []

    async def complete_job(job):
        job.status = "succeeded"

    with (
        patch(
            "qwenpaw.app.channels.dependencies."
            "version_mismatch_requirements",
            side_effect=mismatches,
        ),
        patch.object(
            service,
            "_create_install_job",
            return_value=(repaired, True),
        ) as create_job,
        patch.object(
            service,
            "_run_job",
            new=AsyncMock(side_effect=complete_job),
        ) as run_job,
    ):
        jobs = await service.repair_version_mismatches(
            {"feishu"},
            on_success=callback,
        )

    assert jobs == [repaired]
    assert create_job.call_args.args[1] == ["lark-oapi==1.7.1"]
    assert create_job.call_args.kwargs["source"] == "aliyun"
    assert create_job.call_args.kwargs["version_repair"] is True
    run_job.assert_awaited_once_with(repaired)
    callback.assert_awaited_once_with()


async def test_automatic_repair_ignores_disabled_channels(tmp_path):
    with patch("qwenpaw.app.channels.dependencies.WORKING_DIR", tmp_path):
        service = ChannelDependencyService()
    with patch(
        "qwenpaw.app.channels.dependencies.version_mismatch_requirements",
    ) as inspect_requirements:
        assert await service.repair_version_mismatches(set()) == []

    inspect_requirements.assert_not_called()


async def test_automatic_repair_continues_after_inspection_failure(tmp_path):
    with patch("qwenpaw.app.channels.dependencies.WORKING_DIR", tmp_path):
        service = ChannelDependencyService()
    repaired = InstallJob(
        id="repair-job",
        channel="matrix",
        requirements=["matrix-nio==0.25.2"],
        version_repair=True,
    )

    def mismatches(spec):
        if spec.key == "feishu":
            raise RuntimeError("inspection failed")
        if spec.key == "matrix":
            return repaired.requirements
        return []

    async def complete_job(job):
        job.status = "succeeded"

    with (
        patch(
            "qwenpaw.app.channels.dependencies."
            "version_mismatch_requirements",
            side_effect=mismatches,
        ),
        patch.object(
            service,
            "_create_install_job",
            return_value=(repaired, True),
        ) as create_job,
        patch.object(
            service,
            "_run_job",
            new=AsyncMock(side_effect=complete_job),
        ),
    ):
        jobs = await service.repair_version_mismatches(
            {"feishu", "matrix"},
        )

    assert jobs == [repaired]
    assert create_job.call_args.args[0] == "matrix"


async def test_automatic_repairs_run_sequentially(tmp_path):
    with patch("qwenpaw.app.channels.dependencies.WORKING_DIR", tmp_path):
        service = ChannelDependencyService()
    jobs = {
        "feishu": InstallJob(
            id="feishu-repair",
            channel="feishu",
            requirements=["lark-oapi==1.7.1"],
            version_repair=True,
        ),
        "matrix": InstallJob(
            id="matrix-repair",
            channel="matrix",
            requirements=["matrix-nio==0.26.0"],
            version_repair=True,
        ),
    }
    running = False

    def mismatches(spec):
        job = jobs.get(spec.key)
        return job.requirements if job is not None else []

    def create_job(channel, *_args, **_kwargs):
        return jobs[channel], True

    async def complete_job(job):
        nonlocal running
        assert not running
        running = True
        await asyncio.sleep(0)
        job.status = "succeeded"
        running = False

    with (
        patch(
            "qwenpaw.app.channels.dependencies."
            "version_mismatch_requirements",
            side_effect=mismatches,
        ),
        patch.object(
            service,
            "_create_install_job",
            side_effect=create_job,
        ),
        patch.object(
            service,
            "_run_job",
            new=AsyncMock(side_effect=complete_job),
        ),
    ):
        repaired = await service.repair_version_mismatches(
            {"feishu", "matrix"},
        )

    assert repaired == [jobs["feishu"], jobs["matrix"]]


async def test_automatic_repair_respects_runtime_install_setting(tmp_path):
    with patch("qwenpaw.app.channels.dependencies.WORKING_DIR", tmp_path):
        service = ChannelDependencyService()
    with (
        patch.dict(
            os.environ,
            {"QWENPAW_RUNTIME_DEP_INSTALL": "0"},
        ),
        patch(
            "qwenpaw.app.channels.dependencies."
            "version_mismatch_requirements",
        ) as inspect_requirements,
    ):
        assert await service.repair_version_mismatches({"feishu"}) == []

    inspect_requirements.assert_not_called()


def test_version_repair_installs_only_task_requirements(tmp_path):
    with patch("qwenpaw.app.channels.dependencies.WORKING_DIR", tmp_path):
        service = ChannelDependencyService()
    job = InstallJob(
        id="repair-only-job",
        channel="feishu",
        requirements=["lark-oapi==1.7.1"],
        version_repair=True,
    )

    def requirement_state(requirement):
        if requirement.name == "lark-oapi":
            return "version_mismatch"
        return "missing"

    with (
        patch(
            "qwenpaw.app.channels.dependencies._requirement_state",
            side_effect=requirement_state,
        ),
        patch.object(service, "_install_with_sources") as install,
    ):
        service._install_locked(job)  # pylint: disable=protected-access

    install.assert_called_once_with(
        job,
        ["lark-oapi==1.7.1"],
        reinstall=False,
    )


async def test_failed_automatic_repairs_do_not_trigger_reload(tmp_path):
    with patch("qwenpaw.app.channels.dependencies.WORKING_DIR", tmp_path):
        service = ChannelDependencyService()
    failed = InstallJob(
        id="failed-repair-job",
        channel="feishu",
        requirements=["lark-oapi==1.7.1"],
        version_repair=True,
    )
    callback = MagicMock()

    async def fail_job(job):
        job.status = "failed"

    with (
        patch(
            "qwenpaw.app.channels.dependencies."
            "version_mismatch_requirements",
            side_effect=lambda spec: (
                failed.requirements if spec.key == "feishu" else []
            ),
        ),
        patch.object(
            service,
            "_create_install_job",
            return_value=(failed, True),
        ),
        patch.object(service, "_run_job", side_effect=fail_job),
    ):
        await service.repair_version_mismatches(
            {"feishu"},
            on_success=callback,
        )

    callback.assert_not_called()


async def test_version_repair_verifies_channel_import(tmp_path):
    with patch("qwenpaw.app.channels.dependencies.WORKING_DIR", tmp_path):
        service = ChannelDependencyService()
    job = InstallJob(
        id="verify-repair-job",
        channel="feishu",
        requirements=["lark-oapi==1.7.1"],
        version_repair=True,
    )

    with (
        patch.object(service, "_install_locked"),
        patch.object(
            service,
            "_verify_channel",
            return_value=[],
        ) as verify_channel,
    ):
        await service._run_job(job)  # pylint: disable=protected-access

    assert job.status == "succeeded"
    verify_channel.assert_called_once_with("feishu")


async def test_version_repair_import_failure_does_not_reload(tmp_path):
    with patch("qwenpaw.app.channels.dependencies.WORKING_DIR", tmp_path):
        service = ChannelDependencyService()
    job = InstallJob(
        id="repair-import-failure",
        channel="feishu",
        requirements=["lark-oapi==1.7.1"],
        version_repair=True,
    )
    callback = MagicMock()

    with (
        patch.object(service, "_install_locked"),
        patch.object(
            service,
            "_verify_channel",
            side_effect=RuntimeError("Channel failed to load"),
        ),
    ):
        await service._run_job(  # pylint: disable=protected-access
            job,
            on_success=callback,
        )

    assert job.status == "failed"
    callback.assert_not_called()


async def test_shutdown_cancels_and_waits_for_active_install(tmp_path):
    with patch("qwenpaw.app.channels.dependencies.WORKING_DIR", tmp_path):
        service = ChannelDependencyService()
    requirements = ["lark-oapi==1.7.1"]
    started = threading.Event()
    stopped = threading.Event()

    def install(current_job):
        started.set()
        while not service._is_cancel_requested(current_job):
            time.sleep(0.01)
        stopped.set()
        raise RuntimeError("Dependency installation was stopped by user")

    with (
        patch(
            "qwenpaw.app.channels.dependencies.missing_requirements",
            return_value=requirements,
        ),
        patch.object(service, "_install_locked", side_effect=install),
    ):
        job = await service.start_install("feishu")
        await asyncio.to_thread(started.wait, 1)
        await asyncio.wait_for(service.shutdown(), timeout=2)

    assert stopped.is_set()
    assert job.status == "failed"
    assert not service._background_tasks


async def test_install_state_persistence_does_not_block_event_loop(tmp_path):
    with patch("qwenpaw.app.channels.dependencies.WORKING_DIR", tmp_path):
        service = ChannelDependencyService()
    job = InstallJob(
        id="slow-state-job",
        channel="telegram",
        requirements=["python-telegram-bot>=20.0"],
    )
    release_update = threading.Event()

    def slow_update(*_args, **_kwargs):
        assert release_update.wait(timeout=1)

    with (
        patch.object(service, "_update_job", side_effect=slow_update),
        patch.object(service, "_install_locked"),
        patch.object(service, "_verify_channel", return_value=[]),
    ):
        job_task = asyncio.create_task(service._run_job(job))
        await asyncio.sleep(0)
        release_update.set()
        await asyncio.wait_for(job_task, timeout=0.5)


async def test_reinstall_requires_a_load_error(tmp_path):
    with patch("qwenpaw.app.channels.dependencies.WORKING_DIR", tmp_path):
        service = ChannelDependencyService()
    with (
        patch(
            "qwenpaw.app.channels.dependencies.missing_requirements",
            return_value=[],
        ),
        patch.object(service, "_channel_load_error", return_value=None),
    ):
        with pytest.raises(ValueError, match="already ready"):
            await service.start_install("feishu", reinstall=True)


async def test_reinstall_rejects_missing_dependencies(tmp_path):
    with patch("qwenpaw.app.channels.dependencies.WORKING_DIR", tmp_path):
        service = ChannelDependencyService()
    with patch(
        "qwenpaw.app.channels.dependencies.missing_requirements",
        return_value=["lark-oapi==1.7.1"],
    ):
        with pytest.raises(ValueError, match="only available"):
            await service.start_install("feishu", reinstall=True)


async def test_reinstall_uses_full_channel_requirements(tmp_path):
    with patch("qwenpaw.app.channels.dependencies.WORKING_DIR", tmp_path):
        service = ChannelDependencyService()
    created = InstallJob(
        id="reinstall-job",
        channel="feishu",
        requirements=["lark-oapi==1.7.1"],
        reinstall=True,
    )
    with (
        patch(
            "qwenpaw.app.channels.dependencies.missing_requirements",
            return_value=[],
        ),
        patch.object(
            service,
            "_channel_load_error",
            return_value="ImportError: broken",
        ),
        patch(
            "qwenpaw.app.channels.dependencies.requirements_for_extra",
            return_value=created.requirements,
        ),
        patch.object(
            service,
            "_create_install_job",
            return_value=(created, False),
        ) as create_job,
    ):
        result = await service.start_install("feishu", reinstall=True)

    assert result is created
    assert create_job.call_args.args[1] == created.requirements
    assert create_job.call_args.kwargs["reinstall"] is True


async def test_reinstall_rejects_channel_without_optional_dependencies(
    tmp_path,
):
    with patch("qwenpaw.app.channels.dependencies.WORKING_DIR", tmp_path):
        service = ChannelDependencyService()
    with (
        patch(
            "qwenpaw.app.channels.dependencies.missing_requirements",
            return_value=[],
        ),
        patch.object(
            service,
            "_channel_load_error",
            return_value="ImportError: broken core channel",
        ),
        patch(
            "qwenpaw.app.channels.dependencies.requirements_for_extra",
            return_value=[],
        ),
    ):
        with pytest.raises(ValueError, match="no reinstallable"):
            await service.start_install("console", reinstall=True)


def test_verify_channel_reimports_module_after_install(tmp_path):
    spec = BUILTIN_CHANNEL_CATALOG["telegram"]
    module_name = "qwenpaw.app.channels.telegram"
    stale_module = object()
    sys.modules[module_name] = stale_module
    with (
        patch("qwenpaw.app.channels.dependencies.WORKING_DIR", tmp_path),
        patch(
            "qwenpaw.app.channels.dependencies.missing_requirements",
            return_value=[],
        ),
        patch.object(
            ChannelDependencyService,
            "_channel_load_error",
            return_value=None,
        ) as load_error,
    ):
        assert not ChannelDependencyService._verify_channel("telegram")

    assert module_name not in sys.modules
    load_error.assert_called_once_with(spec)
