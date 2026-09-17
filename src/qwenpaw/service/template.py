# -*- coding: utf-8 -*-
"""无凭据的实例配置模板。"""

import sys
import json
import subprocess
from pathlib import Path

from .config import ServiceError


def example_config(platform=None):
    platform = platform or sys.platform
    windows = platform == "win32"
    root = "C:/ProgramData/QwenPaw" if windows else "/var/lib/qwenpaw"
    return {
        "python": sys.executable,
        "project_dir": str(Path.cwd().resolve()),
        "host": "127.0.0.1",
        "port": 18089,
        "timeout": 120,
        "working_dir": f"{root}/working",
        "secret_dir": f"{root}/secrets",
        "backup_dir": f"{root}/backups",
        "state_dir": f"{root}/run",
        "log_dir": f"{root}/logs" if windows else "/var/log/qwenpaw",
        "environment": {
            "QWENPAW_MULTI_USER_ENABLED": "true",
            "QWENPAW_STORAGE_MODE": "postgres",
            "QWENPAW_DATABASE_URL": "postgresql://qwenpaw:CHANGE_ME@127.0.0.1:5432/qwenpaw",
            "QWENPAW_DATABASE_SCHEMA": "qwenpaw",
            "QWENPAW_CUTOVER_VALIDATED_DOMAINS": "",
            "QWENPAW_CUTOVER_LEGACY_FROZEN_DOMAINS": "",
            "QWENPAW_CUTOVER_POSTGRES_WRITES_DOMAINS": "",
        },
    }


def database_host_config(env_file: Path) -> dict:
    """Use Compose's own interpolation rules; never echo its credential-bearing output."""
    from sqlalchemy.engine import URL

    project = Path.cwd().resolve()
    try:
        result = subprocess.run(
            [
                "docker",
                "compose",
                "--project-name",
                "weldonagent-database",
                "--env-file",
                str(env_file.resolve()),
                "--file",
                str(project / "deploy/compose.database.yml"),
                "config",
                "--format",
                "json",
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=30,
        )
        if result.returncode:
            raise ValueError()
        service = json.loads(result.stdout)["services"]["agent-pg"]
        # Compose re-escapes dollars when serializing a reusable config.
        env = {
            key: value.replace("$$", "$")
            for key, value in service["environment"].items()
        }
        port = next(p for p in service["ports"] if int(p["target"]) == 5432)
        volume = next(
            v
            for v in service["volumes"]
            if v["target"] == "/var/lib/postgresql/data"
            and v["type"] == "bind"
        )
        root = Path(volume["source"]).parent
        if not root.is_absolute():
            raise ValueError()
        password = env["POSTGRES_PASSWORD"]
        if not password or password.upper() in {
            "CHANGE_ME",
            "REPLACE_WITH_RANDOM_PASSWORD",
        }:
            raise ValueError()
        host = port.get("host_ip") or "127.0.0.1"
        if host in {"0.0.0.0", "::"}:
            host = "127.0.0.1"
        url = URL.create(
            "postgresql",
            username=env["POSTGRES_USER"],
            password=password,
            host=host,
            port=int(port["published"]),
            database=env["POSTGRES_DB"],
        )
        data = example_config()
        for field, directory in (
            ("working_dir", "working"),
            ("secret_dir", "secrets"),
            ("backup_dir", "backups"),
            ("state_dir", "run"),
            ("log_dir", "logs"),
        ):
            data[field] = str(root / directory)
        data["environment"].update(
            {
                "QWENPAW_DATABASE_URL": url.render_as_string(
                    hide_password=False
                ),
                "QWENPAW_DATABASE_SCHEMA": env["WELDON_DB_SCHEMA"],
            }
        )
        return data
    except (
        OSError,
        subprocess.SubprocessError,
        ValueError,
        KeyError,
        TypeError,
        StopIteration,
        AttributeError,
    ):
        raise ServiceError(
            "无法读取数据库 Compose 配置；请在项目根目录执行，检查 Docker Compose v2、"
            "--env-file 路径、数据库密码、端口和数据目录配置"
        ) from None
