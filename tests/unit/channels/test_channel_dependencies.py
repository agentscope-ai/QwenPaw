# -*- coding: utf-8 -*-
# pylint: disable=protected-access
import json
from pathlib import Path
import subprocess
import tomllib
from unittest.mock import MagicMock, patch

from packaging.requirements import Requirement

from qwenpaw.app.channels.catalog import BUILTIN_CHANNEL_CATALOG, ChannelSpec
from qwenpaw.app.channels.dependencies import (
    ChannelDependencyService,
    InstallJob,
    _source_pyproject,
    missing_requirements,
    requirements_for_extra,
)


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


def test_legacy_channel_dependency_ranges_are_preserved():
    expected = {
        "discord": {"discord-py": ">=2.3"},
        "dingtalk": {
            "dingtalk-stream": ">=0.24.3",
            "alibabacloud-dingtalk": ">=2.2.42",
            "segno": ">=1.6.6",
        },
        "feishu": {
            "lark-oapi": ">=1.5.3",
            "python-socks": ">=2.5.3",
            "segno": ">=1.6.6",
        },
        "telegram": {"python-telegram-bot": ">=20.0"},
        "slack": {"slack-bolt": ">=1.22.0"},
        "mqtt": {"paho-mqtt": ">=2.0.0"},
        "matrix": {"matrix-nio": ">=0.25.0"},
        "voice": {"twilio": ">=9.10.2"},
        "wecom": {
            "wecom-aibot-python-sdk": "==1.0.2",
            "segno": ">=1.6.6",
        },
    }
    for channel, requirements in expected.items():
        spec = BUILTIN_CHANNEL_CATALOG[channel]
        actual = {
            Requirement(raw).name.lower(): str(Requirement(raw).specifier)
            for raw in requirements_for_extra(spec.extra)
        }
        assert requirements.items() <= actual.items()


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


def test_channel_only_sdks_are_not_core_dependencies():
    pyproject = Path(__file__).resolve().parents[3] / "pyproject.toml"
    data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    core = {
        Requirement(raw).name.lower()
        for raw in data["project"]["dependencies"]
    }
    channel_only = {
        "discord-py",
        "dingtalk-stream",
        "alibabacloud-dingtalk",
        "lark-oapi",
        "python-socks",
        "python-telegram-bot",
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
        "pillow",
        "segno",
    }
    assert core.isdisjoint(channel_only)

    assert {
        "alibabacloud-tea-openapi",
        "alibabacloud-credentials",
        "alibabacloud-tea-util",
    } <= core


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
    spec = BUILTIN_CHANNEL_CATALOG["dingtalk"]
    with patch(
        "qwenpaw.app.channels.dependencies."
        "PluginLoader.is_requirement_satisfied",
        side_effect=lambda req: req.name != "dingtalk-stream",
    ):
        assert missing_requirements(spec) == ["dingtalk-stream>=0.24.3"]


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
    state_dir = tmp_path / "channel_runtime"
    state_dir.mkdir()
    path = state_dir / "install_jobs.json"
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

    with patch("qwenpaw.app.channels.dependencies.WORKING_DIR", tmp_path):
        service = ChannelDependencyService()

    restored = service.get_job("interrupted-job")
    assert restored is not None
    assert restored.status == "failed"
    assert "restart" in (restored.error or "")
    persisted = json.loads(path.read_text(encoding="utf-8"))
    assert persisted[0]["status"] == "failed"


def test_auto_source_retries_aliyun_only_for_network_errors(tmp_path):
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
        "system-config",
        "aliyun",
    ]


def test_auto_source_uses_native_pip_configuration_first(tmp_path):
    with patch("qwenpaw.app.channels.dependencies.WORKING_DIR", tmp_path):
        service = ChannelDependencyService()
    job = InstallJob(
        id="configured-source-job",
        channel="telegram",
        requirements=["python-telegram-bot>=20.0"],
    )

    with patch.dict("os.environ", {}, clear=True):
        assert service._source_candidates(
            job,
        ) == [  # pylint: disable=protected-access
            (None, "system-config"),
            ("https://mirrors.aliyun.com/pypi/simple/", "aliyun"),
        ]


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
    ]
    service._append_attempted_source(  # pylint: disable=protected-access
        job,
        "custom:example.com",
    )

    public = job.public_dict()
    persisted = json.loads(
        (tmp_path / "channel_runtime" / "install_jobs.json").read_text(
            encoding="utf-8",
        ),
    )[0]
    serialized = json.dumps({"public": public, "persisted": persisted})
    assert "secret" not in serialized
    assert "user:" not in serialized
    assert public["attempted_sources"] == ["custom:example.com"]
    assert "owner_pid" not in public


def test_legacy_job_source_credentials_are_sanitized_on_load(tmp_path):
    state_dir = tmp_path / "channel_runtime"
    state_dir.mkdir()
    (state_dir / "install_jobs.json").write_text(
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

    with patch("qwenpaw.app.channels.dependencies.WORKING_DIR", tmp_path):
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
        (tmp_path / "channel_runtime" / "install_jobs.json").read_text(
            encoding="utf-8",
        ),
    )
    assert {item["id"] for item in payload} == {first_job.id, second_job.id}


def test_running_job_owned_by_another_process_is_not_marked_interrupted(
    tmp_path,
):
    state_dir = tmp_path / "channel_runtime"
    state_dir.mkdir()
    job = InstallJob(
        id="peer-job",
        channel="telegram",
        requirements=["python-telegram-bot>=20.0"],
        status="installing",
        owner_pid=456,
        owner_started_at=123.0,
    )
    (state_dir / "install_jobs.json").write_text(
        json.dumps([job.storage_dict()]),
        encoding="utf-8",
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
        restored = service.get_job(job.id)
    assert restored is not None
    assert restored.status == "installing"


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
            "No matching distribution found",
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
