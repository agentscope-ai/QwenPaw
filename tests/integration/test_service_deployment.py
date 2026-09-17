"""部署命令在隔离 schema 中执行，不修改已有实例。"""

import json
import subprocess
import sys
from pathlib import Path

from qwenpaw.service.config import ServiceConfig


def test_database_container_init_script_works_with_checked_out_line_endings(
    postgres_test_schema,
):
    from postgres import DockerPostgresAdmin

    admin = DockerPostgresAdmin(postgres_test_schema.config)
    admin.drop_schema(postgres_test_schema.name)
    root = Path(__file__).resolve().parents[2]
    result = subprocess.run(
        [
            "docker",
            "exec",
            "-i",
            "--env",
            "POSTGRES_DB=" + postgres_test_schema.config.database,
            "--env",
            "WELDON_DB_SCHEMA=" + postgres_test_schema.name,
            postgres_test_schema.config.container,
            "sh",
            "-s",
        ],
        input=(root / "deploy/postgres-init.sh").read_bytes(),
        capture_output=True,
        timeout=30,
    )
    exists = admin.schema_exists(postgres_test_schema.name)
    if not exists:
        admin.create_schema(postgres_test_schema.name)
    assert result.returncode == 0, result.stderr.decode(
        "utf-8", errors="replace"
    )
    assert exists


def test_service_init_uses_real_compose_resolution(
    postgres_test_schema, tmp_path
):
    """Compose handles literal dollars and URL-sensitive password characters."""
    from sqlalchemy.engine import make_url

    root = Path(__file__).resolve().parents[2]
    env_file = tmp_path / "database.env"
    data_root = tmp_path / "external-data"
    env_file.write_text(
        f"WELDON_DATA_ROOT={data_root.as_posix()}\n"
        "WELDON_DB_USER=owner\nWELDON_DB_NAME=company\n"
        "WELDON_DB_SCHEMA=company\nWELDON_DB_PORT=55432\n"
        "WELDON_DB_PASSWORD='literal$pass:@/#%2026'\n",
        encoding="utf-8",
    )
    config_path = tmp_path / "service.json"
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "qwenpaw",
            "service",
            "--config",
            str(config_path),
            "init",
            "--env-file",
            str(env_file),
            "--fresh",
        ],
        cwd=root,
        capture_output=True,
        timeout=45,
    )
    assert result.returncode == 0, result.stderr.decode(
        "utf-8", errors="replace"
    )
    config = ServiceConfig.load(config_path)
    url = make_url(config.environment["QWENPAW_DATABASE_URL"])
    assert url.password == "literal$pass:@/#%2026"
    assert url.username == "owner"
    assert url.port == 55432
    assert config.working_dir == data_root / "working"
    assert b"literal$pass" not in result.stdout + result.stderr


def test_database_upgrade_is_explicit_and_repeatable(
    postgres_test_schema, tmp_path
):
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
    # 首次部署可能完全没有 schema（例如容器初始化脚本未执行）。
    from postgres import DockerPostgresAdmin

    admin = DockerPostgresAdmin(postgres_test_schema.config)
    admin.drop_schema(postgres_test_schema.name)
    for _ in range(2):
        result = subprocess.run(
            c.command("upgrade"),
            cwd=root,
            env=c.child_env(),
            capture_output=True,
            timeout=90,
        )
        if not admin.schema_exists(postgres_test_schema.name):
            admin.create_schema(postgres_test_schema.name)
        assert result.returncode == 0, result.stderr.decode(
            "utf-8", errors="replace"
        )

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
    assert result.returncode == 0, result.stderr.decode(
        "utf-8", errors="replace"
    )
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
                {
                    "username": "deployment-admin",
                    "password": "Deployment-test!2026",
                }
            ).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(request, timeout=15) as response:
            result = json.load(response)
            assert result.get("token")
            assert result["user"]["platform_role"] == "admin"
        # 首次注册后立即创建会话，不依赖重启或已存在的管理员。
        request = urllib.request.Request(
            f"http://127.0.0.1:{c.port}/api/chats",
            data=json.dumps(
                {
                    "session_id": "first-deployment-chat",
                    "user_id": "ignored",
                    "name": "First chat",
                }
            ).encode(),
            headers={
                "Content-Type": "application/json",
                "Authorization": "Bearer " + result["token"],
                "X-Agent-Id": "default",
            },
            method="POST",
        )
        with opener.open(request, timeout=30) as response:
            chat = json.load(response)
        assert (
            admin.execute(
                f'SELECT count(*) FROM "{postgres_test_schema.name}".conversations WHERE id = \'{chat["id"]}\''
            )
            == "1"
        )
    finally:
        manager.stop(c, force=True)
    assert manager.status(c)["state"] == "stopped"
    manager.assert_port_available(c)
