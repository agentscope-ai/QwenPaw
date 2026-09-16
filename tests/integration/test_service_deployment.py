"""部署命令在隔离 schema 中执行，不修改已有实例。"""

import json
import subprocess
import sys
from pathlib import Path

from qwenpaw.service.config import ServiceConfig


def test_database_upgrade_is_explicit_and_repeatable(postgres_test_schema, tmp_path):
    root = Path(__file__).resolve().parents[2]
    path = tmp_path / "service.json"
    path.write_text(
        json.dumps(
            {
                "python": sys.executable,
                "project_dir": str(root),
                "working_dir": str(tmp_path / "working"),
                "state_dir": str(tmp_path / "run"),
                "environment": {
                    "QWENPAW_MULTI_USER_ENABLED": "true",
                    "QWENPAW_STORAGE_MODE": "postgres",
                    "QWENPAW_DATABASE_URL": postgres_test_schema.async_url(),
                    "QWENPAW_DATABASE_SCHEMA": postgres_test_schema.name,
                },
            }
        ),
        encoding="utf-8",
    )
    c = ServiceConfig.load(path)
    for _ in range(2):
        result = subprocess.run(
            c.command("upgrade"),
            cwd=root,
            env=c.child_env(),
            capture_output=True,
            timeout=90,
        )
        assert result.returncode == 0, result.stderr.decode("utf-8", errors="replace")

    # 沿用公开初始化入口，关闭测试环境遥测，避免发送环境信息。
    c.working_dir.mkdir(parents=True, exist_ok=True)
    (c.working_dir / ".telemetry_collected").write_text(
        '{"opted_out": true}', encoding="utf-8"
    )
    result = subprocess.run(
        [c.python, "-m", "qwenpaw", "init", "--defaults", "--accept-security"],
        cwd=root,
        env=c.child_env(),
        capture_output=True,
        timeout=120,
    )
    assert result.returncode == 0, result.stderr.decode("utf-8", errors="replace")
    assert (c.working_dir / "config.json").is_file()

    # 新建 schema 无旧数据需要迁移；在实际初始化完成后声明切换。
    import socket
    import urllib.request
    from qwenpaw.service import manager

    data = json.loads(path.read_text(encoding="utf-8"))
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        data["port"] = listener.getsockname()[1]
    data["log_dir"] = str(tmp_path / "logs")
    for suffix in (
        "VALIDATED_DOMAINS",
        "LEGACY_FROZEN_DOMAINS",
        "POSTGRES_WRITES_DOMAINS",
    ):
        data["environment"]["QWENPAW_CUTOVER_" + suffix] = "all"
    path.write_text(json.dumps(data), encoding="utf-8")
    c = ServiceConfig.load(path)
    try:
        first = manager.start(c)
        assert first["state"] == "ready"
        assert manager.start(c)["pid"] == first["pid"]
        request = urllib.request.Request(
            f"http://127.0.0.1:{c.port}/api/auth/register",
            data=json.dumps(
                {"username": "deployment-admin", "password": "Deployment-test!2026"}
            ).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(request, timeout=15) as response:
            result = json.load(response)
            assert result.get("token")
            assert result["user"]["platform_role"] == "admin"
    finally:
        manager.stop(c, force=True)
    assert manager.status(c)["state"] == "stopped"
    manager.assert_port_available(c)
