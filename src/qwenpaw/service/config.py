# -*- coding: utf-8 -*-
"""实例配置；不导入任何依赖环境变量的应用模块。"""

from __future__ import annotations

import json
import os
import sys
import sysconfig
import re
from dataclasses import dataclass, field
from pathlib import Path


class ServiceError(RuntimeError):
    """可安全展示的运维错误。"""


@dataclass
class ServiceConfig:
    path: Path
    working_dir: Path
    secret_dir: Path
    backup_dir: Path
    state_dir: Path
    log_dir: Path
    project_dir: Path
    python: str
    host: str = "127.0.0.1"
    port: int = 18089
    timeout: int = 120
    environment: dict[str, str] = field(default_factory=dict, repr=False)

    @classmethod
    def load(cls, path: str | Path) -> ServiceConfig:
        path = Path(path).expanduser().resolve()
        try:
            data = json.loads(path.read_text(encoding="utf-8-sig"))

            def location(key, default):
                value = Path(data.get(key, default)).expanduser()
                return (path.parent / value).resolve()

            working = location("working_dir", "../data/working")
            env = data.get("environment", {})
            if not isinstance(env, dict) or any(
                not isinstance(k, str)
                or not isinstance(v, str)
                or "\0" in k + v
                or "=" in k
                for k, v in env.items()
            ):
                raise ValueError()
            # 模板可引用进程环境，但缺失变量必须报错，不能启动到错误实例。
            env = {
                k: re.sub(
                    r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}",
                    lambda match: os.environ[match[1]],
                    v,
                )
                for k, v in env.items()
            }
            port = int(data.get("port", 18089))
            timeout = int(data.get("timeout", 120))
            host = data.get("host", "127.0.0.1")
            if (
                not 0 < port < 65536
                or not 5 <= timeout <= 1800
                or not isinstance(host, str)
            ):
                raise ValueError()
            return cls(
                path,
                working,
                location("secret_dir", str(working) + ".secret"),
                location("backup_dir", str(working) + ".backups"),
                location("state_dir", "../data/run"),
                location("log_dir", "../data/logs"),
                location("project_dir", ".."),
                str(location("python", sys.executable)),
                host,
                port,
                timeout,
                env,
            )
        except (OSError, ValueError, TypeError, AttributeError, KeyError):
            raise ServiceError(
                "实例配置无法读取或字段无效，请检查 JSON 配置文件"
            ) from None

    @property
    def pid_file(self):
        return self.state_dir / "service.pid.json"

    @property
    def stop_file(self):
        return self.state_dir / "stop.request"

    def child_env(self):
        # 实例相关变量必须全部来自配置，防止继承另一个终端实例。
        env = {
            k: v
            for k, v in os.environ.items()
            if not k.startswith(("QWENPAW_", "COPAW_"))
        }
        env.update(self.environment)
        if os.name == "nt" and not env.get("PROCESSOR_ARCHITECTURE"):
            arch = sysconfig.get_platform().split("-")[-1].upper()
            env["PROCESSOR_ARCHITECTURE"] = "x86" if arch == "WIN32" else arch
        env.update(
            {
                "QWENPAW_WORKING_DIR": str(self.working_dir),
                "QWENPAW_SECRET_DIR": str(self.secret_dir),
                "QWENPAW_BACKUP_DIR": str(self.backup_dir),
                "PYTHONIOENCODING": "utf-8",
                "PYTHONUTF8": "1",
            }
        )
        return env

    def command(self, action):
        return [self.python, "-m", "qwenpaw.service.worker", str(self.path), action]
