# -*- coding: utf-8 -*-
"""Docker initialization, application identity, and stopped-data migration."""

from __future__ import annotations

import importlib.util
import configparser
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import time
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

SCRIPT = Path(__file__).resolve().parents[3] / "deploy/runtime_user.py"


@pytest.fixture
def runtime_user():
    if sys.platform == "win32":
        pytest.skip("The Docker entrypoint runs on Linux")
    spec = importlib.util.spec_from_file_location("runtime_user", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("uid,gid", [(1001, 1002), (501, 20), (0, 0)])
def test_identity_uses_container_visible_owner(
    runtime_user,
    monkeypatch,
    uid,
    gid,
):
    monkeypatch.setenv("QWENPAW_WORKING_DIR", "/workspace")
    monkeypatch.setattr(
        Path,
        "lstat",
        lambda _: SimpleNamespace(
            st_mode=stat.S_IFDIR,
            st_uid=uid,
            st_gid=gid,
        ),
    )
    assert runtime_user.shared_identity() == (Path("/workspace"), uid, gid)


@pytest.mark.parametrize("uid,gid", [(65534, 1000), (1000, 65534)])
def test_unmapped_owner_fails_before_application(
    runtime_user,
    monkeypatch,
    uid,
    gid,
):
    monkeypatch.setenv("QWENPAW_WORKING_DIR", "/workspace")
    monkeypatch.setattr(
        Path,
        "lstat",
        lambda _: SimpleNamespace(
            st_mode=stat.S_IFDIR,
            st_uid=uid,
            st_gid=gid,
        ),
    )
    with pytest.raises(ValueError, match="unmapped UID/GID"):
        runtime_user.shared_identity()


def test_shared_root_cannot_be_a_symlink(runtime_user, tmp_path, monkeypatch):
    link = tmp_path / "link"
    link.symlink_to(tmp_path, target_is_directory=True)
    monkeypatch.setenv("QWENPAW_WORKING_DIR", str(link))
    with pytest.raises(ValueError, match="absolute directory"):
        runtime_user.shared_identity()


def test_standalone_container_keeps_existing_identity(
    runtime_user,
    monkeypatch,
):
    monkeypatch.delenv("QWENPAW_RUNTIME_MODE", raising=False)
    execute = Mock()
    monkeypatch.setattr(runtime_user.os, "execvp", execute)
    runtime_user.main(["qwenpaw", "app"])
    execute.assert_called_once_with("qwenpaw", ["qwenpaw", "app"])


@pytest.mark.parametrize(
    "command",
    [["qwenpaw", "init"], ["qwenpaw", "app"], ["startxfce4"]],
)
def test_managed_process_drops_groups_gid_uid_before_exec(
    runtime_user,
    tmp_path,
    monkeypatch,
    command,
):
    monkeypatch.setenv("QWENPAW_RUNTIME_MODE", "hub")
    for name in ("WORKING", "SECRET", "BACKUP"):
        monkeypatch.setenv(f"QWENPAW_{name}_DIR", str(tmp_path))
    monkeypatch.setenv("HOME", "/root")
    monkeypatch.setenv("QWENPAW_DEPENDENCY_STATE_DIR", "/root/state")
    monkeypatch.setattr(
        runtime_user,
        "shared_identity",
        lambda: (tmp_path, 1001, 1002),
    )
    monkeypatch.setattr(runtime_user, "prepare_account", lambda *_: "member")
    monkeypatch.setattr(runtime_user.os, "geteuid", lambda: 0)
    monkeypatch.setattr(runtime_user.os, "chdir", lambda _: None)
    calls = []
    for method in ("setgroups", "setgid", "setuid"):
        monkeypatch.setattr(
            runtime_user.os,
            method,
            lambda value, method=method: calls.append((method, value)),
        )
    monkeypatch.setattr(
        runtime_user.os,
        "execvp",
        lambda *args: calls.append(("exec", args)),
    )
    runtime_user.main(command)
    assert calls == [
        ("setgroups", []),
        ("setgid", 1002),
        ("setuid", 1001),
        ("exec", (command[0], command)),
    ]
    assert os.environ["HOME"] == str(tmp_path)
    assert os.environ["USER"] == os.environ["LOGNAME"] == "member"
    assert os.environ["QWENPAW_DEPENDENCY_STATE_DIR"] == str(
        tmp_path / ".dependency-environments",
    )


def test_rootless_mapped_root_does_not_switch_to_host_uid(
    runtime_user,
    tmp_path,
    monkeypatch,
):
    monkeypatch.setenv("QWENPAW_RUNTIME_MODE", "hub")
    for name in ("WORKING", "SECRET", "BACKUP"):
        monkeypatch.setenv(f"QWENPAW_{name}_DIR", str(tmp_path))
    monkeypatch.setattr(
        runtime_user,
        "shared_identity",
        lambda: (tmp_path, 0, 0),
    )
    monkeypatch.setattr(runtime_user, "prepare_account", lambda *_: "root")
    monkeypatch.setattr(runtime_user.os, "geteuid", lambda: 0)
    monkeypatch.setattr(runtime_user.os, "getegid", lambda: 0)
    monkeypatch.setattr(runtime_user.os, "chdir", lambda _: None)
    switch = Mock(side_effect=AssertionError("changed rootless identity"))
    monkeypatch.setattr(runtime_user.os, "setuid", switch)
    monkeypatch.setattr(runtime_user.os, "execvp", Mock())
    runtime_user.main(["qwenpaw", "init"])
    switch.assert_not_called()


def test_normal_start_does_not_repair_shared_data(
    runtime_user,
    tmp_path,
    monkeypatch,
):
    monkeypatch.setenv("QWENPAW_RUNTIME_MODE", "hub")
    monkeypatch.setattr(
        runtime_user,
        "shared_identity",
        lambda: (tmp_path, 1001, 1002),
    )
    monkeypatch.setattr(runtime_user.os, "geteuid", lambda: 1003)
    repair = Mock()
    monkeypatch.setattr(runtime_user, "repair_tree", repair)
    with pytest.raises(PermissionError, match="Cannot assume"):
        runtime_user.main(["qwenpaw", "app"])
    repair.assert_not_called()


def test_repair_rejects_a_symlink_root(runtime_user, tmp_path):
    link = tmp_path / "link"
    link.symlink_to(tmp_path, target_is_directory=True)
    with pytest.raises(ValueError, match="Refusing ownership repair"):
        runtime_user.repair_tree(link, 1001, 1001)


def test_mountinfo_decodes_bind_paths(runtime_user, monkeypatch):
    monkeypatch.setattr(Path, "exists", lambda _: True)
    monkeypatch.setattr(
        Path,
        "read_text",
        lambda _, **kwargs: "1 2 0:3 / /workspace/nested\\040mount rw - tmpfs tmpfs rw\n",
    )
    assert runtime_user.mount_points() == {Path("/workspace/nested mount")}


@pytest.mark.skipif(
    sys.platform != "linux"
    or os.environ.get("QWENPAW_TEST_DOCKER_OWNERSHIP") != "1",
    reason="requires an explicitly opted-in disposable Linux root container",
)
def test_real_cross_uid_writes_and_stopped_data_repair(runtime_user, tmp_path):
    """Exercise real setuid, private atomic saves, and a legacy root inode."""
    assert os.geteuid() == 0
    # Let the managed user traverse pytest's parent directories.
    for parent in tmp_path.parents:
        if parent == Path("/tmp"):
            break
        parent.chmod(0o755)
    tmp_path.chmod(0o755)
    environment = {**os.environ, "QWENPAW_RUNTIME_MODE": "hub"}
    roots = []
    for name in ("WORKING", "SECRET", "BACKUP"):
        root = tmp_path / name.lower()
        root.mkdir(mode=0o700)
        os.chown(root, 12345, 12346)
        environment[f"QWENPAW_{name}_DIR"] = str(root)
        roots.append(root)
    working = roots[0]
    io_source = SCRIPT.parent.parent / "src/qwenpaw/utils/io_utils.py"
    writer = (
        "import importlib.util, os; from pathlib import Path; "
        f"spec=importlib.util.spec_from_file_location('io_utils', {str(io_source)!r}); "
        "module=importlib.util.module_from_spec(spec); spec.loader.exec_module(module); "
        "assert os.getuid()==12345 and os.getgid()==12346 and os.getgroups()==[]; "
        "assert Path.cwd()==Path(os.environ['HOME']); "
        "module.write_json_atomic(Path('config.json'), {'project_dir':'/app/working/projects/demo'}); "
        "module.write_json_atomic(Path('workspaces/default/agent.json'), {'updated':True}); "
        "module.write_json_atomic(Path(os.environ['QWENPAW_SECRET_DIR'])/'envs.json', {'secret':'test'})"
    )

    def run(*arguments):
        return subprocess.run(
            [sys.executable, "-I", str(SCRIPT), *arguments],
            env=environment,
            capture_output=True,
            text=True,
        )

    # First initialization, then a new process saving existing configuration.
    for _ in range(2):
        result = run(sys.executable, "-c", writer)
        assert result.returncode == 0, result.stderr
        for path in (
            working / "config.json",
            working / "workspaces/default/agent.json",
            roots[1] / "envs.json",
        ):
            assert (path.stat().st_uid, stat.S_IMODE(path.stat().st_mode)) == (
                12345,
                0o600,
            )

    # Recreate the old root-writer replacement bug and prove the Hub UID fails.
    config = working / "config.json"
    os.chown(config, 0, 0)
    reader = "from pathlib import Path; Path('config.json').read_text()"
    assert "PermissionError" in run(sys.executable, "-c", reader).stderr
    outside = tmp_path / "outside.json"
    outside.write_text("private")
    outside.chmod(0o600)
    (working / "outside-link").symlink_to(outside)
    result = run("--repair-data")
    assert result.returncode == 0, result.stderr
    assert outside.stat().st_uid == 0
    assert (config.stat().st_uid, stat.S_IMODE(config.stat().st_mode)) == (
        12345,
        0o600,
    )
    assert run(sys.executable, "-c", reader).returncode == 0
    assert run(sys.executable, "-c", writer).returncode == 0

    # The Hub also reads and rewrites real files as the non-root data owner,
    # including after reopening its persistent registry in a new process.
    hub_cycle = (
        "import sys, os; from pathlib import Path; "
        f"sys.path[:0]=[{str(SCRIPT.parent.parent)!r}, {str(SCRIPT.parent.parent / 'src')!r}]; "
        "from tests.unit.hub.test_service import _backend_service, _docker_config; "
        "from qwenpaw.hub.models import RuntimeRecord, RuntimeState; "
        "root=Path(os.environ['QWENPAW_WORKING_DIR']); "
        "control=root/'hub-control'; control.mkdir(exist_ok=True); "
        "service,_,backend=_backend_service(control, config=_docker_config('custom:test')); "
        "record=service.registry.get('private-runtime'); "
        "record or service.registry.create(RuntimeRecord("
        "runtime_id='private-runtime', tenant_id='tenant', owner_user_id='owner', "
        "provisioner='docker', host='127.0.0.1', port=0, state=RuntimeState.STOPPED, "
        "working_dir=root, secret_dir=Path(os.environ['QWENPAW_SECRET_DIR']), "
        "backup_dir=Path(os.environ['QWENPAW_BACKUP_DIR']), log_file=root/'app.log')); "
        "service.start('private-runtime'); service.stop('private-runtime'); "
        "service.start('private-runtime'); service.stop('private-runtime'); "
        "assert backend.start_calls==2; service.close()"
    )
    for _ in range(2):
        result = run(sys.executable, "-c", hub_cycle)
        assert result.returncode == 0, result.stderr
        assert config.stat().st_uid == 12345

    nested = working / "nested-mount"
    nested.mkdir()
    nested_file = nested / "config.json"
    nested_file.write_text("{}")
    nested_file.chmod(0o600)
    original_mount_points = runtime_user.mount_points
    runtime_user.mount_points = lambda: {nested}
    try:
        runtime_user.repair_tree(working, 12345, 12346)
        assert nested_file.stat().st_uid == 0
    finally:
        runtime_user.mount_points = original_mount_points
        nested_file.unlink()
        nested.rmdir()

    hardlink = working / "unsafe-hardlink"
    os.link(outside, hardlink)
    result = run("--repair-data")
    assert result.returncode != 0
    assert "hard link" in result.stderr
    assert outside.stat().st_uid == 0


@pytest.mark.skipif(
    sys.platform != "linux"
    or os.environ.get("QWENPAW_TEST_DOCKER_OWNERSHIP") != "1",
    reason="requires an explicitly opted-in disposable Linux root container",
)
def test_real_entrypoint_initializes_and_supervises_as_data_owner(tmp_path):
    """Use the actual entrypoint and Supervisor with a small application stub."""
    if not Path("/usr/bin/supervisord").exists() or not shutil.which(
        "envsubst",
    ):
        pytest.skip("requires Supervisor, system Python, and gettext")
    assert os.geteuid() == 0
    for parent in tmp_path.parents:
        if parent == Path("/tmp"):
            break
        parent.chmod(0o755)
    tmp_path.chmod(0o755)
    environment = {
        **os.environ,
        "QWENPAW_RUNTIME_MODE": "hub",
        "QWENPAW_AUTH_ENABLED": "true",
    }
    for name in ("WORKING", "SECRET", "BACKUP"):
        directory = tmp_path / name.lower()
        directory.mkdir(mode=0o700)
        os.chown(directory, 12345, 12346)
        environment[f"QWENPAW_{name}_DIR"] = str(directory)
    working = Path(environment["QWENPAW_WORKING_DIR"])
    wrapper = Path("/usr/local/bin/qwenpaw-runtime-user")
    shutil.copyfile(SCRIPT, wrapper)
    wrapper.chmod(0o755)
    application = Path("/usr/local/bin/qwenpaw")
    application.write_text(
        f"#!{sys.executable}\n"
        "import json, os, sys, tempfile, time\n"
        "from pathlib import Path\n"
        "assert os.getuid() == 12345 and os.getgid() == 12346\n"
        "assert Path.cwd() == Path(os.environ['HOME'])\n"
        "path = Path('config.json')\n"
        "data = json.loads(path.read_text()) if path.exists() else {}\n"
        "data[sys.argv[1]] = data.get(sys.argv[1], 0) + 1\n"
        "fd, temporary = tempfile.mkstemp(dir='.')\n"
        "with os.fdopen(fd, 'w') as handle: json.dump(data, handle)\n"
        "os.replace(temporary, path)\n"
        "if sys.argv[1] == 'app': time.sleep(60)\n",
    )
    application.chmod(0o755)
    config = configparser.ConfigParser(interpolation=None)
    config.read(SCRIPT.parent / "config/supervisord.conf.template")
    # System/desktop services are outside this smoke test. Their real app
    # peer is still launched from the unmodified production app section.
    for section in ("program:dbus", "program:xvfb", "program:xfce4"):
        config.remove_section(section)
    template = Path("/etc/supervisor/conf.d/supervisord.conf.template")
    template.parent.mkdir(parents=True, exist_ok=True)
    with template.open("w") as stream:
        config.write(stream)
    for expected_boot in (1, 2):
        with (tmp_path / "supervisor.log").open("w") as output:
            process = subprocess.Popen(
                ["/bin/sh", str(SCRIPT.parent / "entrypoint.sh")],
                env=environment,
                stdout=output,
                stderr=subprocess.STDOUT,
            )
            try:
                deadline = time.monotonic() + 15
                while time.monotonic() < deadline:
                    path = working / "config.json"
                    if (
                        path.exists()
                        and json.loads(path.read_text()).get("app")
                        == expected_boot
                    ):
                        break
                    assert process.poll() is None, (
                        tmp_path / "supervisor.log"
                    ).read_text()
                    time.sleep(0.05)
                else:
                    pytest.fail((tmp_path / "supervisor.log").read_text())
                assert json.loads(path.read_text())["init"] == 1
                assert (
                    path.stat().st_uid,
                    stat.S_IMODE(path.stat().st_mode),
                ) == (12345, 0o600)
                assert Path("/var/log/supervisord.pid").stat().st_uid == 0
            finally:
                process.terminate()
                try:
                    process.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
