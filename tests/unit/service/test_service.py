import json
from pathlib import Path

import pytest

from qwenpaw.service.config import ServiceConfig, ServiceError
from qwenpaw.service.manager import managed_process
from qwenpaw.service import manager


def config_file(tmp_path, **overrides):
    data = {
        "port": 18089,
        "working_dir": "../data/工作区",
        "state_dir": "run",
        "environment": {},
    }
    data.update(overrides)
    path = tmp_path / "service.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def test_relative_paths_use_config_parent(tmp_path):
    c = ServiceConfig.load(config_file(tmp_path))
    assert c.working_dir == (tmp_path / "../data/工作区").resolve()
    assert c.child_env()["QWENPAW_WORKING_DIR"] == str(c.working_dir)


def test_invalid_config_does_not_echo_secrets(tmp_path):
    with pytest.raises(ServiceError) as caught:
        ServiceConfig.load(config_file(tmp_path, port="password-secret"))
    assert "password-secret" not in str(caught.value)


def test_parent_database_settings_do_not_leak(tmp_path, monkeypatch):
    monkeypatch.setenv("QWENPAW_DATABASE_URL", "wrong-instance")
    c = ServiceConfig.load(config_file(tmp_path))
    assert "QWENPAW_DATABASE_URL" not in c.child_env()


def test_invalid_environment_type(tmp_path):
    with pytest.raises(ServiceError):
        ServiceConfig.load(config_file(tmp_path, environment={"X": {"secret": 1}}))


def test_reused_pid_not_owned(tmp_path, monkeypatch):
    c = ServiceConfig.load(config_file(tmp_path))
    c.state_dir.mkdir(parents=True)
    c.pid_file.write_text(json.dumps({"pid": 42, "created": 1}), encoding="utf-8")

    class Process:
        def create_time(self):
            return 2

    monkeypatch.setattr("qwenpaw.service.manager.psutil.Process", lambda pid: Process())
    assert managed_process(c) is None


def test_wrong_command_not_owned(tmp_path, monkeypatch):
    c = ServiceConfig.load(config_file(tmp_path))
    c.state_dir.mkdir(parents=True)
    c.pid_file.write_text(json.dumps({"pid": 42, "created": 1}), encoding="utf-8")

    class Process:
        def create_time(self):
            return 1

        def cmdline(self):
            return ["python", "other-service.py"]

    monkeypatch.setattr("qwenpaw.service.manager.psutil.Process", lambda pid: Process())
    assert managed_process(c) is None


def test_missing_environment_reference_is_safe(tmp_path):
    with pytest.raises(ServiceError):
        ServiceConfig.load(
            config_file(tmp_path, environment={"DSN": "${MISSING_SERVICE_SECRET_123}"})
        )


def test_environment_reference_resolves(tmp_path, monkeypatch):
    monkeypatch.setenv("SERVICE_TEST_SECRET", "credential")
    c = ServiceConfig.load(
        config_file(tmp_path, environment={"DSN": "${SERVICE_TEST_SECRET}"})
    )
    assert c.child_env()["DSN"] == "credential"
    assert "credential" not in repr(c)


def test_duplicate_start_does_not_spawn(tmp_path, monkeypatch):
    c = ServiceConfig.load(config_file(tmp_path))
    monkeypatch.setattr(manager, "managed_process", lambda c: object())
    monkeypatch.setattr(manager, "status", lambda c: {"state": "ready", "pid": 123})
    monkeypatch.setattr(manager, "check", lambda c: pytest.fail("must not start again"))
    assert manager.start(c)["pid"] == 123


def test_port_collision_is_not_killed(tmp_path):
    import socket

    c = ServiceConfig.load(config_file(tmp_path))
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        c.port = listener.getsockname()[1]
        with pytest.raises(ServiceError, match="端口"):
            manager.assert_port_available(c)
        assert listener.getsockname()[1] == c.port


def test_stop_foreign_pid_never_writes_request(tmp_path, monkeypatch):
    c = ServiceConfig.load(config_file(tmp_path))
    monkeypatch.setattr(manager, "managed_process", lambda c: None)
    assert manager.stop(c)["state"] == "stopped"
    assert not c.stop_file.exists()


def test_init_refuses_overwrite(tmp_path):
    from click.testing import CliRunner
    from qwenpaw.cli.service_cmd import service_group

    path = config_file(tmp_path)
    before = path.read_bytes()
    result = CliRunner().invoke(service_group, ["--config", str(path), "init"])
    assert result.exit_code != 0
    assert path.read_bytes() == before


@pytest.mark.parametrize("platform", ["win32", "linux"])
def test_new_template_keeps_data_outside_project(tmp_path, monkeypatch, platform):
    from qwenpaw.service.template import example_config

    monkeypatch.chdir(tmp_path)
    data = example_config(platform)
    assert Path(data["project_dir"]) == tmp_path
    from pathlib import PureWindowsPath, PurePosixPath

    path_type = PureWindowsPath if platform == "win32" else PurePosixPath
    for key in ("working_dir", "secret_dir", "backup_dir", "state_dir", "log_dir"):
        value = path_type(data[key])
        assert value.is_absolute()
        assert not value.is_relative_to(path_type(data["project_dir"]))


def test_init_external_config_records_project_directory(tmp_path, monkeypatch):
    from click.testing import CliRunner
    from qwenpaw.cli.service_cmd import service_group

    project = tmp_path / "source"
    project.mkdir()
    monkeypatch.chdir(project)
    path = tmp_path / "instance" / "service.json"
    result = CliRunner().invoke(service_group, ["--config", str(path), "init"])
    assert result.exit_code == 0, result.output
    c = ServiceConfig.load(path)
    assert c.project_dir == project
    assert not c.working_dir.is_relative_to(project)


def test_upgrade_requires_explicit_yes(tmp_path):
    from click.testing import CliRunner
    from qwenpaw.cli.service_cmd import service_group

    path = config_file(tmp_path)
    result = CliRunner().invoke(
        service_group, ["--config", str(path), "database-upgrade"]
    )
    assert result.exit_code != 0
    assert "--yes" in result.output


def test_instance_lock_rejects_concurrent_operation(tmp_path):
    c = ServiceConfig.load(config_file(tmp_path))
    with manager.instance_lock(c):
        with pytest.raises(ServiceError, match="另一个"):
            with manager.instance_lock(c):
                pytest.fail("lock not enforced")


def test_stale_health_is_not_ready(tmp_path, monkeypatch):
    import time

    c = ServiceConfig.load(config_file(tmp_path))
    c.state_dir.mkdir(parents=True)

    class Process:
        pid = 42

        def create_time(self):
            return 100

    monkeypatch.setattr(manager, "managed_process", lambda c: Process())
    health = {"pid": 42, "created": 100, "ready": True, "time": time.time() - 90}
    (c.state_dir / "health.json").write_text(json.dumps(health), encoding="utf-8")
    assert manager.ready(c) is False
